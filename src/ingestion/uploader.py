"""Narrow OpenAI file upload operations for VDR ingestion."""

from pathlib import Path
from src.ingestion.file_filter import SUPPORTED_EXTENSIONS
import time

from openai import OpenAI
from openai.types.file_object import FileObject
from openai.types.vector_stores.vector_store_file import VectorStoreFile


class DefinitePreRemoteUploadError(Exception):
    """Local failure proved to occur before files.create."""


def ingestion_client(client):
    # Fake adapters are accepted by offline tests; actual SDK clients are cloned.
    return client.with_options(max_retries=0) if isinstance(client, OpenAI) else client


def upload_openai_file(
    client: OpenAI,
    local_path: Path,
) -> FileObject:
    """Upload one local file for use with OpenAI File Search."""

    if local_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise DefinitePreRemoteUploadError("Only direct document formats and generated Markdown proxies may be uploaded. Raw workbooks are not upload targets.")
    try:
        file_stream = local_path.open("rb")
    except OSError as error:
        raise DefinitePreRemoteUploadError(str(error)) from error
    with file_stream:
        client = ingestion_client(client)
        return client.files.create(
            file=file_stream,
            purpose="assistants",
        )


def attach_file_and_poll(
    client: OpenAI,
    vector_store_id: str,
    file_id: str,
    *,
    max_wait_seconds: float = 120,
    poll_interval_seconds: float = 1,
) -> VectorStoreFile:
    """Attach once, then perform bounded initial read-only indexing polling.

    This is not a restart/resume service. On timeout the workflow retains the
    known file ID and in-progress state and refuses another file creation.
    SDK request timeouts are capped by the remaining wait; individual HTTP
    connection/read/write phases still follow the SDK's timeout semantics.
    """
    if max_wait_seconds <= 0 or poll_interval_seconds <= 0:
        raise ValueError("Indexing wait and poll interval must be positive.")
    deadline = time.monotonic() + max_wait_seconds
    client = ingestion_client(client)
    if isinstance(client, OpenAI):
        client = client.with_options(timeout=min(max_wait_seconds, 30))
    remote = client.vector_stores.files.create(
        file_id=file_id, vector_store_id=vector_store_id
    )
    while getattr(remote, "status", None) == "in_progress":
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "Initial indexing wait expired; preserve the known file ID and do not re-upload."
            )
        time.sleep(min(poll_interval_seconds, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "Initial indexing wait expired; preserve the known file ID and do not re-upload."
            )
        if isinstance(client, OpenAI):
            client = client.with_options(timeout=min(remaining, 30))
        remote = client.vector_stores.files.retrieve(
            file_id, vector_store_id=vector_store_id
        )
    return remote
