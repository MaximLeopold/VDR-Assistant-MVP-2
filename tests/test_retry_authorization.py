"""No-ID retry policy and retained candidate identity checks; no session proof."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.ingestion import upload_workflow as workflow
from src.ingestion.manifest_persistence import (
    derive_manifest_paths,
    load_manifest,
    save_manifest,
)
from src.ui import new_case_setup as ui
from test_upload_workflow import make_case, success_attach, success_upload


@pytest.mark.parametrize(
    "failure", [workflow.DefinitePreRemoteUploadError(), TimeoutError(), None]
)
def test_no_id_failure_is_retryable_after_restart_without_session_proof(
    tmp_path, failure
):
    root = make_case(tmp_path, ("report.pdf",))
    upload = Mock(side_effect=failure, return_value=SimpleNamespace(id=None))
    first = workflow.run_manifest_upload(
        root, client_factory=object, upload_file=upload
    )
    assert first.pass_outcome == "finished"
    assert first.no_id_retryable_count == 1
    upload.assert_called_once()
    assert load_manifest(root).files[0].upload_attempts == 1
    del first
    second = workflow.run_manifest_upload(
        root,
        client_factory=object,
        upload_file=success_upload,
        attach_file=success_attach,
    )
    assert second.succeeded
    assert load_manifest(root).files[0].upload_attempts == 2


@pytest.mark.parametrize("change", ["replacement", "store", "content", "other_root"])
def test_reviewed_candidate_context_cannot_transfer_or_survive_replacement(
    tmp_path, change
):
    root = make_case(tmp_path / "A", ("report.pdf",))
    reviewed = workflow.prepare_manifest_upload(root).context
    if change == "other_root":
        root = make_case(tmp_path / "B", ("report.pdf",))
    else:
        manifest = load_manifest(root)
        if change == "replacement":
            manifest.created_at += timedelta(microseconds=1)
        elif change == "store":
            manifest.vector_store_id = "vs_replacement"
        else:
            manifest.case_name = "Replacement snapshot"
        derive_manifest_paths(root).manifest_path.write_text(manifest.model_dump_json())
    factory = Mock()
    result = workflow.run_manifest_upload(
        root, client_factory=factory, expected_context=reviewed
    )
    assert result.critically_stopped
    factory.assert_not_called()


def test_runner_rechecks_candidate_after_plan_before_upload(tmp_path):
    root = make_case(tmp_path, ("report.pdf",))

    def replace_after_plan():
        manifest = load_manifest(root)
        manifest.created_at += timedelta(seconds=1)
        derive_manifest_paths(root).manifest_path.write_text(manifest.model_dump_json())
        return object()

    upload = Mock()
    result = workflow.run_manifest_upload(
        root, client_factory=replace_after_plan, upload_file=upload
    )
    assert result.critically_stopped
    upload.assert_not_called()


@pytest.mark.parametrize("action", ["start", "cancel", "folder", "case"])
def test_setup_context_changes_clear_previous_result(tmp_path, monkeypatch, action):
    root = make_case(tmp_path, ("report.pdf",))
    state = {
        ui.SETUP_FOLDER_KEY: str(root.resolve()),
        ui.SETUP_CASE_ID_KEY: "case-a",
        ui.SETUP_UPLOAD_RESULT_KEY: object(),
    }
    monkeypatch.setattr(ui.st, "rerun", Mock())
    if action == "start":
        ui.start_new_case_setup(state)
    elif action == "cancel":
        ui._cancel_setup(state)
    else:
        ui._set_setup_candidate(
            state,
            root if action == "case" else root.parent / "OtherVDR",
            "case-b" if action == "case" else "case-a",
        )
    assert ui.SETUP_UPLOAD_RESULT_KEY not in state


def test_upload_uses_final_verified_path(tmp_path, monkeypatch):
    root = make_case(tmp_path, ("Finance/report.pdf",))
    final_path = root / "final-verified.pdf"
    preflight = Mock(side_effect=[(root / "old-planned.pdf", None), (final_path, None)])
    monkeypatch.setattr(workflow, "preflight_target", preflight)
    upload = Mock(return_value=SimpleNamespace(id="file_verified"))
    client = object()
    result = workflow.run_manifest_upload(
        root,
        client_factory=lambda: client,
        upload_file=upload,
        attach_file=success_attach,
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
        root,
        client_factory=object,
        upload_file=Mock(return_value=SimpleNamespace(id="file_known")),
        attach_file=Mock(
            return_value=SimpleNamespace(
                status="failed", id="file_known", vector_store_id="vs_manifest_owned"
            )
        ),
        manifest_saver=saver,
    )
    message = ui._file_id_recovery_message(result)
    assert result.recovery_file_id == "file_known"
    if failure == "indexing":
        assert "ID is persisted" in message
        assert "could not be confirmed" not in message
    else:
        assert "persistence could not be confirmed" in message
