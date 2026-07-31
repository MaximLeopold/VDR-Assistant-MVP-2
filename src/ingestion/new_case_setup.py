"""Local preparation services for a new, unregistered VDR case.

The services in this module are deliberately limited to Phase 1:

- validate a technical case ID and an existing local VDR folder;
- build a read-only, structured scan preview;
- protect manifest creation with a deterministic preview fingerprint; and
- recognize resumable unregistered manifests.

This module never calls OpenAI and never writes a case registry.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Literal, Sequence

from src.config.case_registry import PreparedCase
from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_builder import build_manifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    create_manifest,
    derive_manifest_paths,
    load_manifest,
)
from src.ingestion.vector_store_manager import (
    InvalidVectorStoreIdError,
    normalize_vector_store_id,
)


CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class NewCaseSetupError(Exception):
    """Base error safe for the new-case setup workflow to classify."""


class NewCaseValidationError(NewCaseSetupError):
    """Raised when supplied setup data is invalid or unsafe."""


class ExistingManifestError(NewCaseSetupError):
    """Raised when manifest creation would overwrite an existing file."""


class StalePreviewError(NewCaseSetupError):
    """Raised when a reviewed folder preview no longer matches the folder."""


@dataclass(frozen=True)
class NewCasePreviewRow:
    """One safe, relative-path row in the setup scan preview."""

    relative_path: str
    extension: str
    size_bytes: int
    classification_status: str
    classification_reason: str

    def as_display_dict(self) -> dict[str, str | int]:
        """Return fields suitable for an internal Streamlit preview table."""

        return {
            "Relative path": self.relative_path,
            "Extension": self.extension,
            "Size (bytes)": self.size_bytes,
            "Classification": self.classification_status,
            "Reason": self.classification_reason,
        }


@dataclass(frozen=True)
class NewCasePreview:
    """Structured result of validating and inspecting one new-case folder."""

    case_id: str
    vdr_folder: Path
    case_name: str
    manifest_path: Path
    state: Literal["scan_preview", "resume_association", "phase1_complete"]
    total_files: int
    supported_files: int
    unsupported_files: int
    ignored_files: int
    error_files: int
    rows: tuple[NewCasePreviewRow, ...]
    fingerprint: str | None = None
    blockers: tuple[str, ...] = ()

    @property
    def can_create_manifest(self) -> bool:
        return (
            self.state == "scan_preview"
            and self.fingerprint is not None
            and not self.blockers
        )


@dataclass(frozen=True)
class ManifestCreationResult:
    """Persisted result of creating and reloading one initial manifest."""

    manifest_path: Path
    manifest: VDRManifest


def normalize_folder_input(raw_path: str) -> str:
    """Trim a pasted path and remove one matching pair of outer quotes."""

    normalized = raw_path.strip() if isinstance(raw_path, str) else ""
    if (
        len(normalized) >= 2
        and normalized.startswith('"')
        and normalized.endswith('"')
    ):
        normalized = normalized[1:-1].strip()
    return normalized


def normalize_new_case_id(raw_case_id: str) -> str:
    """Return a normalized new technical case ID or raise a safe error."""

    normalized = raw_case_id.strip().lower() if isinstance(raw_case_id, str) else ""
    if not normalized:
        raise NewCaseValidationError("A technical case ID is required.")
    if not CASE_ID_PATTERN.fullmatch(normalized):
        raise NewCaseValidationError(
            "Use 1-64 lower-case letters, numbers, hyphens, or underscores; "
            "the first character must be a letter or number."
        )
    return normalized


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve()))


def _is_within(path: Path, parent: Path) -> bool:
    path_key = _path_key(path)
    parent_key = _path_key(parent)
    try:
        return os.path.commonpath([path_key, parent_key]) == parent_key
    except ValueError:
        return False


def _validate_folder(
    raw_path: str,
    *,
    repository_root: str | Path,
) -> Path:
    normalized = normalize_folder_input(raw_path)
    if not normalized:
        raise NewCaseValidationError("A local VDR folder path is required.")

    candidate = Path(normalized).expanduser().resolve()
    if not candidate.exists():
        raise NewCaseValidationError("The selected folder does not exist.")
    if not candidate.is_dir():
        raise NewCaseValidationError("The selected path is not a folder.")
    if _is_within(candidate, Path(repository_root)):
        raise NewCaseValidationError(
            "Select a VDR folder outside the application repository."
        )
    return candidate


def _validate_case_id_uniqueness(
    case_id: str,
    registered_cases: Sequence[PreparedCase],
) -> None:
    if any(case.case_id.casefold() == case_id.casefold() for case in registered_cases):
        raise NewCaseValidationError("This case ID is already in use.")


def _validate_folder_uniqueness(
    vdr_folder: Path,
    registered_cases: Sequence[PreparedCase],
) -> None:
    folder_key = _path_key(vdr_folder)
    if any(_path_key(case.vdr_folder) == folder_key for case in registered_cases):
        raise NewCaseValidationError(
            "The selected folder is already registered as a prepared case."
        )


def _preview_rows(manifest: VDRManifest) -> tuple[NewCasePreviewRow, ...]:
    rows = [
        NewCasePreviewRow(
            relative_path=record.relative_path,
            extension=record.extension,
            size_bytes=record.size_bytes,
            classification_status=record.classification_status,
            classification_reason=record.classification_reason,
        )
        for record in manifest.files
    ]
    rows.sort(key=lambda row: (row.relative_path.casefold(), row.relative_path))
    return tuple(rows)


def manifest_preview_fingerprint(manifest: VDRManifest) -> str:
    """Fingerprint stable file metadata without reading document contents."""

    payload = [
        {
            "relative_path": row.relative_path,
            "size_bytes": row.size_bytes,
            "classification_status": row.classification_status,
            "classification_reason": row.classification_reason,
        }
        for row in _preview_rows(manifest)
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_vector_store_id(manifest: VDRManifest) -> str | None:
    try:
        return normalize_vector_store_id(manifest.vector_store_id)
    except InvalidVectorStoreIdError:
        return None


def _preview_from_manifest(
    *,
    case_id: str,
    vdr_folder: Path,
    manifest_path: Path,
    manifest: VDRManifest,
    state: Literal["scan_preview", "resume_association", "phase1_complete"],
    fingerprint: str | None,
    blockers: tuple[str, ...] = (),
) -> NewCasePreview:
    return NewCasePreview(
        case_id=case_id,
        vdr_folder=vdr_folder,
        case_name=manifest.case_name,
        manifest_path=manifest_path,
        state=state,
        total_files=manifest.total_files,
        supported_files=manifest.supported_files,
        unsupported_files=manifest.unsupported_files,
        ignored_files=manifest.ignored_files,
        error_files=manifest.error_files,
        rows=_preview_rows(manifest),
        fingerprint=fingerprint,
        blockers=blockers,
    )


def build_new_case_preview(
    raw_vdr_folder: str,
    raw_case_id: str,
    *,
    registered_cases: Sequence[PreparedCase],
    repository_root: str | Path,
) -> NewCasePreview:
    """Validate setup inputs and return a read-only Phase 1 preview/state."""

    case_id = normalize_new_case_id(raw_case_id)
    _validate_case_id_uniqueness(case_id, registered_cases)
    vdr_folder = _validate_folder(
        raw_vdr_folder,
        repository_root=repository_root,
    )
    _validate_folder_uniqueness(vdr_folder, registered_cases)
    paths = derive_manifest_paths(vdr_folder)

    if paths.manifest_path.exists():
        try:
            manifest = load_manifest(vdr_folder)
        except (ManifestPersistenceError, OSError) as error:
            raise NewCaseValidationError(
                "An existing manifest is invalid or unreadable. It was not changed."
            ) from error

        vector_store_id = _manifest_vector_store_id(manifest)
        state = "phase1_complete" if vector_store_id is not None else "resume_association"
        return _preview_from_manifest(
            case_id=case_id,
            vdr_folder=vdr_folder,
            manifest_path=paths.manifest_path,
            manifest=manifest,
            state=state,
            fingerprint=None,
        )

    try:
        manifest = build_manifest(str(vdr_folder))
    except (OSError, ValueError) as error:
        raise NewCaseValidationError(
            "The selected folder could not be scanned safely."
        ) from error

    if not manifest.case_name.strip():
        raise NewCaseValidationError(
            "A usable case name could not be derived from the selected folder."
        )

    blockers = (
        ("No supported documents were found.",)
        if manifest.supported_files == 0
        else ()
    )
    return _preview_from_manifest(
        case_id=case_id,
        vdr_folder=vdr_folder,
        manifest_path=paths.manifest_path,
        manifest=manifest,
        state="scan_preview",
        fingerprint=manifest_preview_fingerprint(manifest),
        blockers=blockers,
    )


def create_new_case_manifest(
    vdr_folder: str | Path,
    reviewed_fingerprint: str,
) -> ManifestCreationResult:
    """Create exactly the manifest represented by a reviewed scan preview."""

    paths = derive_manifest_paths(vdr_folder)
    if paths.manifest_path.exists():
        raise ExistingManifestError(
            "A manifest already exists and cannot be overwritten."
        )
    if not reviewed_fingerprint:
        raise StalePreviewError(
            "Scan and review the folder before creating the manifest."
        )

    try:
        manifest = build_manifest(str(paths.vdr_folder))
    except (OSError, ValueError) as error:
        raise NewCaseValidationError(
            "The selected folder could not be scanned safely."
        ) from error

    if manifest.supported_files == 0:
        raise NewCaseValidationError("No supported documents were found.")
    if manifest_preview_fingerprint(manifest) != reviewed_fingerprint:
        raise StalePreviewError(
            "The folder contents changed after the preview. Scan the folder "
            "again before creating the manifest."
        )

    try:
        manifest_path = create_manifest(manifest, paths.vdr_folder)
        persisted = load_manifest(paths.vdr_folder)
    except ManifestPersistenceError as error:
        if paths.manifest_path.exists():
            raise ExistingManifestError(
                "A manifest already exists and cannot be overwritten."
            ) from error
        raise NewCaseSetupError(
            "The manifest could not be created safely."
        ) from error

    return ManifestCreationResult(
        manifest_path=manifest_path,
        manifest=persisted,
    )
