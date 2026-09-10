"""Narrow OpenAI file upload operations for VDR ingestion."""

from pathlib import Path
from src.ingestion.file_filter import SUPPORTED_EXTENSIONS
import time

import httpx
from openai import OpenAI
from openai.types.file_object import FileObject
from openai.types.vector_stores.vector_store_file import VectorStoreFile
from src.ingestion.openai_policy import file_create_client, mutation_client, read_client
from src.ingestion.remote_errors import RemoteIdentityError, RemoteProtocolError


class DefinitePreRemoteUploadError(Exception):
    """Local failure proved to occur before files.create."""


def upload_openai_file(
    client: OpenAI,
    local_path: Path,
) -> FileObject:
    """Upload one local file for use with OpenAI File Search."""

    if local_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise DefinitePreRemoteUploadError(
            "Only direct document formats and generated Markdown proxies may be uploaded. Raw workbooks are not upload targets."
        )
    try:
        file_stream = local_path.open("rb")
    except OSError as error:
        raise DefinitePreRemoteUploadError(str(error)) from error
    with file_stream:
        client = file_create_client(client)
        return client.files.create(
            file=file_stream,
            purpose="assistants",
        )


def validate_attachment(remote, vector_store_id: str, file_id: str):
    if not isinstance(getattr(remote, "id", None), str) or not isinstance(
        getattr(remote, "vector_store_id", None), str
    ):
        raise RemoteProtocolError("Attachment response lacks resource IDs.")
    if (
        getattr(remote, "id", None) != file_id
        or getattr(remote, "vector_store_id", None) != vector_store_id
    ):
        raise RemoteIdentityError(
            "Attachment response does not match the requested File and store."
        )
    if getattr(remote, "status", None) not in {
        "completed",
        "in_progress",
        "failed",
        "cancelled",
    }:
        raise RemoteProtocolError("Attachment response has no recognized status.")
    return remote


def attach_file_and_poll(
    client: OpenAI,
    vector_store_id: str,
    file_id: str,
    *,
    max_wait_seconds: float = 10,
    poll_interval_seconds: float = 2,
) -> VectorStoreFile:
    """Attach once and opportunistically poll in a short scheduling window.

    An executing GET and its SDK retries may outlast the window. Expiry returns
    healthy in_progress, never a fabricated indexing failure. The caller must
    have already persisted and verified the exact File ID and attachment intent.
    """
    if max_wait_seconds <= 0 or poll_interval_seconds <= 0:
        raise ValueError("Indexing wait and poll interval must be positive.")
    reads = read_client(client)
    client = mutation_client(client)
    if isinstance(client, OpenAI):
        # Attachment transport timeouts are independent of the polling window.
        client = client.with_options(timeout=httpx.Timeout(30.0, connect=5.0))
    remote = client.vector_stores.files.create(
        file_id=file_id, vector_store_id=vector_store_id
    )
    validate_attachment(remote, vector_store_id, file_id)
    deadline = time.monotonic() + max_wait_seconds
    delay = 0.0
    while getattr(remote, "status", None) == "in_progress":
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if delay:
            time.sleep(min(delay, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if isinstance(reads, OpenAI):
            reads = reads.with_options(timeout=min(remaining, 5))
        remote = reads.vector_stores.files.retrieve(
            file_id, vector_store_id=vector_store_id
        )
        validate_attachment(remote, vector_store_id, file_id)
        delay = poll_interval_seconds if not delay else delay * 2
    return remote
