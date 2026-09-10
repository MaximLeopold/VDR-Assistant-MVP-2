"""Offline restart, continuation, exact-ID recovery and publication boundaries."""

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import (
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    NotFoundError,
    InternalServerError,
)

from src.ingestion.upload_workflow import run_manifest_upload, prepare_manifest_upload
from src.ingestion.upload_targets import UploadTargetKey, enumerate_upload_targets
from src.ingestion.manifest_persistence import (
    load_manifest,
    save_manifest,
    ManifestPersistenceError,
)
from src.ingestion.case_readiness import assess_case_readiness
from src.ingestion.uploader import attach_file_and_poll
from test_upload_workflow import make_case, success_upload, success_attach


def api_error(kind=NotFoundError, status=404):
    response = httpx.Response(
        status, request=httpx.Request("GET", "https://offline.invalid/resource")
    )
    return kind("sanitized fixture", response=response, body={})


def attachment(file_id, store="vs_manifest_owned", status="completed"):
    return SimpleNamespace(id=file_id, vector_store_id=store, status=status)


def known(root, name="a.pdf", *, status="in_progress", file_id="file_known"):
    manifest = load_manifest(root)
    record = next(r for r in manifest.files if r.relative_path == name)
    record.openai_file_id = file_id
    record.upload_status = "uploaded"
    record.indexing_status = status
    record.upload_attempts = 1
    save_manifest(manifest, root)


def fake_client(statuses=None):
    statuses = statuses or {}
    client = Mock()
    client.files.create.side_effect = AssertionError(
        "Known-file recovery must never create a File"
    )

    def read(file_id, *, vector_store_id):
        if file_id not in statuses:
            raise api_error()
        return attachment(file_id, vector_store_id, statuses[file_id])

    client.vector_stores.files.retrieve.side_effect = read
    client.vector_stores.retrieve.side_effect = lambda store: SimpleNamespace(id=store)
    client.files.retrieve.side_effect = lambda file_id: SimpleNamespace(id=file_id)
    client.vector_stores.files.create.side_effect = (
        lambda file_id, vector_store_id: attachment(file_id, vector_store_id)
    )
    return client


@pytest.mark.parametrize(
    "status,expected",
    [
        ("completed", "completed"),
        ("in_progress", "in_progress"),
        ("failed", "failed"),
        ("cancelled", "failed"),
    ],
)
def test_restart_reconciles_present_attachment_without_upload_or_reattach(
    tmp_path, status, expected
):
    root = make_case(tmp_path, ("a.pdf", "b.pdf"))
    known(root)
    (root / "a.pdf").unlink()  # Recovery does not depend on the local source surviving.
    client = fake_client({"file_known": status})
    upload, attach = Mock(), Mock()
    result = run_manifest_upload(
        root,
        client_factory=lambda: client,
        recover_only=True,
        upload_file=upload,
        attach_file=attach,
    )
    assert result.pass_outcome == "finished"
    record = load_manifest(root).files[0]
    assert record.openai_file_id == "file_known" and record.indexing_status == expected
    assert record.upload_attempts == 1
    assert load_manifest(root).files[1].upload_attempts == 0
    upload.assert_not_called()
    attach.assert_not_called()
    client.vector_stores.files.retrieve.assert_called_once_with(
        "file_known", vector_store_id="vs_manifest_owned"
    )


def test_normal_pass_reconciles_all_known_ids_before_any_new_create(tmp_path):
    root = make_case(tmp_path, ("a.pdf", "b.pdf", "c.pdf"))
    known(root, "b.pdf", file_id="file_b")
    known(root, "c.pdf", file_id="file_c")
    client = fake_client({"file_b": "completed", "file_c": "in_progress"})

    def upload(*args):
        assert client.vector_stores.files.retrieve.call_count == 2
        assert load_manifest(root).files[1].indexing_status == "completed"
        return success_upload(*args)

    result = run_manifest_upload(
        root,
        client_factory=lambda: client,
        upload_file=upload,
        attach_file=success_attach,
    )
    assert [r.key.source_relative_path for r in result.files] == [
        "b.pdf",
        "c.pdf",
        "a.pdf",
    ]
    assert result.total_completed_count == 2 and result.known_pending_count == 1
    assert client.vector_stores.files.retrieve.call_count == 2  # No post-pass sweep.


def test_known_not_started_absent_attaches_once_after_resource_and_checkpoint_checks(
    tmp_path,
):
    root = make_case(tmp_path, ("a.pdf",))
    known(root, status="not_started")
    client = fake_client()

    def attach(_client, store, file_id):
        assert client.vector_stores.files.retrieve.call_count == 2
        client.vector_stores.retrieve.assert_called_once_with(store)
        client.files.retrieve.assert_called_once_with(file_id)
        saved = load_manifest(root).files[0]
        assert (
            saved.openai_file_id == file_id and saved.indexing_status == "in_progress"
        )
        return attachment(file_id, store)

    upload = Mock()
    result = run_manifest_upload(
        root,
        client_factory=lambda: client,
        recover_only=True,
        upload_file=upload,
        attach_file=attach,
    )
    assert result.succeeded
    upload.assert_not_called()
    assert load_manifest(root).files[0].upload_attempts == 1


@pytest.mark.parametrize("prior_status", ["in_progress", "failed"])
def test_ambiguous_absence_requires_explicit_action_and_rechecks_all_evidence(
    tmp_path, prior_status
):
    root = make_case(tmp_path, ("a.pdf",))
    known(root, status=prior_status)
    client = fake_client()
    upload = Mock()
    first = run_manifest_upload(root, client_factory=lambda: client, upload_file=upload)
    assert first.files[0].can_attach_existing
    client.vector_stores.files.create.assert_not_called()
    assert client.vector_stores.files.retrieve.call_count == 2
    second = run_manifest_upload(
        root,
        client_factory=lambda: client,
        recover_only=True,
        reattach_keys=(UploadTargetKey("a.pdf"),),
        upload_file=upload,
    )
    assert second.succeeded
    assert client.vector_stores.files.retrieve.call_count == 4
    assert client.files.retrieve.call_count == 2
    assert client.vector_stores.retrieve.call_count == 2
    client.vector_stores.files.create.assert_called_once_with(
        file_id="file_known", vector_store_id="vs_manifest_owned"
    )
    upload.assert_not_called()


def test_attachment_appears_during_absence_checks_so_no_post_is_sent(tmp_path):
    root = make_case(tmp_path, ("a.pdf",))
    known(root)
    client = fake_client()
    client.vector_stores.files.retrieve.side_effect = [
        api_error(),
        attachment("file_known"),
    ]
    result = run_manifest_upload(
        root,
        client_factory=lambda: client,
        recover_only=True,
        reattach_keys=(UploadTargetKey("a.pdf"),),
    )
    assert result.succeeded
    client.vector_stores.files.create.assert_not_called()


@pytest.mark.parametrize("resource", ["store", "file"])
def test_missing_underlying_resource_never_creates_or_attaches(tmp_path, resource):
    root = make_case(tmp_path, ("a.pdf", "b.pdf"))
    known(root, status="not_started")
    client = fake_client()
    method = (
        client.vector_stores.retrieve if resource == "store" else client.files.retrieve
    )
    method.side_effect = api_error()
    upload = Mock(side_effect=success_upload)
    result = run_manifest_upload(
        root,
        client_factory=lambda: client,
        upload_file=upload,
        attach_file=success_attach,
    )
    assert load_manifest(root).files[0].openai_file_id == "file_known"
    client.vector_stores.files.create.assert_not_called()
    if resource == "store":
        assert result.pass_outcome == "paused"
        upload.assert_not_called()
    else:
        assert result.pass_outcome == "finished" and result.known_failed_count == 1
        assert upload.call_count == 1 and upload.call_args.args[1].name == "b.pdf"


@pytest.mark.parametrize("identity", ["file", "store"])
def test_wrong_remote_identity_stops_before_other_uploads(tmp_path, identity):
    root = make_case(tmp_path, ("a.pdf", "b.pdf"))
    known(root)
    client = fake_client()
    client.vector_stores.files.retrieve.side_effect = None
    client.vector_stores.files.retrieve.return_value = attachment(
        "file_wrong" if identity == "file" else "file_known",
        "vs_wrong" if identity == "store" else "vs_manifest_owned",
    )
    upload = Mock()
    result = run_manifest_upload(
        root, client_factory=lambda: client, upload_file=upload
    )
    assert result.critically_stopped
    upload.assert_not_called()
    assert load_manifest(root).files[0].openai_file_id == "file_known"


@pytest.mark.parametrize(
    "failure",
    ["upload", "missing_id", "attachment", "index_failed", "pending", "local"],
)
def test_middle_target_failure_does_not_starve_third_target(tmp_path, failure):
    root = make_case(tmp_path, ("a.pdf", "b.pdf", "c.pdf"))
    if failure == "local":
        (root / "b.pdf").unlink()

    def upload(client, path):
        if path.name == "b.pdf":
            if failure == "upload":
                raise TimeoutError()
            if failure == "missing_id":
                return SimpleNamespace(id=None)
        return success_upload(client, path)

    def attach(client, store, file_id):
        if file_id == "file_b":
            if failure == "attachment":
                raise TimeoutError()
            if failure in {"pending", "index_failed"}:
                return attachment(
                    file_id, store, "in_progress" if failure == "pending" else "failed"
                )
        return attachment(file_id, store)

    result = run_manifest_upload(
        root, client_factory=object, upload_file=upload, attach_file=attach
    )
    assert result.pass_outcome == "finished" and result.completed_count == 2
    assert load_manifest(root).files[2].indexing_status == "completed"
    assert not assess_case_readiness(root).is_ready


@pytest.mark.parametrize("boundary", [1, 2, 3, 4])
def test_failed_or_silently_lost_checkpoint_stops_whole_pass(tmp_path, boundary):
    root = make_case(tmp_path, ("a.pdf", "b.pdf"))
    count = 0

    def saver(manifest, folder):
        nonlocal count
        count += 1
        if count == boundary:
            return None  # A no-op saver must fail readback, even without an exception.
        return save_manifest(manifest, folder)

    upload, attach = Mock(side_effect=success_upload), Mock(side_effect=success_attach)
    result = run_manifest_upload(
        root,
        client_factory=object,
        upload_file=upload,
        attach_file=attach,
        manifest_saver=saver,
    )
    assert result.critically_stopped
    assert upload.call_count == (0 if boundary == 1 else 1)
    assert attach.call_count == (1 if boundary == 4 else 0)
    assert load_manifest(root).files[1].upload_attempts == 0


def test_middle_target_id_checkpoint_failure_stops_before_third_target(tmp_path):
    root = make_case(tmp_path, ("a.pdf", "b.pdf", "c.pdf"))

    def saver(manifest, folder):
        if manifest.files[1].openai_file_id:
            raise ManifestPersistenceError("Second target ID checkpoint failed")
        return save_manifest(manifest, folder)

    upload, attach = Mock(side_effect=success_upload), Mock(side_effect=success_attach)
    result = run_manifest_upload(
        root,
        client_factory=object,
        upload_file=upload,
        attach_file=attach,
        manifest_saver=saver,
    )
    assert result.critically_stopped and result.completed_count == 1
    assert result.recovery_file_id == "file_b"
    assert upload.call_count == 2 and attach.call_count == 1
    assert load_manifest(root).files[2].upload_attempts == 0


@pytest.mark.parametrize(
    "kind,status",
    [(AuthenticationError, 401), (PermissionDeniedError, 403), (RateLimitError, 429)],
)
def test_service_access_errors_pause_immediately_after_persisting_failure(
    tmp_path, kind, status
):
    root = make_case(tmp_path, ("a.pdf", "b.pdf", "c.pdf"))
    upload = Mock(side_effect=api_error(kind, status))
    result = run_manifest_upload(root, client_factory=object, upload_file=upload)
    assert result.pass_outcome == "paused"
    upload.assert_called_once()
    assert load_manifest(root).files[0].last_error
    assert load_manifest(root).files[1].upload_attempts == 0


def test_client_access_failure_pauses_without_recording_an_upload_attempt(tmp_path):
    root = make_case(tmp_path, ("a.pdf", "b.pdf"))
    upload = Mock()
    result = run_manifest_upload(
        root,
        client_factory=Mock(side_effect=api_error(AuthenticationError, 401)),
        upload_file=upload,
    )
    assert result.pass_outcome == "paused"
    assert load_manifest(root).files[0].last_error
    assert all(f.upload_attempts == 0 for f in load_manifest(root).files)
    upload.assert_not_called()


def test_explicit_reattach_stops_if_candidate_changes_during_remote_checks(tmp_path):
    from datetime import timedelta
    from src.ingestion.manifest_persistence import derive_manifest_paths

    root = make_case(tmp_path, ("a.pdf",))
    known(root)
    client = fake_client()
    reads = 0

    def absent(file_id, *, vector_store_id):
        nonlocal reads
        reads += 1
        if reads == 2:
            changed = load_manifest(root)
            changed.created_at += timedelta(seconds=1)
            derive_manifest_paths(root).manifest_path.write_text(
                changed.model_dump_json()
            )
        raise api_error()

    client.vector_stores.files.retrieve.side_effect = absent
    result = run_manifest_upload(
        root,
        client_factory=lambda: client,
        recover_only=True,
        reattach_keys=(UploadTargetKey("a.pdf"),),
    )
    assert result.critically_stopped and reads == 2
    client.vector_stores.files.create.assert_not_called()
    client.files.create.assert_not_called()


def test_healthy_pending_result_explains_recovery_without_calling_it_a_failure(
    tmp_path,
):
    from src.ui.new_case_setup import _file_id_recovery_message

    root = make_case(tmp_path, ("a.pdf",))
    result = run_manifest_upload(
        root,
        client_factory=object,
        upload_file=success_upload,
        attach_file=lambda _client, store, file_id: attachment(
            file_id, store, "in_progress"
        ),
    )
    assert result.pass_outcome == "finished"
    assert load_manifest(root).files[0].last_error is None
    message = _file_id_recovery_message(result)
    assert (
        "Indexing is pending" in message and "Refresh / recover known files" in message
    )


@pytest.mark.parametrize("breaker", ["local", "completed", "pending"])
def test_three_infrastructure_failure_threshold_and_reset(tmp_path, breaker):
    root = make_case(tmp_path, tuple(f"{x}.pdf" for x in "abcdefg"))
    if breaker == "local":
        (root / "c.pdf").unlink()

    def upload(client, path):
        if path.stem == "c" and breaker != "local":
            return success_upload(client, path)
        raise api_error(InternalServerError, 500)

    def attach(client, store, file_id):
        return attachment(
            file_id, store, "in_progress" if breaker == "pending" else "completed"
        )

    result = run_manifest_upload(
        root, client_factory=object, upload_file=upload, attach_file=attach
    )
    assert result.pass_outcome == "paused" and "3 consecutive" in result.message
    states = load_manifest(root).files
    if breaker == "local":
        assert states[3].upload_attempts == 1 and states[4].upload_attempts == 0
    else:
        assert states[5].upload_attempts == 1 and states[6].upload_attempts == 0


def test_short_poll_window_returns_pending_and_uses_immediate_then_backoff_reads(
    monkeypatch,
):
    from src.ingestion import uploader

    clock = [0.0]
    reads, sleeps = [], []
    monkeypatch.setattr(uploader.time, "monotonic", lambda: clock[0])

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(uploader.time, "sleep", sleep)
    client = fake_client()
    client.vector_stores.files.create.side_effect = lambda **kw: attachment(
        kw["file_id"], kw["vector_store_id"], "in_progress"
    )

    def read(file_id, *, vector_store_id):
        reads.append(clock[0])
        return attachment(file_id, vector_store_id, "in_progress")

    client.vector_stores.files.retrieve.side_effect = read
    result = attach_file_and_poll(client, "vs_manifest_owned", "file_known")
    assert result.status == "in_progress"
    assert reads == [0, 2, 6] and sleeps == [2, 4, 4]
    assert clock[0] == 10
    assert client.vector_stores.files.create.call_count == 1


def test_85_of_86_stays_unpublished_until_exact_known_target_recovers(tmp_path):
    root = make_case(tmp_path, tuple(f"{i:03}.pdf" for i in range(86)))
    manifest = load_manifest(root)
    for i, record in enumerate(manifest.files):
        record.openai_file_id = f"file_{i:03}"
        record.upload_status = "uploaded"
        record.indexing_status = "in_progress" if i == 40 else "completed"
        record.upload_attempts = 1
    save_manifest(manifest, root)
    readiness = assess_case_readiness(root)
    assert readiness.completed_count == 85 and not readiness.is_ready
    before = load_manifest(root)
    client = fake_client({"file_040": "completed"})
    upload = Mock()
    result = run_manifest_upload(
        root, client_factory=lambda: client, recover_only=True, upload_file=upload
    )
    assert result.succeeded and result.total_completed_count == 86
    assert assess_case_readiness(root).is_ready
    upload.assert_not_called()
    after = load_manifest(root)
    assert all(
        a == b
        for i, (a, b) in enumerate(zip(before.files, after.files, strict=True))
        if i != 40
    )
    assert (
        after.snapshot_state == "preparing"
    )  # Publication remains a separate strict gate.
