"""Narrow OpenAI file upload operations for VDR ingestion."""

from pathlib import Path

from openai import OpenAI
from openai.types.file_object import FileObject
from openai.types.vector_stores.vector_store_file import VectorStoreFile


def upload_openai_file(
    client: OpenAI,
    local_path: Path,
) -> FileObject:
    """Upload one local file for use with OpenAI File Search."""

    with local_path.open("rb") as file_stream:
        return client.files.create(
            file=file_stream,
            purpose="assistants",
        )


def attach_file_and_poll(
    client: OpenAI,
    vector_store_id: str,
    file_id: str,
) -> VectorStoreFile:
    """Attach one OpenAI File and wait for vector-store indexing."""

    return client.vector_stores.files.create_and_poll(
        file_id,
        vector_store_id=vector_store_id,
    )
