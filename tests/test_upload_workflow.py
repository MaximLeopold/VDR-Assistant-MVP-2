from src.ingestion.upload_targets import UploadTargetKey
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ingestion.manifest import VDRFileRecord
from src.ingestion.manifest_builder import build_manifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    create_manifest,
    load_manifest,
    save_manifest,
)
from src.ingestion.upload_workflow import (
    DefinitePreRemoteUploadError,
    UploadDisposition,
    UploadPreparationError,
    classify_manifest_record,
    prepare_manifest_upload,
    run_manifest_upload,
)


def record(
    *,
    classification_status="supported",
    openai_file_id=None,
    upload_status="not_uploaded",
    indexing_status="not_started",
) -> VDRFileRecord:
    return VDRFileRecord(
        relative_path="document.pdf",
        filename="document.pdf",
        extension=".pdf",
        size_bytes=1,
        classification_status=classification_status,
        classification_reason="test",
        openai_file_id=openai_file_id,
        upload_status=upload_status,
        indexing_status=indexing_status,
    )


@pytest.mark.parametrize("upload", ["not_uploaded", "uploading", "failed", "uploaded"])
@pytest.mark.parametrize(
    "indexing", ["not_started", "in_progress", "failed", "completed"]
)
@pytest.mark.parametrize("file_id", [None, "file_known", " "])
def test_manifest_states_define_eligibility(upload, indexing, file_id):
    item = record(
        upload_status=upload, indexing_status=indexing, openai_file_id=file_id
    )
    classification = classify_manifest_record(item)
    assert classification.eligible is (
        file_id is None and indexing == "not_started" and upload != "uploaded"
    )
    if file_id is not None:
        assert not classification.eligible
    if file_id == "file_known" and upload == "uploaded":
        assert classification.disposition == (
            UploadDisposition.COMPLETED
            if indexing == "completed"
            else UploadDisposition.RECOVERY_ONLY
        )


def make_case(tmp_path: Path, filenames=("z.pdf", "Nested/a.pdf")) -> Path:
    vdr_folder = tmp_path / "Project" / "VDR"
    vdr_folder.mkdir(parents=True)
    for filename in filenames:
        path = vdr_folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"content:{filename}".encode())
    manifest = build_manifest(str(vdr_folder))
    manifest.vector_store_id = "vs_manifest_owned"
    create_manifest(manifest, vdr_folder)
    return vdr_folder


def test_preparation_is_read_only_deterministic_and_probes_all_candidates(
    tmp_path: Path,
) -> None:
    vdr_folder = make_case(tmp_path)
    before = load_manifest(vdr_folder).model_dump()

    plan = prepare_manifest_upload(vdr_folder)

    assert [candidate.key.source_relative_path for candidate in plan.candidates] == [
        "Nested/a.pdf",
        "z.pdf",
    ]
    assert all(row.preflight_ok for row in plan.rows)
    assert not plan.blockers
    assert load_manifest(vdr_folder).model_dump() == before


def test_preparation_reports_every_preflight_blocker(tmp_path: Path) -> None:
    vdr_folder = make_case(tmp_path, ("first.pdf", "second.pdf"))
    (vdr_folder / "first.pdf").unlink()
    (vdr_folder / "second.pdf").write_bytes(b"changed")

    plan = prepare_manifest_upload(vdr_folder)

    attempted = [row for row in plan.rows if row.eligible]
    assert len(attempted) == 2
    assert all(row.preflight_ok is False for row in attempted)
    assert not plan.blockers
    assert plan.can_execute


@pytest.mark.parametrize("relative_path", ["../outside.pdf", "C:/absolute.pdf"])
def test_preparation_blocks_unsafe_stored_paths(
    tmp_path: Path,
    relative_path: str,
) -> None:
    vdr_folder = make_case(tmp_path, ("document.pdf",))
    manifest = load_manifest(vdr_folder)
    manifest.files[0].relative_path = relative_path
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        save_manifest(manifest, vdr_folder)
    # Externally corrupted manifests fail closed at loading, before planning.
    (vdr_folder.parent / "VDR Assistant" / "manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(UploadPreparationError):
        prepare_manifest_upload(vdr_folder)


def test_preparation_blocks_unreadable_file(tmp_path: Path, monkeypatch) -> None:
    vdr_folder = make_case(tmp_path, ("document.pdf",))
    real_open = Path.open

    def deny_document(self, *args, **kwargs):
        if self.name == "document.pdf":
            raise PermissionError("sensitive raw error")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_document)

    plan = prepare_manifest_upload(vdr_folder)

    assert not plan.blockers
    assert plan.rows[0].blocking_reason == "The reviewed file is not locally readable."


def test_preparation_requires_owned_manifest_and_vector_store(tmp_path: Path) -> None:
    missing = tmp_path / "Missing" / "VDR"
    missing.mkdir(parents=True)
    with pytest.raises(UploadPreparationError):
        prepare_manifest_upload(missing)

    blank = make_case(tmp_path / "blank", ("document.pdf",))
    manifest = load_manifest(blank)
    manifest.vector_store_id = None
    (blank.parent / "VDR Assistant" / "manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(UploadPreparationError, match="vector-store association"):
        prepare_manifest_upload(blank)

    mismatch = make_case(tmp_path / "mismatch", ("document.pdf",))
    manifest = load_manifest(mismatch)
    manifest.root_path = str((tmp_path / "other" / "VDR").resolve())
    (mismatch.parent / "VDR Assistant" / "manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(UploadPreparationError, match="does not belong"):
        prepare_manifest_upload(mismatch)


def test_uncertain_record_is_reported_while_safe_candidate_remains(
    tmp_path: Path,
) -> None:
    vdr_folder = make_case(tmp_path, ("first.pdf", "second.pdf"))
    manifest = load_manifest(vdr_folder)
    first = next(item for item in manifest.files if item.relative_path == "first.pdf")
    first.upload_status = "uploading"
    save_manifest(manifest, vdr_folder)

    plan = prepare_manifest_upload(vdr_folder)

    assert len(plan.candidates) == 2
    assert plan.count(UploadDisposition.RETRY_CANDIDATE) == 1
    assert not plan.blockers


def success_upload(_client, local_path: Path):
    return SimpleNamespace(id=f"file_{local_path.stem}")


def success_attach(_client, vector_store_id: str, file_id: str):
    return SimpleNamespace(
        status="completed",
        vector_store_id=vector_store_id,
        id=file_id,
    )


def test_execution_persists_all_checkpoints_before_attachment(
    tmp_path: Path,
) -> None:
    vdr_folder = make_case(tmp_path, ("document.pdf",))
    events: list[str] = []
    snapshots: list[tuple] = []
    real_save = save_manifest

    def capture_save(manifest, folder):
        item = manifest.files[0]
        snapshots.append(
            (
                item.openai_file_id,
                item.upload_status,
                item.indexing_status,
                item.upload_attempts,
            )
        )
        events.append(f"save:{item.indexing_status}")
        return real_save(manifest, folder)

    def attach(client, vector_store_id, file_id):
        persisted = load_manifest(vdr_folder).files[0]
        assert persisted.openai_file_id == file_id
        assert persisted.indexing_status == "in_progress"
        events.append(f"attach:{vector_store_id}:{file_id}")
        return SimpleNamespace(
            status="completed", id=file_id, vector_store_id=vector_store_id
        )

    result = run_manifest_upload(
        vdr_folder,
        client_factory=lambda: object(),
        upload_file=success_upload,
        attach_file=attach,
        manifest_saver=capture_save,
        progress_callback=lambda event: events.append(event.kind),
    )

    assert result.succeeded
    assert snapshots == [
        (None, "uploading", "not_started", 1),
        ("file_document", "uploaded", "not_started", 1),
        ("file_document", "uploaded", "in_progress", 1),
        ("file_document", "uploaded", "completed", 1),
    ]
    assert events.index("save:not_started", 1) < events.index("file_id_persisted")
    assert events.index("save:in_progress") < events.index(
        "attach:vs_manifest_owned:file_document"
    )
    assert events == [
        "batch_started",
        "file_started",
        "save:not_started",
        "manifest_marked_uploading",
        "save:not_started",
        "file_uploaded",
        "file_id_persisted",
        "save:in_progress",
        "attachment_started",
        "attach:vs_manifest_owned:file_document",
        "save:completed",
        "indexing_completed",
        "batch_completed",
    ]


def test_final_preflight_failure_does_not_construct_client(tmp_path: Path) -> None:
    vdr_folder = make_case(tmp_path, ("document.pdf",))
    (vdr_folder / "document.pdf").unlink()
    factory = Mock()

    result = run_manifest_upload(vdr_folder, client_factory=factory)

    assert result.pass_outcome == "finished"
    assert result.no_id_retryable_count == 1
    factory.assert_not_called()
    assert load_manifest(vdr_folder).files[0].upload_status == "failed"


def test_definite_pre_remote_failure_continues_later_file(tmp_path: Path) -> None:
    vdr_folder = make_case(tmp_path, ("first.pdf", "second.pdf"))
    calls: list[str] = []

    def upload(_client, path):
        calls.append(path.name)
        if path.name == "first.pdf":
            raise DefinitePreRemoteUploadError("not sent")
        return SimpleNamespace(id="file_second")

    result = run_manifest_upload(
        vdr_folder,
        client_factory=lambda: object(),
        upload_file=upload,
        attach_file=success_attach,
    )

    assert calls == ["first.pdf", "second.pdf"]
    assert result.completed_count == 1
    assert result.no_id_retryable_count == 1
    persisted = load_manifest(vdr_folder)
    first = next(item for item in persisted.files if item.relative_path == "first.pdf")
    assert first.upload_status == "failed"
    assert first.openai_file_id is None


def test_exhausted_upload_failure_continues_later_files(
    tmp_path: Path,
) -> None:
    vdr_folder = make_case(tmp_path, ("first.pdf", "second.pdf"))
    upload = Mock(side_effect=TimeoutError("raw timeout detail"))

    result = run_manifest_upload(
        vdr_folder,
        client_factory=lambda: object(),
        upload_file=upload,
        attach_file=Mock(),
    )

    assert result.pass_outcome == "finished"
    assert result.no_id_retryable_count == 2
    assert upload.call_count == 2
    persisted = load_manifest(vdr_folder)
    first = next(item for item in persisted.files if item.relative_path == "first.pdf")
    second = next(
        item for item in persisted.files if item.relative_path == "second.pdf"
    )
    assert first.upload_status == "uploading"
    assert "raw timeout detail" not in first.last_error
    assert second.upload_status == "uploading"


def test_id_persistence_failure_stops_before_attachment_and_returns_exact_id(
    tmp_path: Path,
) -> None:
    vdr_folder = make_case(tmp_path, ("document.pdf",))
    attach = Mock()
    real_save = save_manifest
    save_calls = 0

    def fail_id_save(manifest, folder):
        nonlocal save_calls
        save_calls += 1
        if save_calls == 2:
            raise ManifestPersistenceError("ID save failed")
        return real_save(manifest, folder)

    result = run_manifest_upload(
        vdr_folder,
        client_factory=lambda: object(),
        upload_file=lambda *_args: SimpleNamespace(id="file_recovery_exact"),
        attach_file=attach,
        manifest_saver=fail_id_save,
    )

    assert result.critically_stopped
    assert result.recovery_file_id == "file_recovery_exact"
    attach.assert_not_called()
    persisted = load_manifest(vdr_folder).files[0]
    assert persisted.upload_status == "uploading"
    assert persisted.openai_file_id is None


def test_indexing_failure_and_interruption_continue_later_files(
    tmp_path: Path,
) -> None:
    vdr_folder = make_case(
        tmp_path,
        ("first.pdf", "second.pdf", "third.pdf"),
    )
    attach_calls = 0

    def attach(_client, _vector_store_id, _file_id):
        nonlocal attach_calls
        attach_calls += 1
        if attach_calls == 1:
            return SimpleNamespace(
                status="failed", id=_file_id, vector_store_id=_vector_store_id
            )
        if attach_calls == 2:
            raise TimeoutError("raw polling failure")
        return SimpleNamespace(
            status="completed", id=_file_id, vector_store_id=_vector_store_id
        )

    result = run_manifest_upload(
        vdr_folder,
        client_factory=lambda: object(),
        upload_file=success_upload,
        attach_file=attach,
    )

    assert result.completed_count == 1
    assert result.recovery_count == 2
    assert attach_calls == 3
    persisted = load_manifest(vdr_folder)
    states = {item.relative_path: item.indexing_status for item in persisted.files}
    assert states == {
        "first.pdf": "failed",
        "second.pdf": "in_progress",
        "third.pdf": "completed",
    }


def test_manifest_checkpoint_failure_stops_complete_batch(tmp_path: Path) -> None:
    vdr_folder = make_case(tmp_path, ("first.pdf", "second.pdf"))
    upload = Mock()

    result = run_manifest_upload(
        vdr_folder,
        client_factory=lambda: object(),
        upload_file=upload,
        attach_file=Mock(),
        manifest_saver=Mock(side_effect=ManifestPersistenceError("no save")),
    )

    assert result.critically_stopped
    upload.assert_not_called()


def test_restart_without_id_allows_one_new_logical_upload(tmp_path):
    vdr_folder = make_case(tmp_path, ("document.pdf",))
    manifest = load_manifest(vdr_folder)
    manifest.files[0].upload_status = "uploading"
    manifest.files[0].upload_attempts = 2
    save_manifest(manifest, vdr_folder)
    upload = Mock(side_effect=success_upload)
    result = run_manifest_upload(
        vdr_folder,
        client_factory=object,
        upload_file=upload,
        attach_file=success_attach,
    )
    assert result.succeeded
    upload.assert_called_once()
    assert load_manifest(vdr_folder).files[0].upload_attempts == 3


def test_execution_reloads_and_reclassifies_manifest_before_remote_upload(
    tmp_path: Path,
) -> None:
    vdr_folder = make_case(tmp_path, ("document.pdf",))
    upload = Mock()

    def change_disk_state_before_execution():
        manifest = load_manifest(vdr_folder)
        item = manifest.files[0]
        item.openai_file_id = "file_completed_elsewhere"
        item.upload_status = "uploaded"
        item.indexing_status = "completed"
        save_manifest(manifest, vdr_folder)
        return object()

    result = run_manifest_upload(
        vdr_folder,
        client_factory=change_disk_state_before_execution,
        upload_file=upload,
    )

    assert result.critically_stopped
    assert "stopped" in result.message
    upload.assert_not_called()
