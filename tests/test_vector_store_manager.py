from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import openai
import pytest

from src.ingestion.vector_store_manager import (
    InvalidCaseNameError,
    InvalidOpenAIFileIdError,
    InvalidVectorStoreIdError,
    OpenAIFileIdMismatchError,
    VectorStoreAPIError,
    VectorStoreAuthenticationError,
    VectorStoreConnectionError,
    VectorStoreCreationError,
    VectorStoreIdMismatchError,
    VectorStoreNotAccessibleError,
    VectorStorePermissionError,
    VectorStoreRateLimitError,
    VectorStoreTimeoutError,
    create_vector_store,
    list_vector_store_files,
    retrieve_openai_file,
    retrieve_vector_store,
)


def make_client() -> Mock:
    client = Mock()
    client.vector_stores = Mock()
    return client


def request() -> httpx.Request:
    return httpx.Request("GET", "https://api.openai.test/vector_stores/test")


def status_error(error_type, status_code: int):
    response = httpx.Response(status_code, request=request())
    return error_type("synthetic error", response=response, body=None)


def test_valid_retrieval_returns_remote_object() -> None:
    client = make_client()
    remote = SimpleNamespace(id="vs_test", name="Test")
    client.vector_stores.retrieve.return_value = remote

    assert retrieve_vector_store(client, "  vs_test ") is remote
    client.vector_stores.retrieve.assert_called_once_with("vs_test")


def test_blank_id_fails_before_api_call() -> None:
    client = make_client()

    with pytest.raises(InvalidVectorStoreIdError):
        retrieve_vector_store(client, "   ")

    client.vector_stores.retrieve.assert_not_called()


def test_returned_id_mismatch_is_rejected() -> None:
    client = make_client()
    client.vector_stores.retrieve.return_value = SimpleNamespace(id="vs_other")

    with pytest.raises(VectorStoreIdMismatchError):
        retrieve_vector_store(client, "vs_requested")


@pytest.mark.parametrize(
    ("sdk_error", "expected_error"),
    [
        (
            status_error(openai.NotFoundError, 404),
            VectorStoreNotAccessibleError,
        ),
        (
            status_error(openai.AuthenticationError, 401),
            VectorStoreAuthenticationError,
        ),
        (
            status_error(openai.PermissionDeniedError, 403),
            VectorStorePermissionError,
        ),
        (
            openai.APIConnectionError(request=request()),
            VectorStoreConnectionError,
        ),
        (
            openai.APITimeoutError(request=request()),
            VectorStoreTimeoutError,
        ),
        (
            status_error(openai.RateLimitError, 429),
            VectorStoreRateLimitError,
        ),
        (
            status_error(openai.InternalServerError, 500),
            VectorStoreAPIError,
        ),
    ],
)
def test_retrieval_maps_openai_errors(sdk_error, expected_error) -> None:
    client = make_client()
    client.vector_stores.retrieve.side_effect = sdk_error

    with pytest.raises(expected_error):
        retrieve_vector_store(client, "vs_test")


def test_valid_creation_normalizes_name_and_creates_once() -> None:
    client = make_client()
    remote = SimpleNamespace(id="vs_created", name="VDR Assistant - Project Falcon")
    client.vector_stores.create.return_value = remote

    assert create_vector_store(client, "  Project   Falcon \n") is remote
    client.vector_stores.create.assert_called_once_with(
        name="VDR Assistant - Project Falcon"
    )
    assert "metadata" not in client.vector_stores.create.call_args.kwargs


@pytest.mark.parametrize("case_name", ["", " \n\t", None])
def test_empty_case_name_is_rejected(case_name) -> None:
    client = make_client()

    with pytest.raises(InvalidCaseNameError):
        create_vector_store(client, case_name)

    client.vector_stores.create.assert_not_called()


def test_creation_failure_returns_no_usable_id() -> None:
    client = make_client()
    client.vector_stores.create.side_effect = openai.APIConnectionError(
        request=request()
    )

    with pytest.raises(VectorStoreCreationError):
        create_vector_store(client, "Project Falcon")


def test_creation_rejects_response_without_id() -> None:
    client = make_client()
    client.vector_stores.create.return_value = SimpleNamespace(id=None)

    with pytest.raises(VectorStoreCreationError):
        create_vector_store(client, "Project Falcon")


def test_blank_vector_store_id_rejected_before_file_list() -> None:
    client = make_client()

    with pytest.raises(InvalidVectorStoreIdError):
        list_vector_store_files(client, "  ")

    client.vector_stores.files.list.assert_not_called()


def test_list_vector_store_files_uses_id_and_returns_all_pages() -> None:
    client = make_client()
    first = SimpleNamespace(id="file_first")
    second = SimpleNamespace(id="file_second")

    class PaginatedAttachments:
        def __iter__(self):
            yield first
            yield second

    client.vector_stores.files.list.return_value = PaginatedAttachments()

    result = list_vector_store_files(client, " vs_manifest ")

    assert result == [first, second]
    client.vector_stores.files.list.assert_called_once_with("vs_manifest")


def test_blank_openai_file_id_rejected_before_retrieval() -> None:
    client = make_client()

    with pytest.raises(InvalidOpenAIFileIdError):
        retrieve_openai_file(client, "")

    client.files.retrieve.assert_not_called()


def test_retrieve_openai_file_uses_expected_id() -> None:
    client = make_client()
    remote_file = SimpleNamespace(
        id="file_expected",
        filename="document.pdf",
        bytes=123,
    )
    client.files.retrieve.return_value = remote_file

    assert retrieve_openai_file(client, " file_expected ") is remote_file
    client.files.retrieve.assert_called_once_with("file_expected")


def test_retrieve_openai_file_rejects_returned_id_mismatch() -> None:
    client = make_client()
    client.files.retrieve.return_value = SimpleNamespace(id="file_other")

    with pytest.raises(OpenAIFileIdMismatchError):
        retrieve_openai_file(client, "file_expected")
