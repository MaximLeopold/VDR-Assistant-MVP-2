"""Build structured VDR manifests.

This module combines folder scanning and file classification into a
structured VDRManifest object.

It does not upload files.
It does not modify files.
It only prepares a structured manifest.
"""

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
                status=file["status"],
                reason=file["reason"],
            )
        )

    supported_files = [
        file
        for file in file_records
        if file.status == "supported"
    ]

    unsupported_files = [
        file
        for file in file_records
        if file.status == "unsupported"
    ]

    ignored_files = [
        file
        for file in file_records
        if file.status == "ignored"
    ]

    return VDRManifest(
        root_path=str(root_path),
        total_files=len(file_records),
        supported_files=len(supported_files),
        unsupported_files=len(unsupported_files),
        ignored_files=len(ignored_files),
        files=file_records,
    )