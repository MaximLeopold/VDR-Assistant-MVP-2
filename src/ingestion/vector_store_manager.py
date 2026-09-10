"""Direct OpenAI vector-store operations for case ingestion.

This module deliberately does not load manifests or manage vector-store
files. Case-level lifecycle decisions live in ``case_vector_store.py``.
"""

from __future__ import annotations

import re
from src.ingestion.openai_policy import mutation_client, read_client

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from openai import NotFoundError as OpenAINotFoundError
from openai.types.file_object import FileObject
from openai.types.vector_store import VectorStore
from openai.types.vector_stores.vector_store_file import VectorStoreFile


class VectorStoreError(Exception):
    """Base error for direct vector-store operations."""


class InvalidVectorStoreIdError(VectorStoreError):
    """Raised when a vector-store ID is blank or invalid."""


class VectorStoreNotAccessibleError(VectorStoreError):
    """Raised when a vector store cannot be found or accessed."""


class VectorStoreAuthenticationError(VectorStoreError):
    """Raised when OpenAI rejects the configured credentials."""


class VectorStorePermissionError(VectorStoreError):
    """Raised when credentials lack permission for the operation."""


class VectorStoreConnectionError(VectorStoreError):
    """Raised when OpenAI cannot be reached."""


class VectorStoreTimeoutError(VectorStoreError):
    """Raised when an OpenAI request times out."""


class VectorStoreRateLimitError(VectorStoreError):
    """Raised when OpenAI rate-limits the operation."""


class VectorStoreAPIError(VectorStoreError):
    """Raised for another OpenAI API or status error."""


class VectorStoreIdMismatchError(VectorStoreError):
    """Raised when retrieval returns a different vector-store ID."""


class InvalidCaseNameError(VectorStoreError):
    """Raised when a vector store cannot be named from the case."""


class InvalidOpenAIFileIdError(VectorStoreError):
    """Raised when an OpenAI file ID is blank or invalid."""


class OpenAIFileIdMismatchError(VectorStoreError):
    """Raised when file retrieval returns a different OpenAI file ID."""


class VectorStoreCreationError(VectorStoreError):
    """Raised when OpenAI does not create a usable vector store."""


def normalize_vector_store_id(vector_store_id: str) -> str:
    """Return a trimmed non-empty vector-store ID."""

    if not isinstance(vector_store_id, str) or not vector_store_id.strip():
        raise InvalidVectorStoreIdError("The OpenAI vector-store ID must not be blank.")
    return vector_store_id.strip()


def _status_description(error: APIStatusError) -> str:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        return "OpenAI returned an API error."
    return f"OpenAI returned API status {status_code}."


def _raise_retrieval_error(error: Exception) -> None:
    if isinstance(error, OpenAINotFoundError):
        raise VectorStoreNotAccessibleError(
            "The vector store was not found or is inaccessible. "
            "The ID may belong to another OpenAI project."
        ) from error
    if isinstance(error, AuthenticationError):
        raise VectorStoreAuthenticationError(
            "OpenAI authentication failed while retrieving the vector store."
        ) from error
    if isinstance(error, PermissionDeniedError):
        raise VectorStorePermissionError(
            "OpenAI denied permission to retrieve the vector store."
        ) from error
    if isinstance(error, APITimeoutError):
        raise VectorStoreTimeoutError(
            "The OpenAI request timed out while retrieving the vector store."
        ) from error
    if isinstance(error, RateLimitError):
        raise VectorStoreRateLimitError(
            "OpenAI rate-limited the vector-store retrieval request."
        ) from error
    if isinstance(error, APIConnectionError):
        raise VectorStoreConnectionError(
            "Could not connect to OpenAI while retrieving the vector store."
        ) from error
    if isinstance(error, APIStatusError):
        raise VectorStoreAPIError(_status_description(error)) from error
    raise error


def retrieve_vector_store(
    client: OpenAI,
    vector_store_id: str,
) -> VectorStore:
    """Retrieve and validate one accessible OpenAI vector store."""

    requested_id = normalize_vector_store_id(vector_store_id)

    try:
        vector_store = read_client(client).vector_stores.retrieve(requested_id)
    except Exception as error:
        _raise_retrieval_error(error)
        raise  # pragma: no cover - _raise_retrieval_error always raises

    returned_id = getattr(vector_store, "id", None)
    if returned_id != requested_id:
        raise VectorStoreIdMismatchError(
            "OpenAI returned a vector store whose ID did not match " "the requested ID."
        )

    return vector_store


def create_vector_store(
    client: OpenAI,
    case_name: str,
) -> VectorStore:
    """Create exactly one empty OpenAI vector store for a case."""

    if not isinstance(case_name, str):
        raise InvalidCaseNameError("The case name must not be blank.")

    normalized_case_name = re.sub(r"\s+", " ", case_name).strip()
    if not normalized_case_name:
        raise InvalidCaseNameError("The case name must not be blank.")

    vector_store_name = f"VDR Assistant - {normalized_case_name}"

    try:
        vector_store = mutation_client(client).vector_stores.create(
            name=vector_store_name
        )
    except Exception as error:
        if isinstance(error, AuthenticationError):
            detail = "OpenAI authentication failed."
        elif isinstance(error, PermissionDeniedError):
            detail = "OpenAI denied permission."
        elif isinstance(error, APITimeoutError):
            detail = "The OpenAI request timed out."
        elif isinstance(error, RateLimitError):
            detail = "OpenAI rate-limited the request."
        elif isinstance(error, APIConnectionError):
            detail = "Could not connect to OpenAI."
        elif isinstance(error, APIStatusError):
            detail = _status_description(error)
        else:
            detail = "An unexpected OpenAI client error occurred."
        raise VectorStoreCreationError(
            f"Could not create the case vector store. {detail}"
        ) from error

    try:
        normalize_vector_store_id(getattr(vector_store, "id", None))
    except InvalidVectorStoreIdError as error:
        raise VectorStoreCreationError(
            "OpenAI returned a created vector store without a usable ID."
        ) from error

    return vector_store


def list_vector_store_files(
    client: OpenAI,
    vector_store_id: str,
) -> list[VectorStoreFile]:
    """Return every file attachment associated with a vector store."""

    requested_id = normalize_vector_store_id(vector_store_id)

    try:
        page = read_client(client).vector_stores.files.list(requested_id)
        return list(page)
    except Exception as error:
        _raise_retrieval_error(error)
        raise  # pragma: no cover - _raise_retrieval_error always raises


def retrieve_openai_file(
    client: OpenAI,
    file_id: str,
) -> FileObject:
    """Retrieve and validate one underlying OpenAI File object."""

    if not isinstance(file_id, str) or not file_id.strip():
        raise InvalidOpenAIFileIdError("The OpenAI file ID must not be blank.")
    requested_id = file_id.strip()

    try:
        openai_file = read_client(client).files.retrieve(requested_id)
    except Exception as error:
        _raise_retrieval_error(error)
        raise  # pragma: no cover - _raise_retrieval_error always raises

    if getattr(openai_file, "id", None) != requested_id:
        raise OpenAIFileIdMismatchError(
            "OpenAI returned a file whose ID did not match the requested ID."
        )

    return openai_file
