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
from typing import NamedTuple

from pydantic import ValidationError

from src.ingestion.manifest import VDRManifest


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
        raise ManifestPathError(
            f"Project folder is unavailable: {project_folder}"
        )

    assistant_folder = project_folder / "VDR Assistant"

    return ManifestPaths(
        vdr_folder=selected_folder,
        project_folder=project_folder,
        assistant_folder=assistant_folder,
        manifest_path=assistant_folder / "manifest.json",
        backup_path=assistant_folder / "manifest.backup.json",
    )


def _serialize_manifest(manifest: VDRManifest) -> str:
    """Serialize a manifest without machine-specific per-file paths."""

    data = manifest.model_dump(
        mode="json",
        exclude={"files": {"__all__": {"absolute_path"}}},
    )
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
            f"Could not write a temporary manifest file in {directory}: "
            f"{error}"
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


def create_manifest(
    manifest: VDRManifest,
    vdr_folder: str | Path,
) -> Path:
    """Create the first current manifest without overwriting one."""

    paths = derive_manifest_paths(vdr_folder)
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
        os.replace(temporary_path, paths.manifest_path)
        temporary_path = None
        return paths.manifest_path
    except OSError as error:
        raise ManifestPersistenceError(
            f"Could not create manifest {paths.manifest_path}: {error}"
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def save_manifest(
    manifest: VDRManifest,
    vdr_folder: str | Path,
) -> Path:
    """Save the newest state and retain exactly one previous backup."""

    paths = derive_manifest_paths(vdr_folder)
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
            os.replace(backup_temporary, paths.backup_path)
            backup_temporary = None

        os.replace(new_manifest_temporary, paths.manifest_path)
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
        if schema_version is not None and schema_version != 1:
            raise UnsupportedSchemaVersionError(
                f"Unsupported manifest schema version "
                f"{schema_version!r}: {path}"
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
        relative_path = Path(file_record.relative_path)
        candidate = (root / relative_path).resolve()

        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ManifestPathError(
                f"File relative path escapes the selected VDR root: "
                f"{file_record.relative_path}"
            ) from error

        file_record.absolute_path = str(candidate)

    return relinked
