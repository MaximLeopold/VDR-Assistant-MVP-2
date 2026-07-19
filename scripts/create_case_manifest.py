"""Create the first shared manifest for a selected local VDR folder."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.manifest_builder import build_manifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    create_manifest,
    derive_manifest_paths,
)


def normalize_vdr_folder_input(raw_path: str) -> str:
    """Normalize a normally pasted local folder path."""

    normalized = raw_path.strip()
    if len(normalized) >= 2 and normalized.startswith('"') and normalized.endswith('"'):
        normalized = normalized[1:-1].strip()
    return normalized


def main() -> int:
    raw_path = input("Enter the local VDR folder path: ")
    vdr_folder = normalize_vdr_folder_input(raw_path)

    if not vdr_folder:
        print("A local VDR folder path is required.", file=sys.stderr)
        return 1

    try:
        manifest = build_manifest(vdr_folder)
        paths = derive_manifest_paths(vdr_folder)
    except Exception as error:
        print(f"Could not prepare the case manifest: {error}", file=sys.stderr)
        return 1

    print(f"Selected VDR folder: {paths.vdr_folder}")
    print(f"Case name: {manifest.case_name}")
    print(f"Total files: {manifest.total_files}")
    print(f"Supported files: {manifest.supported_files}")
    print(f"Unsupported files: {manifest.unsupported_files}")
    print(f"Ignored files: {manifest.ignored_files}")
    print(f"Target manifest: {paths.manifest_path}")

    if paths.manifest_path.exists():
        print(
            f"A manifest already exists and will not be overwritten: "
            f"{paths.manifest_path}",
            file=sys.stderr,
        )
        return 1

    confirmation = input("Type CREATE to write this manifest: ").strip()
    if confirmation != "CREATE":
        print(
            "Manifest creation aborted. No folder or manifest was created."
        )
        return 2

    try:
        manifest_path = create_manifest(manifest, vdr_folder)
    except ManifestPersistenceError as error:
        if paths.manifest_path.exists():
            print(
                f"A manifest already exists and was not overwritten: "
                f"{paths.manifest_path}",
                file=sys.stderr,
            )
        else:
            print(f"Could not create the case manifest: {error}", file=sys.stderr)
        return 1

    print(f"Created manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
