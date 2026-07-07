#Example manifest definition and structure for the manifest builder 

"""Manifest models for VDR ingestion.

The manifest preserves the relationship between the original VDR file
structure and any future OpenAI upload/indexing metadata.

The relative VDR path is treated as the stable identity of a document
inside one VDR project.

Upload-related fields are included but remain empty until the upload
step is implemented.
"""

from pydantic import BaseModel


class VDRFileRecord(BaseModel):
    """Structured record for one file in a VDR folder."""

    absolute_path: str
    relative_path: str

    filename: str
    extension: str
    size_bytes: int

    status: str
    reason: str

    openai_file_id: str | None = None
    upload_status: str = "not_uploaded"


class VDRManifest(BaseModel):
    """Structured manifest representing one scanned VDR."""

    root_path: str

    total_files: int
    supported_files: int
    unsupported_files: int
    ignored_files: int

    files: list[VDRFileRecord]