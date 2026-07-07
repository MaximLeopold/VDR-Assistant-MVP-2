"""Manual test script for the VDR ingestion pipeline.

Run from the project root:

    python scripts/test_folder_scanner.py
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.ingestion.manifest_builder import build_manifest


def main() -> None:
    """Run the ingestion pipeline."""

    folder_path = (
        input("Enter the local VDR folder path to scan: ")
        .strip()
        .strip('"')
    )

    manifest = build_manifest(folder_path)

    print()
    print("=" * 80)
    print("VDR Manifest Summary")
    print("=" * 80)

    print(f"Root folder        : {manifest.root_path}")
    print(f"Total files        : {manifest.total_files}")
    print(f"Supported files    : {manifest.supported_files}")
    print(f"Unsupported files  : {manifest.unsupported_files}")
    print(f"Ignored files      : {manifest.ignored_files}")

    print()
    print("=" * 80)
    print("Files")
    print("=" * 80)

    for file in manifest.files:

        print(
            f"[{file.status.upper():11}] "
            f"{file.relative_path}"
        )


if __name__ == "__main__":
    main()