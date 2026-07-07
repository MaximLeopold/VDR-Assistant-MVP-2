"""Filter supported and unsupported files.

Responsibilities:

- Accept supported document types.
- Ignore unsupported file types.
- Ignore temporary system files.
- Report skipped files.

Initial supported file types:

- PDF
- PPTX
- DOCX

Initial ignored file types:

- XLSX
- XLS
- XLSM
- CSV

Excel support will be added in a later version.
"""

"""File filtering for VDR ingestion.

This module classifies scanned files before upload.

It does not upload files.
It only determines whether files should be included, ignored,
or marked as unsupported.
"""


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".txt",
    ".md",
}

IGNORED_FILENAMES = {
    ".ds_store",
    "thumbs.db",
}

IGNORED_PREFIXES = (
    "~$",
)


def classify_file(file_record: dict) -> dict:
    """Classify a scanned file record.

    Args:
        file_record:
            File metadata returned by scan_vdr_folder.

    Returns:
        A copy of the file record with classification fields added.
    """

    classified = file_record.copy()

    filename = classified["filename"].lower()
    extension = classified["extension"].lower()
    size_bytes = classified["size_bytes"]

    if filename in IGNORED_FILENAMES:
        classified["status"] = "ignored"
        classified["reason"] = "Ignored system file"
        return classified

    if filename.startswith(IGNORED_PREFIXES):
        classified["status"] = "ignored"
        classified["reason"] = "Ignored temporary Office file"
        return classified

    if size_bytes == 0:
        classified["status"] = "ignored"
        classified["reason"] = "Empty file"
        return classified

    if extension not in SUPPORTED_EXTENSIONS:
        classified["status"] = "unsupported"
        classified["reason"] = f"Unsupported file extension: {extension}"
        return classified

    classified["status"] = "supported"
    classified["reason"] = "Supported file type"
    return classified


def classify_files(file_records: list[dict]) -> list[dict]:
    """Classify multiple scanned file records."""

    return [classify_file(file_record) for file_record in file_records]
