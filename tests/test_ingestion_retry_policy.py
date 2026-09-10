"""Real SDK requests remain offline and have operation-specific retry counts."""

from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, InternalServerError, OpenAI

from src.ingestion.uploader import attach_file_and_poll, upload_openai_file
from src.ingestion.vector_store_manager import (
    list_vector_store_files,
    retrieve_openai_file,
    retrieve_vector_store,
)


@pytest.mark.parametrize("max_wait_seconds", [2, 10])
@pytest.mark.parametrize("failure", ["timeout", "server_error"])
def test_attachment_post_timeout_is_independent_and_never_retried(
    max_wait_seconds, failure, monkeypatch
):
    monkeypatch.setattr("openai._base_client.time.sleep", lambda _: None)
    requests = []

    def transport(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("offline attachment timeout", request=request)
        return httpx.Response(500, json={"error": {"message": "offline server error"}})

    base_timeout = httpx.Timeout(99.0, connect=7.0)
    with OpenAI(
        api_key="offline-test",
        base_url="https://offline.invalid/v1",
        max_retries=5,
        timeout=base_timeout,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as client:
        error_type = APITimeoutError if failure == "timeout" else InternalServerError
        with pytest.raises(error_type):
            attach_file_and_poll(
                client, "vs_owned", "file_known", max_wait_seconds=max_wait_seconds
            )
        assert client.max_retries == 5 and client.timeout == base_timeout

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.headers["x-stainless-retry-count"] == "0"
    assert request.extensions["timeout"] == {
        "connect": 5.0,
        "read": 30.0,
        "write": 30.0,
        "pool": 30.0,
    }


def test_polling_window_starts_after_attachment_and_retains_get_timeouts(monkeypatch):
    from src.ingestion import uploader

    clock = [0.0]
    requests = []

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(
        uploader, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)
    )

    def transport(request):
        requests.append((request, clock[0]))
        if request.method == "POST":
            clock[0] += 20.0  # Attachment time must not consume the polling window.
        return httpx.Response(
            200,
            json={
                "id": "file_known",
                "vector_store_id": "vs_owned",
                "status": "in_progress",
            },
        )

    with OpenAI(
        api_key="offline-test",
        base_url="https://offline.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as client:
        result = attach_file_and_poll(
            client, "vs_owned", "file_known", max_wait_seconds=10
        )
        assert client.max_retries == 0

    assert result.status == "in_progress"
    assert [(r.method, timestamp) for r, timestamp in requests] == [
        ("POST", 0),
        ("GET", 20),
        ("GET", 22),
        ("GET", 26),
    ]
    assert clock[0] == 30  # Ten seconds of scheduled polling after the POST returns.
    assert requests[0][0].extensions["timeout"] == {
        "connect": 5.0,
        "read": 30.0,
        "write": 30.0,
        "pool": 30.0,
    }
    for (request, _), expected_timeout in zip(
        requests[1:], [5.0, 5.0, 4.0], strict=True
    ):
        assert request.extensions["timeout"] == {
            phase: expected_timeout for phase in ("connect", "read", "write", "pool")
        }


@pytest.mark.parametrize("exhausted", [False, True])
def test_workflow_sdk_retries_attach_only_the_returned_persisted_id(
    tmp_path, monkeypatch, exhausted
):
    from src.ingestion.upload_workflow import run_manifest_upload
    from src.ingestion.manifest_persistence import load_manifest
    from test_upload_workflow import make_case
    import json

    root = make_case(tmp_path, ("a.pdf", "b.pdf", "c.pdf"))
    monkeypatch.setattr("openai._base_client.time.sleep", lambda _: None)
    calls, uploaded_names, attachments = [], [], []
    b_attempts = 0

    def transport(request):
        nonlocal b_attempts
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/files":
            body = request.read()
            name = next(n for n in "abc" if (f'filename="{n}.pdf"').encode() in body)
            uploaded_names.append(name)
            if name == "b":
                b_attempts += 1
                # The server may have stored these Files, but their IDs are never
                # returned to the application. They must not become attachments.
                if exhausted or b_attempts < 3:
                    raise httpx.ReadTimeout(
                        "response lost after possible server acceptance",
                        request=request,
                    )
            return httpx.Response(200, json={"id": f"file_{name}_returned"})
        assert (
            request.method == "POST"
            and request.url.path == "/v1/vector_stores/vs_manifest_owned/files"
        )
        file_id = json.loads(request.read())["file_id"]
        saved = next(
            f for f in load_manifest(root).files if f.openai_file_id == file_id
        )
        assert (
            saved.upload_status == "uploaded" and saved.indexing_status == "in_progress"
        )
        attachments.append(file_id)
        return httpx.Response(
            200,
            json={
                "id": file_id,
                "vector_store_id": "vs_manifest_owned",
                "status": "completed",
            },
        )

    with OpenAI(
        api_key="offline",
        base_url="https://offline.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as client:
        result = run_manifest_upload(root, client_factory=lambda: client)
        assert client.max_retries == 0
    assert uploaded_names == ["a", "b", "b", "b", "c"]
    assert result.pass_outcome == "finished"
    assert attachments == (
        ["file_a_returned", "file_c_returned"]
        if exhausted
        else ["file_a_returned", "file_b_returned", "file_c_returned"]
    )
    assert all(f.upload_attempts == 1 for f in load_manifest(root).files)
    assert result.no_id_retryable_count == int(exhausted)
    assert result.completed_count == (2 if exhausted else 3)


@pytest.mark.parametrize("operation", ["store", "list", "file", "poll"])
@pytest.mark.parametrize("exhausted", [False, True])
def test_ingestion_reads_retry_without_repeating_attachment(
    operation, exhausted, monkeypatch
):
    monkeypatch.setattr("time.sleep", lambda _: None)
    requests = []

    def transport(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "id": "file_known",
                    "vector_store_id": "vs_owned",
                    "status": "in_progress",
                },
            )
        count = sum(r.method == "GET" for r in requests)
        if exhausted or count < 3:
            return httpx.Response(
                500, json={"error": {"message": "offline", "type": "server_error"}}
            )
        payload = {
            "id": "vs_owned" if operation == "store" else "file_known",
            "vector_store_id": "vs_owned",
            "status": "completed",
        }
        if operation == "list":
            payload = {"object": "list", "data": [payload], "has_more": False}
        return httpx.Response(200, json=payload)

    with OpenAI(
        api_key="offline-test",
        base_url="https://offline.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as client:

        def call():
            if operation == "store":
                return retrieve_vector_store(client, "vs_owned")
            if operation == "list":
                return list_vector_store_files(client, "vs_owned")
            if operation == "file":
                return retrieve_openai_file(client, "file_known")
            return attach_file_and_poll(client, "vs_owned", "file_known")

        if exhausted:
            with pytest.raises(Exception):
                call()
        else:
            call()
        assert client.max_retries == 0
    assert sum(r.method == "GET" for r in requests) == 3
    assert sum(r.method == "POST" for r in requests) == (
        1 if operation == "poll" else 0
    )


def test_file_upload_rewinds_body_and_returns_only_successful_retry(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("time.sleep", lambda _: None)
    path = tmp_path / "document.pdf"
    path.write_bytes(b"exact offline document bytes")
    requests = []

    def transport(request):
        requests.append(request)
        assert b"exact offline document bytes" in request.read()
        if len(requests) < 3:
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(200, json={"id": "file_returned"})

    with OpenAI(
        api_key="offline-test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as client:
        assert upload_openai_file(client, path).id == "file_returned"
        assert client.max_retries == 0
    assert len(requests) == 3
    assert [r.headers["x-stainless-retry-count"] for r in requests] == ["0", "1", "2"]
    assert all(r.url.path == "/v1/files" for r in requests)
