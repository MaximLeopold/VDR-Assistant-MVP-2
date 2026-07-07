"""Scan a Virtual Data Room (VDR) folder recursively.

Responsibilities:

- Walk through the complete folder tree.
- Detect every file and folder.
- Preserve the relative folder structure.
- Ignore temporary and hidden files.
- Return a structured representation of the VDR.

The folder scanner should never modify files.
It only discovers the VDR structure.
"""

"""Local VDR folder scanner.

This module scans a local VDR folder and returns basic metadata
for every file found recursively.

It does not upload files.
It does not modify files.
It only reads folder structure and file metadata.
"""

from pathlib import Path


def scan_vdr_folder(folder_path: str) -> list[dict]:
    """Scan a local VDR folder recursively.

    Args:
        folder_path:
            Path to the local VDR folder.

    Returns:
        A list of dictionaries containing basic file metadata.
    """

    root_path = Path(folder_path).expanduser().resolve()

    if not root_path.exists():
        raise FileNotFoundError(f"Folder does not exist: {root_path}")

    if not root_path.is_dir():
        raise NotADirectoryError(f"Path is not a folder: {root_path}")

    files = []

    for file_path in root_path.rglob("*"):
        if not file_path.is_file():
            continue

        relative_path = file_path.relative_to(root_path)

        files.append(
            {
                "absolute_path": str(file_path),
                "relative_path": relative_path.as_posix(),
                "filename": file_path.name,
                "extension": file_path.suffix.lower(),
                "size_bytes": file_path.stat().st_size,
            }
        )

    return files