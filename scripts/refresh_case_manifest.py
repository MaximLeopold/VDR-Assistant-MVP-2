"""Append newly discovered local files to an existing case manifest."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.manifest_builder import build_manifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    load_manifest,
    save_manifest,
)


def normalize_vdr_folder_input(raw_path: str) -> str:
    """Normalize a normally pasted local folder path."""

    normalized = raw_path.strip()
    if (
        len(normalized) >= 2
        and normalized.startswith('"')
        and normalized.endswith('"')
    ):
        normalized = normalized[1:-1].strip()
    return normalized


def main() -> int:
    raw_path = input("Enter the selected local VDR folder path: ")
    vdr_folder = normalize_vdr_folder_input(raw_path)
    if not vdr_folder:
        print("A local VDR folder path is required.", file=sys.stderr)
        return 1

    try:
        existing_manifest = load_manifest(vdr_folder)
        scanned_manifest = build_manifest(vdr_folder)
    except Exception as error:
        print(f"Could not prepare the manifest refresh: {error}", file=sys.stderr)
        return 1

    existing_relative_paths = {
        record.relative_path
        for record in existing_manifest.files
    }
    new_records = [
        record
        for record in scanned_manifest.files
        if record.relative_path not in existing_relative_paths
    ]

    if not new_records:
        print("The manifest is current. No new files were found.")
        return 0

    print(f"Case name: {existing_manifest.case_name}")
    print(f"Selected VDR path: {Path(vdr_folder).expanduser().resolve()}")
    print(f"New files found: {len(new_records)}")
    print("\nNEW FILES")
    for record in new_records:
        print(
            f"- {record.relative_path} | "
            f"{record.classification_status} | "
            f"{record.classification_reason} | "
            f"{record.size_bytes} bytes"
        )

    confirmation = input(
        "\nType REFRESH to append these records to the manifest: "
    ).strip()
    if confirmation != "REFRESH":
        print("Manifest refresh aborted. The manifest was not saved.")
        return 2

    existing_manifest.files.extend(new_records)
    existing_manifest.total_files += len(new_records)
    existing_manifest.supported_files += sum(
        record.classification_status == "supported"
        for record in new_records
    )
    existing_manifest.unsupported_files += sum(
        record.classification_status == "unsupported"
        for record in new_records
    )
    existing_manifest.ignored_files += sum(
        record.classification_status == "ignored"
        for record in new_records
    )
    existing_manifest.error_files += sum(
        record.classification_status == "error"
        for record in new_records
    )

    try:
        manifest_path = save_manifest(existing_manifest, vdr_folder)
    except ManifestPersistenceError as error:
        print(
            f"Manifest refresh was not persisted: {error}",
            file=sys.stderr,
        )
        return 1

    print(f"Refreshed manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
