"""Workbook-level capture, deterministic identity and atomic publication."""

import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from src.ingestion.local_io import publish_directory

from src.ingestion.excel_parser import (
    ExcelLimits,
    TRANSFORMATION_VERSION,
    parse_capture,
)
from src.ingestion.manifest import (
    ExcelPreprocessing,
    WorksheetSearchArtifact,
    VDRManifest,
)
from src.ingestion.manifest_persistence import (
    load_manifest,
    save_manifest,
    derive_manifest_paths,
    ManifestPersistenceError,
)
from src.ingestion.paths import managed_path, resolve_relative

log = logging.getLogger(__name__)


def identity(**values):
    return hashlib.sha256(
        json.dumps(
            {"identity_version": 1, **values},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def file_sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_mutable(manifest, *, content=False):
    if manifest.snapshot_state == "sealed":
        raise ManifestPersistenceError(
            "Sealed snapshots reject ingestion mutations. Create a fresh snapshot."
        )
    if content and manifest.vector_store_id:
        raise ManifestPersistenceError(
            "Vector-store association freezes inventory, generations, coverage and exclusions. Create a fresh snapshot."
        )


def workbook_record(manifest, relative_path):
    matches = [
        f
        for f in manifest.files
        if f.relative_path == relative_path and f.classification_status == "preprocess"
    ]
    if len(matches) != 1:
        raise ValueError("Select an exact preprocess workbook path.")
    return matches[0]


def exclude_workbook(root, relative_path, reason):
    manifest = load_manifest(root)
    require_mutable(manifest, content=True)
    record = workbook_record(manifest, relative_path)
    record.excel_preprocessing = ExcelPreprocessing(
        status="excluded", exclusion_reason=reason
    )
    record.derived_artifacts = []
    save_manifest(manifest, root)
    return load_manifest(root)


def validate_generation(output, artifacts, outputs):
    for artifact in artifacts:
        path = output / f"sheet_{artifact.worksheet_index:03d}.md"
        if path.read_bytes() != outputs[artifact.worksheet_index]:
            raise ValueError("Generated proxy bytes differ from serialized worksheet.")
        if (
            path.stat().st_size != artifact.size_bytes
            or file_sha256(path) != artifact.artifact_sha256
        ):
            raise ValueError("Generated proxy integrity check failed.")


def preprocess_workbook(
    root, relative_path, *, limits=None, manifest_saver=save_manifest
):
    limits = limits or ExcelLimits()
    paths = derive_manifest_paths(root)
    manifest = load_manifest(root)
    require_mutable(manifest, content=True)
    record = workbook_record(manifest, relative_path)
    record.excel_preprocessing = ExcelPreprocessing(status="processing")
    record.derived_artifacts = []
    # Nothing local is generated until this checkpoint is durable.
    manifest_saver(manifest, root)
    attempt = None
    expected = None
    try:
        attempts = managed_path(
            paths.vdr_folder, paths.assistant_folder, "derived/excel/.attempts"
        )
        attempts.mkdir(parents=True, exist_ok=True)
        attempt = Path(tempfile.mkdtemp(prefix="capture-", dir=attempts))
        capture = attempt / "source.xlsx"
        output = attempt / "output"
        output.mkdir()
        source = resolve_relative(paths.vdr_folder, relative_path)
        if source.stat().st_size > limits.source_bytes:
            raise ValueError(
                "Source workbook byte limit exceeded; reduce workbook size or raise source_bytes."
            )
        # Stream a bounded copy; never save/open the raw source with openpyxl.
        with source.open("rb") as incoming, capture.open("xb") as outgoing:
            copied = 0
            while chunk := incoming.read(1024 * 1024):
                copied += len(chunk)
                if copied > limits.source_bytes:
                    raise ValueError(
                        "Source workbook byte limit exceeded during capture."
                    )
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        source_hash = file_sha256(capture)
        generation = identity(
            original_relative_path=relative_path,
            source_sha256=source_hash,
            transformation_version=TRANSFORMATION_VERSION,
        )
        coverage, outputs = parse_capture(capture, relative_path, limits)
        artifacts = []
        for sheet in coverage:
            if sheet.outcome != "included":
                continue
            filename = f"sheet_{sheet.worksheet_index:03d}.md"
            data = outputs[sheet.worksheet_index]
            destination = output / filename
            with destination.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            artifacts.append(
                WorksheetSearchArtifact(
                    artifact_id=identity(
                        generation_id=generation, worksheet_index=sheet.worksheet_index
                    ),
                    worksheet_name=sheet.worksheet_name,
                    worksheet_index=sheet.worksheet_index,
                    proxy_relative_path=f"derived/excel/{generation}/{filename}",
                    size_bytes=destination.stat().st_size,
                    artifact_sha256=file_sha256(destination),
                )
            )
        prep = ExcelPreprocessing(
            status="completed",
            source_sha256=source_hash,
            transformation_version=TRANSFORMATION_VERSION,
            generation_id=generation,
            worksheets=coverage,
        )
        record.excel_preprocessing = prep
        record.derived_artifacts = artifacts
        VDRManifest.model_validate(manifest.model_dump())
        validate_generation(output, artifacts, outputs)
        # A fresh attempt may prove an existing immutable output equivalent;
        # metadata is compared as well as every persisted proxy byte hash.
        metadata = {
            "preprocessing": prep.model_dump(mode="json"),
            "artifacts": [a.model_dump(mode="json") for a in artifacts],
        }
        (output / "generation.json").write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        final = managed_path(
            paths.vdr_folder, paths.assistant_folder, f"derived/excel/{generation}"
        )
        if final.exists():
            if (
                json.loads((final / "generation.json").read_text(encoding="utf-8"))
                != metadata
            ):
                raise ValueError("Generation collision: immutable metadata differs.")
            if {p.name for p in final.iterdir()} != {p.name for p in output.iterdir()}:
                raise ValueError("Generation collision: output files differ.")
            for artifact in artifacts:
                published = managed_path(
                    paths.vdr_folder,
                    paths.assistant_folder,
                    artifact.proxy_relative_path,
                )
                if (
                    published.stat().st_size != artifact.size_bytes
                    or file_sha256(published) != artifact.artifact_sha256
                ):
                    raise ValueError(
                        "Generation collision: immutable artifact differs."
                    )
        else:
            publish_directory(output, final)
        expected = record.model_dump(mode="json")
        manifest_saver(manifest, root)
        persisted = load_manifest(root)
        if (
            workbook_record(persisted, relative_path).model_dump(mode="json")
            != expected
        ):
            raise ManifestPersistenceError(
                "Completed generation checkpoint could not be verified."
            )
        return persisted
    except Exception as error:
        # Save may have committed and then failed. Reload is authoritative.
        current = load_manifest(root)
        current_record = workbook_record(current, relative_path)
        if expected is not None and current_record.model_dump(mode="json") == expected:
            return current
        require_mutable(current, content=True)
        current_record.excel_preprocessing = ExcelPreprocessing(
            status="failed", last_error=f"{type(error).__name__}: {error}"
        )
        current_record.derived_artifacts = []
        manifest_saver(current, root)
        raise
    finally:
        if attempt is not None:
            try:
                checked = managed_path(
                    paths.vdr_folder,
                    paths.assistant_folder,
                    attempt.relative_to(paths.assistant_folder).as_posix(),
                )
                shutil.rmtree(checked)
            except Exception:
                log.warning(
                    "Could not clean Excel attempt %s; generation status is unchanged.",
                    attempt,
                    exc_info=True,
                )
