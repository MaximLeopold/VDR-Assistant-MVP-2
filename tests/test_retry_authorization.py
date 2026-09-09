"""Candidate-bound retry proof; all remote effects use fake adapters."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ingestion import upload_workflow as workflow
from src.ingestion.manifest_persistence import (
    derive_manifest_paths, load_manifest, save_manifest,
)
from src.ingestion.upload_targets import UploadTargetKey
from src.ui import new_case_setup as ui
from test_upload_workflow import make_case, success_attach, success_upload


def safe_failure(root):
    result = workflow.run_manifest_upload(
        root,
        client_factory=object,
        upload_file=Mock(side_effect=workflow.DefinitePreRemoteUploadError("local open")),
        attach_file=Mock(),
    )
    assert result.safe_retry_authorization is not None
    return result


def assert_retry_refused(root, authorization):
    before = load_manifest(root).model_dump()
    plan = workflow.prepare_manifest_upload(root, safe_retry_authorization=authorization)
    assert not plan.candidates
    client_factory, upload, attach = Mock(), Mock(), Mock()
    workflow.run_manifest_upload(
        root, client_factory=client_factory, upload_file=upload, attach_file=attach,
        safe_retry_authorization=authorization,
    )
    client_factory.assert_not_called()
    upload.assert_not_called()
    attach.assert_not_called()
    assert load_manifest(root).model_dump() == before


@pytest.mark.parametrize("same_store", [False, True])
def test_direct_proof_cannot_transfer_between_candidates(tmp_path, same_store):
    root_a = make_case(tmp_path / "A", ("Finance/report.pdf",))
    root_b = make_case(tmp_path / "B", ("Finance/report.pdf",))
    proof_a = safe_failure(root_a).safe_retry_authorization
    safe_failure(root_b)
    if not same_store:
        manifest = load_manifest(root_b)
        manifest.vector_store_id = "vs_other_candidate"
        # Simulate an independently associated candidate, never bypass a real store.
        derive_manifest_paths(root_b).manifest_path.write_text(manifest.model_dump_json())
    assert_retry_refused(root_b, proof_a)


@pytest.mark.parametrize("change", ["replacement", "store", "content"])
def test_changed_manifest_context_invalidates_proof(tmp_path, change):
    root = make_case(tmp_path, ("Finance/report.pdf",))
    authorization = safe_failure(root).safe_retry_authorization
    manifest = load_manifest(root)
    if change == "replacement":
        # Same location, store and inventory, but a newly created manifest.
        manifest.created_at += timedelta(microseconds=1)
    elif change == "store":
        manifest.vector_store_id = "vs_replacement"
    else:
        manifest.case_name = "Replacement inventory snapshot"
    # External replacement is the event under test; shared saves correctly forbid it.
    derive_manifest_paths(root).manifest_path.write_text(manifest.model_dump_json())
    assert_retry_refused(root, authorization)


def test_same_candidate_proof_survives_ordinary_checkpoints(tmp_path):
    root = make_case(tmp_path, ("Finance/report.pdf",))
    result = safe_failure(root)
    before = load_manifest(root)
    assert result.safe_retry_authorization.context.vdr_folder == root.resolve()
    assert result.safe_retry_authorization.context.manifest_path == derive_manifest_paths(root).manifest_path.resolve()
    save_manifest(before, root)
    upload = Mock(side_effect=success_upload)
    retried = workflow.run_manifest_upload(
        root, client_factory=object, upload_file=upload, attach_file=success_attach,
        safe_retry_authorization=result.safe_retry_authorization,
    )
    assert retried.succeeded
    upload.assert_called_once()
    assert load_manifest(root).files[0].upload_attempts == 2


def test_bare_target_keys_are_not_retry_authorization(tmp_path):
    root = make_case(tmp_path, ("Finance/report.pdf",))
    result = safe_failure(root)
    assert result.safe_retry_keys == (UploadTargetKey("Finance/report.pdf"),)
    assert_retry_refused(root, result.safe_retry_keys)


def test_runner_rechecks_candidate_after_plan_before_upload(tmp_path):
    root = make_case(tmp_path, ("Finance/report.pdf",))
    authorization = safe_failure(root).safe_retry_authorization

    def replace_after_plan():
        manifest = load_manifest(root)
        manifest.created_at += timedelta(seconds=1)
        derive_manifest_paths(root).manifest_path.write_text(manifest.model_dump_json())
        return object()

    upload = Mock()
    result = workflow.run_manifest_upload(
        root, client_factory=replace_after_plan, upload_file=upload,
        safe_retry_authorization=authorization,
    )
    assert result.critically_stopped
    upload.assert_not_called()
    assert load_manifest(root).files[0].upload_status == "failed"


@pytest.mark.parametrize("state", ["uncertain", "known_id", "index_failed"])
def test_matching_proof_never_overrides_remote_uncertainty(tmp_path, state):
    root = make_case(tmp_path, ("Finance/report.pdf",))
    authorization = safe_failure(root).safe_retry_authorization
    if state == "uncertain":
        upload = Mock(side_effect=TimeoutError("request may have been sent"))
        attach = Mock()
    else:
        upload = Mock(return_value=SimpleNamespace(id="file_known"))
        attach = (
            Mock(side_effect=TimeoutError("poll interrupted")) if state == "known_id"
            else Mock(return_value=SimpleNamespace(status="failed"))
        )
    workflow.run_manifest_upload(
        root, client_factory=object, upload_file=upload, attach_file=attach,
        safe_retry_authorization=authorization,
    )
    assert_retry_refused(root, authorization)


@pytest.mark.parametrize("action", ["start", "cancel", "folder", "case"])
def test_setup_context_changes_clear_authorization(tmp_path, monkeypatch, action):
    root = make_case(tmp_path, ("Finance/report.pdf",))
    result = safe_failure(root)
    state = {
        ui.SETUP_FOLDER_KEY: str(root.resolve()), ui.SETUP_CASE_ID_KEY: "case-a",
        ui.SETUP_SAFE_RETRY_KEY: result.safe_retry_authorization,
        ui.SETUP_UPLOAD_RESULT_KEY: result,
    }
    monkeypatch.setattr(ui.st, "rerun", Mock())
    if action == "start":
        ui.start_new_case_setup(state)
    elif action == "cancel":
        ui._cancel_setup(state)
    else:
        ui._set_setup_candidate(
            state, root if action == "case" else root.parent / "OtherVDR",
            "case-b" if action == "case" else "case-a",
        )
    assert ui.SETUP_SAFE_RETRY_KEY not in state
    assert ui.SETUP_UPLOAD_RESULT_KEY not in state


def test_same_setup_candidate_keeps_authorization(tmp_path):
    root = make_case(tmp_path, ("Finance/report.pdf",))
    authorization = safe_failure(root).safe_retry_authorization
    state = {
        ui.SETUP_FOLDER_KEY: str(root.resolve()), ui.SETUP_CASE_ID_KEY: "case-a",
        ui.SETUP_SAFE_RETRY_KEY: authorization,
    }
    ui._set_setup_candidate(state, root / ".", "case-a")
    assert state[ui.SETUP_SAFE_RETRY_KEY] is authorization


def test_streamlit_preview_discards_other_candidate_authorization(tmp_path, monkeypatch):
    import json
    from streamlit.testing.v1 import AppTest
    from src.config import settings
    from test_new_case_setup_ui import make_registered_case

    existing = make_registered_case(tmp_path)
    registry = tmp_path / "cases.json"
    registry.write_text(json.dumps({"cases": [{"case_id": "existing", "vdr_folder": str(existing)}]}))
    root_a = make_case(tmp_path / "A", ("Finance/report.pdf",))
    root_b = make_case(tmp_path / "B", ("Finance/report.pdf",))
    authorization = safe_failure(root_a).safe_retry_authorization
    safe_failure(root_b)
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(registry))
    client_factory = Mock()
    monkeypatch.setattr(ui, "get_openai_client", client_factory)
    app = AppTest.from_file("app/main.py")
    for key, value in {
        ui.SETUP_ACTIVE_KEY: True, ui.SETUP_STEP_KEY: "upload_preview",
        ui.SETUP_FOLDER_KEY: str(root_b), ui.SETUP_CASE_ID_KEY: "case-b",
        ui.SETUP_SAFE_RETRY_KEY: authorization,
    }.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    assert ui.SETUP_SAFE_RETRY_KEY not in app.session_state
    assert not any(b.label == "Upload and index all eligible files" for b in app.button)
    client_factory.assert_not_called()


def test_upload_uses_final_verified_path(tmp_path, monkeypatch):
    root = make_case(tmp_path, ("Finance/report.pdf",))
    final_path = root / "final-verified.pdf"
    preflight = Mock(side_effect=[(root / "old-planned.pdf", None), (final_path, None)])
    monkeypatch.setattr(workflow, "preflight_target", preflight)
    upload = Mock(return_value=SimpleNamespace(id="file_verified"))
    client = object()
    result = workflow.run_manifest_upload(
        root, client_factory=lambda: client, upload_file=upload, attach_file=success_attach,
    )
    assert result.succeeded and preflight.call_count == 2
    upload.assert_called_once_with(client, final_path)


@pytest.mark.parametrize("failure", ["indexing", "id_persistence"])
def test_recovery_wording_matches_confirmed_persistence(tmp_path, failure):
    root = make_case(tmp_path, ("Finance/report.pdf",))

    def saver(manifest, folder):
        if failure == "id_persistence" and manifest.files[0].openai_file_id:
            raise workflow.ManifestPersistenceError("ID checkpoint failed")
        return save_manifest(manifest, folder)

    result = workflow.run_manifest_upload(
        root, client_factory=object,
        upload_file=Mock(return_value=SimpleNamespace(id="file_known")),
        attach_file=Mock(return_value=SimpleNamespace(status="failed")),
        manifest_saver=saver,
    )
    message = ui._file_id_recovery_message(result)
    assert result.recovery_file_id == "file_known"
    assert "do not re-upload" in message
    if failure == "indexing":
        assert "ID is persisted" in message
        assert "could not be confirmed" not in message
    else:
        assert "persistence could not be confirmed" in message
