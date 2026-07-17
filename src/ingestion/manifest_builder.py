"""Build structured VDR manifests.

This module combines folder scanning and file classification into a
structured VDRManifest object.

It does not upload files.
It does not modify files.
It only prepares a structured manifest.

This module coordinates the folder scanner, file filter, and manifest modules to produce a structured manifest for a local VDR folder.
"""

from datetime import datetime, timezone
from pathlib import Path

from src.ingestion.file_filter import classify_files
from src.ingestion.folder_scanner import scan_vdr_folder
from src.ingestion.manifest import (
    VDRFileRecord,
    VDRManifest,
)


def build_manifest(folder_path: str) -> VDRManifest:
    """Build a manifest for a local VDR folder."""

    root_path = Path(folder_path).expanduser().resolve()
    created_at = datetime.now(timezone.utc)

    scanned_files = scan_vdr_folder(str(root_path))
    classified_files = classify_files(scanned_files)

    file_records = []

    for file in classified_files:

        file_records.append(
            VDRFileRecord(
                absolute_path=file["absolute_path"],
                relative_path=file["relative_path"],
                filename=file["filename"],
                extension=file["extension"],
                size_bytes=file["size_bytes"],
                classification_status=file["classification_status"],
                classification_reason=file["classification_reason"],
            )
        )

    supported_files = [
        file
        for file in file_records
        if file.classification_status == "supported"
    ]

    unsupported_files = [
        file
        for file in file_records
        if file.classification_status == "unsupported"
    ]

    ignored_files = [
        file
        for file in file_records
        if file.classification_status == "ignored"
    ]

    error_files = [
        file
        for file in file_records
        if file.classification_status == "error"
    ]

    return VDRManifest(
        schema_version=1,
        case_name=root_path.parent.name,
        root_path=str(root_path),
        vector_store_id=None,
        created_at=created_at,
        updated_at=created_at,
        total_files=len(file_records),
        supported_files=len(supported_files),
        unsupported_files=len(unsupported_files),
        ignored_files=len(ignored_files),
        error_files=len(error_files),
        files=file_records,
    )
