#Example manifest definition and structure for the manifest builder 

"""Manifest models for VDR ingestion.

The manifest preserves the relationship between the original VDR file
structure and any future OpenAI upload/indexing metadata.

The relative VDR path is treated as the stable identity of a document
inside one VDR project.

Upload-related fields are included but remain empty until the upload
step is implemented.

The manifest acts as invetory for the VDR - when OpenAI cites  a file the streamlit application
looks in the manifest to find the path of the file - this is how we can give the local VDR file
path as source! 

WE HAVE TO ADDRESS THE WEAKNESS THAT THE MANIFEST ONLY EXISTS IN THE PYTHON MEMORY AND ONCE THE SCRIPT STOPS IT DISSAPEARS!
"""

from typing import Literal

from pydantic import BaseModel


class VDRFileRecord(BaseModel):
    """Structured record for one file in a VDR folder."""

    absolute_path: str
    relative_path: str

    filename: str
    extension: str
    size_bytes: int

    checksum_sha256: str | None = None

    classification_status: Literal[
        "supported",
        "unsupported",
        "ignored",
        "error",
    ]
    classification_reason: str

    openai_file_id: str | None = None
    upload_status: Literal[
        "not_uploaded",
        "uploading",
        "uploaded",
        "failed",
    ] = "not_uploaded"

    indexing_status: Literal[
        "not_started",
        "in_progress",
        "completed",
        "failed",
    ] = "not_started"

    upload_attempts: int = 0
    last_error: str | None = None


class VDRManifest(BaseModel):
    """Structured manifest representing one scanned VDR."""

    root_path: str

    total_files: int
    supported_files: int
    unsupported_files: int
    ignored_files: int

    files: list[VDRFileRecord]
