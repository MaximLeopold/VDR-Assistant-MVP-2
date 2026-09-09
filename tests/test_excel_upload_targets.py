"""Identical upload checkpoint contract for direct and worksheet targets."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import httpx
import pytest
from openai import OpenAI, APIConnectionError, InternalServerError
from openpyxl import Workbook
from src.ingestion.manifest_builder import build_manifest
from src.ingestion.manifest_persistence import (
    create_manifest,
    save_manifest,
    load_manifest,
    ManifestPersistenceError,
)
from src.ingestion.excel_preprocessing import preprocess_workbook
from src.ingestion.upload_targets import enumerate_upload_targets, UploadTargetKey
from src.ingestion.upload_workflow import (
    run_manifest_upload,
    prepare_manifest_upload,
    DefinitePreRemoteUploadError,
    SafeRetryAuthorization,
    retry_candidate_context,
)
from src.ingestion.uploader import upload_openai_file, attach_file_and_poll
from src.ingestion.vector_store_manager import create_vector_store


@pytest.fixture(params=["direct", "worksheet"])
def candidate(tmp_path, request):
    root = tmp_path / "VDR"
    root.mkdir()
    if request.param == "worksheet":
        book = Workbook()
        book.active.title = "Revenue"
        book.active["A1"] = "Revenue 2025 100"
        book.save(root / "model.xlsx")
        book.close()
    else:
        (root / "memo.pdf").write_bytes(b"pdf fixture")
    create_manifest(build_manifest(str(root)), root)
    if request.param == "worksheet":
        preprocess_workbook(root, "model.xlsx")
    manifest = load_manifest(root)
    manifest.vector_store_id = "vs_test"
    save_manifest(manifest, root)
    return root


def owner(root):
    return enumerate_upload_targets(load_manifest(root), root)[0].state_owner


def good_attach(*args):
    return SimpleNamespace(status="completed")


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "pre_remote",
        "uncertain",
        "missing_id",
        "unusable_id",
        "attach",
        "index_failed",
    ],
)
def test_remote_boundaries(candidate, failure):
    upload = Mock()
    if failure == "pre_remote":
        upload.side_effect = DefinitePreRemoteUploadError("local open")
    elif failure == "uncertain":
        upload.side_effect = TimeoutError("uncertain")
    else:
        upload.return_value = SimpleNamespace(
            id=(
                None
                if failure == "missing_id"
                else " " if failure == "unusable_id" else "file_exact"
            )
        )
    attach = Mock(
        side_effect=TimeoutError("poll") if failure == "attach" else None,
        return_value=SimpleNamespace(
            status="failed" if failure == "index_failed" else "completed"
        ),
    )
    result = run_manifest_upload(
        candidate, client_factory=object, upload_file=upload, attach_file=attach
    )
    assert upload.call_count == 1
    state = owner(candidate)
    if failure == "none":
        assert result.succeeded and state.indexing_status == "completed"
    elif failure == "pre_remote":
        assert result.safe_retry_keys == (
            enumerate_upload_targets(load_manifest(candidate), candidate)[0].key,
        )
        retry = run_manifest_upload(
            candidate,
            client_factory=object,
            upload_file=Mock(return_value=SimpleNamespace(id="file_retry")),
            attach_file=good_attach,
            safe_retry_authorization=result.safe_retry_authorization,
        )
        assert retry.succeeded
    elif failure in {"uncertain", "missing_id", "unusable_id"}:
        assert state.upload_status == "uploading" and state.openai_file_id is None
        assert result.recovery_count == 1
    else:
        assert state.openai_file_id == "file_exact"
        assert state.indexing_status == (
            "failed" if failure == "index_failed" else "in_progress"
        )
        assert result.recovery_details["openai_file_id"] == "file_exact"
    # Every outcome other than proven local failure must be refused on restart.
    if failure != "pre_remote":
        again = Mock()
        run_manifest_upload(
            candidate,
            client_factory=object,
            upload_file=again,
            attach_file=good_attach,
            safe_retry_authorization=SafeRetryAuthorization(
                retry_candidate_context(load_manifest(candidate), candidate),
                (enumerate_upload_targets(load_manifest(candidate), candidate)[0].key,),
            ),
        )
        again.assert_not_called()


@pytest.mark.parametrize("checkpoint", [1, 2, 3, 4])
def test_checkpoint_failures(candidate, checkpoint):
    calls = 0

    def saver(manifest, root):
        nonlocal calls
        calls += 1
        if calls == checkpoint:
            raise ManifestPersistenceError("injected checkpoint failure")
        return save_manifest(manifest, root)

    upload = Mock(return_value=SimpleNamespace(id="file_returned"))
    attach = Mock(return_value=SimpleNamespace(status="completed"))
    result = run_manifest_upload(
        candidate,
        client_factory=object,
        upload_file=upload,
        attach_file=attach,
        manifest_saver=saver,
    )
    assert result.critically_stopped
    assert upload.call_count == (0 if checkpoint == 1 else 1)
    assert attach.call_count == (1 if checkpoint == 4 else 0)
    if checkpoint == 2:
        assert result.recovery_file_id == "file_returned"
        assert (
            result.recovery_details["artifact_id"]
            == enumerate_upload_targets(load_manifest(candidate), candidate)[
                0
            ].key.artifact_id
        )
    run_manifest_upload(
        candidate, client_factory=object, upload_file=upload, attach_file=attach
    )
    assert upload.call_count == 1


@pytest.mark.parametrize(
    "stage",
    [
        "batch_started",
        "file_started",
        "manifest_marked_uploading",
        "file_uploaded",
        "file_id_persisted",
        "attachment_started",
        "indexing_completed",
        "batch_completed",
    ],
)
def test_callback_isolation(candidate, stage):
    events = []
    observed_ids = []

    def callback(event):
        events.append(event.kind)
        if event.kind == "file_uploaded":
            observed_ids.append(owner(candidate).openai_file_id)
        if event.kind == stage:
            raise RuntimeError("cosmetic callback")

    upload = Mock(return_value=SimpleNamespace(id="file_stable"))
    result = run_manifest_upload(
        candidate,
        client_factory=object,
        upload_file=upload,
        attach_file=good_attach,
        progress_callback=callback,
    )
    assert (
        result.succeeded
        and stage in events
        and owner(candidate).openai_file_id == "file_stable"
    )
    assert upload.call_count == 1
    assert observed_ids == ["file_stable"]


@pytest.mark.parametrize("kind", ["file", "attachment", "store"])
@pytest.mark.parametrize("failure", ["timeout", "server_error"])
def test_sdk_mutation_transport_has_no_opaque_retry(tmp_path, kind, failure):
    requests = []

    def transport(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        return httpx.Response(
            500,
            json={"error": {"message": "synthetic", "type": "server_error"}},
            request=request,
        )

    path = tmp_path / "proxy.md"
    path.write_text("fixture")
    with OpenAI(
        api_key="offline-test-key",
        base_url="https://offline.invalid/v1",
        max_retries=3,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as client:
        with pytest.raises(Exception):
            if kind == "file":
                upload_openai_file(client, path)
            elif kind == "attachment":
                attach_file_and_poll(client, "vs_test", "file_test")
            else:
                create_vector_store(client, "Offline test")
        assert client.max_retries == 3
    assert len(requests) == 1 and requests[0].method == "POST"


def test_local_open_failure_is_proven_before_sdk_call(tmp_path):
    client = Mock()
    with pytest.raises(DefinitePreRemoteUploadError):
        upload_openai_file(client, tmp_path / "missing.md")
    client.files.create.assert_not_called()


@pytest.mark.parametrize("headcount_outcome", ["safe", "uncertain", "known_id"])
def test_three_worksheet_sibling_isolation(tmp_path, headcount_outcome):
    root = tmp_path / "VDR"
    root.mkdir()
    book = Workbook()
    book.remove(book.active)
    for name in ["Revenue", "Customers", "Headcount"]:
        book.create_sheet(name)["A1"] = name
    book.save(root / "model.xlsx")
    book.close()
    create_manifest(build_manifest(str(root)), root)
    preprocess_workbook(root, "model.xlsx")
    m = load_manifest(root)
    m.vector_store_id = "vs_siblings"
    save_manifest(m, root)

    def upload(_client, path):
        if path.name == "sheet_003.md":
            if headcount_outcome == "safe":
                raise DefinitePreRemoteUploadError("not sent")
            if headcount_outcome == "uncertain":
                raise TimeoutError("uncertain upload")
            return SimpleNamespace(id="file_headcount")
        return SimpleNamespace(id="file_" + path.stem)

    def attach(_client, _store, file_id):
        if file_id == "file_headcount":
            raise TimeoutError("known ID incomplete")
        return good_attach()

    result = run_manifest_upload(
        root, client_factory=object, upload_file=upload, attach_file=attach
    )
    before = [
        a.model_dump() for a in load_manifest(root).files[0].derived_artifacts[:2]
    ]
    if headcount_outcome != "safe":
        retried = Mock()
        child = enumerate_upload_targets(load_manifest(root), root)[2]
        run_manifest_upload(
            root,
            client_factory=object,
            upload_file=retried,
            attach_file=good_attach,
            safe_retry_authorization=SafeRetryAuthorization(
                retry_candidate_context(load_manifest(root), root), (child.key,)
            ),
        )
        retried.assert_not_called()
        assert [
            a.model_dump() for a in load_manifest(root).files[0].derived_artifacts[:2]
        ] == before
        return
    assert len(result.safe_retry_keys) == 1 and result.safe_retry_keys[0].artifact_id
    # A parent path is not authorization for a failed child.
    assert not prepare_manifest_upload(
        root, safe_retry_authorization=SafeRetryAuthorization(
            result.safe_retry_authorization.context, (UploadTargetKey("model.xlsx"),)
        )
    ).candidates
    retried = Mock(return_value=SimpleNamespace(id="file_headcount"))
    run_manifest_upload(
        root,
        client_factory=object,
        upload_file=retried,
        attach_file=good_attach,
        safe_retry_authorization=result.safe_retry_authorization,
    )
    assert retried.call_count == 1 and retried.call_args.args[1].name == "sheet_003.md"
    assert [
        a.model_dump() for a in load_manifest(root).files[0].derived_artifacts[:2]
    ] == before


def test_sdk_initial_poll_deadline_never_reattaches(monkeypatch):
    from src.ingestion import uploader

    ticks = iter([0, 0, 1, 3])
    monkeypatch.setattr(
        uploader,
        "time",
        SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None),
    )
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "file_test",
                "object": "vector_store.file",
                "created_at": 1,
                "vector_store_id": "vs_test",
                "status": "in_progress",
                "usage_bytes": 0,
                "last_error": None,
            },
            request=request,
        )

    with OpenAI(
        api_key="offline",
        base_url="https://offline.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as client:
        with pytest.raises(TimeoutError):
            attach_file_and_poll(client, "vs_test", "file_test", max_wait_seconds=2)
    assert [r.method for r in requests] == ["POST", "GET"]


def test_transient_local_lock_after_file_create_never_reuploads(candidate, monkeypatch):
    from src.ingestion import local_io

    real_replace = local_io.os.replace
    sent = False
    blocked = False

    def replacement(source, destination):
        nonlocal blocked
        if sent and not blocked and Path(destination).name == "manifest.backup.json":
            blocked = True
            raise PermissionError("transient local sharing lock")
        return real_replace(source, destination)

    monkeypatch.setattr(local_io.os, "replace", replacement)

    def upload(*args):
        nonlocal sent
        assert not sent
        sent = True
        return SimpleNamespace(id="file_keep")

    result = run_manifest_upload(
        candidate, client_factory=object, upload_file=upload, attach_file=good_attach
    )
    assert (
        blocked and result.succeeded and owner(candidate).openai_file_id == "file_keep"
    )


@pytest.mark.parametrize('extension',['.xlsx','.xls'])
def test_uploader_never_accepts_raw_workbooks(tmp_path,extension):
    path=tmp_path/('raw'+extension);path.write_bytes(b'fixture')
    client=Mock()
    with pytest.raises(DefinitePreRemoteUploadError,match='Raw workbooks'):
        upload_openai_file(client,path)
    client.files.create.assert_not_called()
    assert path.read_bytes()==b'fixture'
