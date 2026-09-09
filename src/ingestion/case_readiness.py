"""Strict, read-only readiness assessment for prepared VDR cases."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    load_manifest,
)
from src.ingestion.vector_store_manager import (
    InvalidVectorStoreIdError,
    normalize_vector_store_id,
)


@dataclass(frozen=True)
class CaseReadiness:
    """Structured result used to gate local case registration."""

    is_ready: bool
    supported_count: int
    completed_count: int
    unuploaded_count: int
    uploading_count: int
    indexing_in_progress_count: int
    failed_count: int
    classification_error_count: int
    blocking_reasons: tuple[str, ...]


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve()))


def manifest_belongs_to_folder(
    manifest: VDRManifest,
    vdr_folder: str | Path,
) -> bool:
    """Return whether the manifest root identifies the selected VDR folder."""

    if not isinstance(manifest.root_path, str) or not manifest.root_path.strip():
        return False
    try:
        return _path_key(Path(manifest.root_path)) == _path_key(Path(vdr_folder))
    except (OSError, RuntimeError, ValueError):
        return False


def _empty_readiness(reason: str) -> CaseReadiness:
    return CaseReadiness(
        is_ready=False,
        supported_count=0,
        completed_count=0,
        unuploaded_count=0,
        uploading_count=0,
        indexing_in_progress_count=0,
        failed_count=0,
        classification_error_count=0,
        blocking_reasons=(reason,),
    )


def assess_manifest_readiness(
    manifest: VDRManifest,
    vdr_folder: str | Path,
) -> CaseReadiness:
    """Assess a loaded manifest without mutating local or remote state."""

    try:
        manifest = VDRManifest.model_validate(manifest.model_dump())
    except ValueError:
        return _empty_readiness("Manifest v2 is structurally invalid.")
    reasons: list[str] = []
    root = Path(vdr_folder).expanduser().resolve()

    if not manifest_belongs_to_folder(manifest, root):
        reasons.append("The manifest does not belong to the selected VDR folder.")
    if not manifest.case_name.strip():
        reasons.append("The manifest does not contain a usable case name.")
    try:
        normalize_vector_store_id(manifest.vector_store_id)
    except InvalidVectorStoreIdError:
        reasons.append("The manifest does not contain a vector-store ID.")

    supported = []
    for record in manifest.files:
        if record.classification_status == "supported":
            supported.append(record)
        elif record.classification_status == "preprocess":
            prep = record.excel_preprocessing
            if prep is None or prep.status not in {"completed", "excluded"}:
                reasons.append(
                    f"{record.relative_path}: Excel preprocessing is incomplete."
                )
            elif prep.status == "completed":
                supported.extend(record.derived_artifacts)
    classification_error_count = sum(
        record.classification_status == "error" for record in manifest.files
    )
    completed_count = sum(
        bool(record.openai_file_id and record.openai_file_id.strip())
        and record.upload_status == "uploaded"
        and record.indexing_status == "completed"
        for record in supported
    )
    unuploaded_count = sum(
        record.upload_status == "not_uploaded" for record in supported
    )
    uploading_count = sum(record.upload_status == "uploading" for record in supported)
    indexing_in_progress_count = sum(
        record.indexing_status == "in_progress" for record in supported
    )
    failed_count = sum(
        record.upload_status == "failed" or record.indexing_status == "failed"
        for record in supported
    )

    if not supported:
        reasons.append("At least one searchable target is required.")
    if classification_error_count:
        reasons.append("The manifest contains classification errors.")
    if any(
        not isinstance(record.openai_file_id, str) or not record.openai_file_id.strip()
        for record in supported
    ):
        reasons.append("Every searchable target must have an OpenAI file ID.")
    if any(record.upload_status != "uploaded" for record in supported):
        reasons.append("Every searchable target must have completed upload.")
    if any(record.indexing_status != "completed" for record in supported):
        reasons.append("Every searchable target must have completed indexing.")

    return CaseReadiness(
        is_ready=not reasons,
        supported_count=len(supported),
        completed_count=completed_count,
        unuploaded_count=unuploaded_count,
        uploading_count=uploading_count,
        indexing_in_progress_count=indexing_in_progress_count,
        failed_count=failed_count,
        classification_error_count=classification_error_count,
        blocking_reasons=tuple(dict.fromkeys(reasons)),
    )


def assess_case_readiness(vdr_folder: str | Path) -> CaseReadiness:
    """Load and assess one case without changing its manifest or registry."""

    try:
        root = Path(vdr_folder).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return _empty_readiness("The selected VDR folder is invalid.")
    if not root.exists():
        return _empty_readiness("The selected VDR folder does not exist.")
    if not root.is_dir():
        return _empty_readiness("The selected VDR path is not a folder.")

    try:
        manifest = load_manifest(root)
    except ManifestPersistenceError:
        return _empty_readiness(
            "The case manifest is missing, inaccessible, or invalid."
        )
    except OSError:
        return _empty_readiness("The case manifest could not be accessed.")

    return assess_manifest_readiness(manifest, root)
