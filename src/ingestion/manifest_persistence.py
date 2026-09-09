"""Persist and relink VDR manifests.

Each selected data-room folder uses a sibling ``VDR Assistant`` folder
inside the same project folder. The current manifest and one backup are
stored there.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from src.ingestion.local_io import atomic_replace
from typing import NamedTuple

from pydantic import ValidationError

from src.ingestion.manifest import VDRManifest
from src.ingestion.paths import managed_path, resolve_relative, validate_disjoint_roots


class ManifestPersistenceError(Exception):
    """Base error for manifest persistence operations."""


class ManifestNotFoundError(ManifestPersistenceError):
    """Raised when a requested current or backup manifest is missing."""


class ManifestJSONError(ManifestPersistenceError):
    """Raised when a manifest does not contain valid JSON."""


class ManifestSchemaError(ManifestPersistenceError):
    """Raised when manifest JSON does not match the supported schema."""


class UnsupportedSchemaVersionError(ManifestSchemaError):
    """Raised when a manifest uses an unsupported schema version."""


class ManifestPathError(ManifestPersistenceError):
    """Raised when a selected VDR path is invalid."""


class ManifestPaths(NamedTuple):
    """Filesystem locations derived from a selected VDR folder."""

    vdr_folder: Path
    project_folder: Path
    assistant_folder: Path
    manifest_path: Path
    backup_path: Path


def derive_manifest_paths(vdr_folder: str | Path) -> ManifestPaths:
    """Derive manifest locations without creating any directories."""

    selected_folder = Path(vdr_folder).expanduser().resolve()

    if not selected_folder.exists():
        raise ManifestPathError(
            f"Selected VDR folder does not exist: {selected_folder}"
        )

    if not selected_folder.is_dir():
        raise ManifestPathError(
            f"Selected VDR path is not a directory: {selected_folder}"
        )

    project_folder = selected_folder.parent

    if not project_folder.exists() or not project_folder.is_dir():
        raise ManifestPathError(f"Project folder is unavailable: {project_folder}")

    assistant_folder = project_folder / "VDR Assistant"
    try:
        validate_disjoint_roots(selected_folder, assistant_folder)
        managed_path(selected_folder, assistant_folder, "manifest.json")
        managed_path(selected_folder, assistant_folder, "manifest.backup.json")
    except ValueError as error:
        raise ManifestPathError(str(error)) from error

    return ManifestPaths(
        vdr_folder=selected_folder,
        project_folder=project_folder,
        assistant_folder=assistant_folder,
        manifest_path=assistant_folder / "manifest.json",
        backup_path=assistant_folder / "manifest.backup.json",
    )


def _serialize_manifest(manifest: VDRManifest) -> str:
    """Serialize a manifest without machine-specific per-file paths."""

    data = VDRManifest.model_validate(manifest.model_dump()).model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _write_temporary_file(
    directory: Path,
    prefix: str,
    content: str | bytes,
) -> Path:
    """Write and fsync a uniquely named temporary file."""

    binary = isinstance(content, bytes)
    mode = "wb" if binary else "w"
    encoding = None if binary else "utf-8"

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode=mode,
            encoding=encoding,
            dir=directory,
            prefix=prefix,
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        return temporary_path
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ManifestPersistenceError(
            f"Could not write a temporary manifest file in {directory}: " f"{error}"
        ) from error


def _ensure_assistant_folder(paths: ManifestPaths) -> None:
    """Create the VDR Assistant folder when it does not exist."""

    try:
        paths.assistant_folder.mkdir(exist_ok=True)
    except OSError as error:
        raise ManifestPersistenceError(
            f"Could not create or access the VDR Assistant folder "
            f"{paths.assistant_folder}: {error}"
        ) from error


def _require_write_owner(manifest, paths):
    if (
        not manifest.root_path
        or Path(manifest.root_path).expanduser().resolve() != paths.vdr_folder
    ):
        raise ManifestPathError(
            "The manifest belongs to another source root. Use a distinct snapshot location."
        )


def create_manifest(
    manifest: VDRManifest,
    vdr_folder: str | Path,
) -> Path:
    """Create the first current manifest without overwriting one."""

    paths = derive_manifest_paths(vdr_folder)
    _require_write_owner(manifest, paths)
    _ensure_assistant_folder(paths)

    if paths.manifest_path.exists():
        raise ManifestPersistenceError(
            f"A current manifest already exists: {paths.manifest_path}"
        )

    temporary_path: Path | None = None

    try:
        temporary_path = _write_temporary_file(
            paths.assistant_folder,
            ".manifest-create-",
            _serialize_manifest(manifest),
        )
        atomic_replace(temporary_path, paths.manifest_path)
        temporary_path = None
        return paths.manifest_path
    except OSError as error:
        raise ManifestPersistenceError(
            f"Could not create manifest {paths.manifest_path}: {error}"
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


_REMOTE_FIELDS = {
    "openai_file_id",
    "upload_status",
    "indexing_status",
    "upload_attempts",
    "last_error",
}


def _content_identity(manifest):
    data = manifest.model_dump(mode="json")
    for key in ("updated_at", "snapshot_state"):
        data.pop(key, None)
    for record in data["files"]:
        for key in _REMOTE_FIELDS:
            record.pop(key, None)
        for artifact in record["derived_artifacts"]:
            for key in _REMOTE_FIELDS:
                artifact.pop(key, None)
    return data


def _guard_save(manifest, paths):
    _require_write_owner(manifest, paths)
    VDRManifest.model_validate(manifest.model_dump())
    if paths.manifest_path.exists():
        current = _load_manifest_file(paths.manifest_path, "Current")
        _require_write_owner(current, paths)
        if current.snapshot_state == "sealed":
            raise ManifestPersistenceError(
                "Sealed snapshots reject ingestion mutations."
            )
        if current.vector_store_id and _content_identity(current) != _content_identity(
            manifest
        ):
            raise ManifestPersistenceError(
                "Vector-store association freezes snapshot content and association."
            )
        if manifest.snapshot_state == "sealed":
            from src.ingestion.case_readiness import assess_manifest_readiness

            if not assess_manifest_readiness(manifest, paths.vdr_folder).is_ready:
                raise ManifestPersistenceError("Only a ready snapshot can be sealed.")
        # IDs can only progress from absent to known; never clear or substitute.
        current_owners = [r for f in current.files for r in [f, *f.derived_artifacts]]
        next_owners = [r for f in manifest.files for r in [f, *f.derived_artifacts]]
        if current.vector_store_id:
            for before, after in zip(current_owners, next_owners, strict=True):
                if (
                    before.openai_file_id
                    and before.openai_file_id != after.openai_file_id
                ):
                    raise ManifestPersistenceError(
                        "Known OpenAI IDs cannot be cleared or replaced."
                    )
                if (
                    before.indexing_status == "completed"
                    and before.model_dump() != after.model_dump()
                ):
                    raise ManifestPersistenceError(
                        "Completed upload targets are immutable."
                    )
                if (
                    before.upload_status in {"uploading", "uploaded", "failed"}
                    and after.upload_status == "not_uploaded"
                ):
                    raise ManifestPersistenceError(
                        "Upload uncertainty cannot be reset into an initial upload."
                    )
                if after.upload_attempts < before.upload_attempts:
                    raise ManifestPersistenceError(
                        "Upload attempt counters cannot decrease."
                    )


def save_manifest(
    manifest: VDRManifest,
    vdr_folder: str | Path,
) -> Path:
    """Save the newest state and retain exactly one previous backup."""

    paths = derive_manifest_paths(vdr_folder)
    _guard_save(manifest, paths)
    _ensure_assistant_folder(paths)

    previous_updated_at = manifest.updated_at
    new_manifest_temporary: Path | None = None
    backup_temporary: Path | None = None

    try:
        manifest.updated_at = datetime.now(timezone.utc)
        serialized_manifest = _serialize_manifest(manifest)

        new_manifest_temporary = _write_temporary_file(
            paths.assistant_folder,
            ".manifest-save-",
            serialized_manifest,
        )

        if paths.manifest_path.exists():
            try:
                current_content = paths.manifest_path.read_bytes()
            except OSError as error:
                raise ManifestPersistenceError(
                    f"Could not read the current manifest for backup "
                    f"{paths.manifest_path}: {error}"
                ) from error

            backup_temporary = _write_temporary_file(
                paths.assistant_folder,
                ".manifest-backup-",
                current_content,
            )
            atomic_replace(backup_temporary, paths.backup_path)
            backup_temporary = None

        atomic_replace(new_manifest_temporary, paths.manifest_path)
        new_manifest_temporary = None
        return paths.manifest_path
    except OSError as error:
        manifest.updated_at = previous_updated_at
        raise ManifestPersistenceError(
            f"Could not save manifest {paths.manifest_path}: {error}"
        ) from error
    except Exception:
        manifest.updated_at = previous_updated_at
        raise
    finally:
        if new_manifest_temporary is not None:
            new_manifest_temporary.unlink(missing_ok=True)
        if backup_temporary is not None:
            backup_temporary.unlink(missing_ok=True)


def _load_manifest_file(path: Path, label: str) -> VDRManifest:
    """Read and validate one current or backup manifest file."""

    if not path.exists():
        raise ManifestNotFoundError(f"{label} manifest not found: {path}")

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ManifestPersistenceError(
            f"Could not read {label.lower()} manifest {path}: {error}"
        ) from error

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise ManifestJSONError(
            f"{label} manifest contains malformed JSON at "
            f"line {error.lineno}, column {error.colno}: {path}"
        ) from error

    if isinstance(data, dict):
        schema_version = data.get("schema_version")
        if type(schema_version) is not int or schema_version != 2:
            raise UnsupportedSchemaVersionError(
                f"Unsupported manifest schema version "
                f"{schema_version!r}: {path}. Recreate the case under Manifest v2."
            )

    try:
        return VDRManifest.model_validate(data)
    except ValidationError as error:
        raise ManifestSchemaError(
            f"{label} manifest failed schema validation: {path}: {error}"
        ) from error


def load_manifest(vdr_folder: str | Path) -> VDRManifest:
    """Load and validate the current manifest only."""

    paths = derive_manifest_paths(vdr_folder)
    return _load_manifest_file(paths.manifest_path, "Current")


def load_backup_manifest(vdr_folder: str | Path) -> VDRManifest:
    """Explicitly load and validate the one retained backup."""

    paths = derive_manifest_paths(vdr_folder)
    return _load_manifest_file(paths.backup_path, "Backup")


def relink_manifest(
    manifest: VDRManifest,
    vdr_folder: str | Path,
) -> VDRManifest:
    """Return a manifest linked to a VDR root on the current machine."""

    paths = derive_manifest_paths(vdr_folder)
    root = paths.vdr_folder
    relinked = manifest.model_copy(deep=True)
    relinked.root_path = str(root)

    for file_record in relinked.files:
        try:
            resolve_relative(root, file_record.relative_path)
        except ValueError as error:
            raise ManifestPathError(
                f"File path escapes selected VDR: {file_record.relative_path}"
            ) from error
    return relinked
