from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import upload_new_manifest_files as script
from src.ingestion.manifest import VDRFileRecord
from src.ingestion.manifest_builder import build_manifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    create_manifest,
    load_manifest,
    save_manifest,
)


def make_case(
    tmp_path: Path,
    filenames: tuple[str, ...] = ("new.pdf",),
) -> Path:
    vdr_folder = tmp_path / "Industry" / "Project Falcon" / "VDR"
    vdr_folder.mkdir(parents=True)
    for filename in filenames:
        path = vdr_folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"content for {filename}".encode())

    manifest = build_manifest(str(vdr_folder))
    manifest.vector_store_id = "vs_manifest"
    create_manifest(manifest, vdr_folder)
    return vdr_folder


def provide_inputs(monkeypatch, *responses: str) -> None:
    answers = iter(responses)
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))


def test_eligibility_selects_only_supported_records_without_id() -> None:
    records = [
        VDRFileRecord(
            relative_path="eligible.pdf",
            filename="eligible.pdf",
            extension=".pdf",
            size_bytes=1,
            classification_status="supported",
            classification_reason="supported",
        ),
        VDRFileRecord(
            relative_path="existing.pdf",
            filename="existing.pdf",
            extension=".pdf",
            size_bytes=1,
            classification_status="supported",
            classification_reason="supported",
            openai_file_id="file_existing",
        ),
    ]
    for status in ("unsupported", "ignored", "error"):
        records.append(
            VDRFileRecord(
                relative_path=f"{status}.bin",
                filename=f"{status}.bin",
                extension=".bin",
                size_bytes=1,
                classification_status=status,
                classification_reason=status,
            )
        )
    manifest = SimpleNamespace(files=records)

    assert script.select_eligible_records(manifest) == [records[0]]


def test_no_eligible_records_skips_confirmation_save_and_client(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    manifest = load_manifest(vdr_folder)
    manifest.files[0].openai_file_id = "file_existing"
    manifest.files[0].upload_status = "uploaded"
    manifest.files[0].indexing_status = "completed"
    save_manifest(manifest, vdr_folder)
    save = Mock()
    client_factory = Mock()
    monkeypatch.setattr(script, "save_manifest", save)
    monkeypatch.setattr(script, "get_openai_client", client_factory)
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        if len(prompts) > 1:
            raise AssertionError("confirmation must not be requested")
        return str(vdr_folder)

    monkeypatch.setattr("builtins.input", answer)

    assert script.main() == 0
    assert len(prompts) == 1
    save.assert_not_called()
    client_factory.assert_not_called()


def test_invalid_confirmation_has_no_side_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    before = load_manifest(vdr_folder).model_dump()
    save = Mock()
    client_factory = Mock()
    upload = Mock()
    monkeypatch.setattr(script, "save_manifest", save)
    monkeypatch.setattr(script, "get_openai_client", client_factory)
    monkeypatch.setattr(script, "upload_openai_file", upload)
    provide_inputs(monkeypatch, str(vdr_folder), "yes")

    assert script.main() == 2
    assert load_manifest(vdr_folder).model_dump() == before
    save.assert_not_called()
    client_factory.assert_not_called()
    upload.assert_not_called()


@pytest.mark.parametrize(
    ("relative_path", "setup", "message"),
    [
        ("missing.pdf", lambda root: None, "missing"),
        ("../outside.pdf", lambda root: None, "escapes"),
        ("C:/absolute.pdf", lambda root: None, "absolute"),
        ("folder", lambda root: (root / "folder").mkdir(), "not a file"),
        (
            "changed.pdf",
            lambda root: (root / "changed.pdf").write_bytes(b"different"),
            "size changed",
        ),
    ],
)
def test_preflight_rejects_invalid_paths(
    tmp_path: Path,
    relative_path: str,
    setup,
    message: str,
) -> None:
    root = tmp_path / "VDR"
    root.mkdir()
    setup(root)
    record = SimpleNamespace(
        relative_path=relative_path,
        size_bytes=999,
    )

    with pytest.raises(ValueError, match=message):
        script.preflight_local_files(root, [record])


def test_preflight_ignores_persisted_absolute_path(tmp_path: Path) -> None:
    root = tmp_path / "VDR"
    root.mkdir()
    local_path = root / "nested" / "document.pdf"
    local_path.parent.mkdir()
    local_path.write_bytes(b"data")
    record = SimpleNamespace(
        relative_path="nested/document.pdf",
        absolute_path="Z:/stale/wrong/document.pdf",
        size_bytes=4,
    )

    assert script.preflight_local_files(root, [record]) == [
        (record, local_path.resolve())
    ]


def configure_success(monkeypatch, events: list[str]):
    client = Mock()
    monkeypatch.setattr(
        script,
        "get_openai_client",
        lambda: events.append("client") or client,
    )

    def upload(received_client, local_path):
        events.append(f"upload:{local_path.name}")
        return SimpleNamespace(id=f"file_{local_path.stem}")

    def attach(received_client, vector_store_id, file_id):
        events.append(f"attach:{file_id}")
        return SimpleNamespace(status="completed", last_error=None)

    monkeypatch.setattr(script, "upload_openai_file", upload)
    monkeypatch.setattr(script, "attach_file_and_poll", attach)
    return client


def test_success_persists_uploading_id_and_completed_states_in_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    events = []
    configure_success(monkeypatch, events)
    real_save = save_manifest
    snapshots = []

    def capture_save(manifest, folder):
        record = manifest.files[0]
        snapshots.append(
            (
                record.openai_file_id,
                record.upload_status,
                record.indexing_status,
                record.upload_attempts,
                record.last_error,
            )
        )
        events.append(f"save:{record.indexing_status}")
        return real_save(manifest, folder)

    monkeypatch.setattr(script, "save_manifest", capture_save)
    provide_inputs(monkeypatch, str(vdr_folder), "UPLOAD")

    assert script.main() == 0
    assert snapshots == [
        (None, "uploading", "not_started", 1, None),
        ("file_new", "uploaded", "not_started", 1, None),
        ("file_new", "uploaded", "in_progress", 1, None),
        ("file_new", "uploaded", "completed", 1, None),
    ]
    assert events == [
        "client",
        "save:not_started",
        "upload:new.pdf",
        "save:not_started",
        "save:in_progress",
        "attach:file_new",
        "save:completed",
    ]


def test_generic_upload_failure_is_persisted_as_uncertain_without_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    client = Mock()
    upload = Mock(side_effect=RuntimeError("synthetic upload failure"))
    attach = Mock()
    monkeypatch.setattr(script, "get_openai_client", lambda: client)
    monkeypatch.setattr(script, "upload_openai_file", upload)
    monkeypatch.setattr(script, "attach_file_and_poll", attach)
    provide_inputs(monkeypatch, str(vdr_folder), "UPLOAD")

    assert script.main() == 1
    persisted = load_manifest(vdr_folder).files[0]
    assert persisted.openai_file_id is None
    assert persisted.upload_status == "uploading"
    assert persisted.indexing_status == "not_started"
    assert persisted.upload_attempts == 1
    assert "uncertain" in persisted.last_error
    assert "synthetic upload failure" not in persisted.last_error
    upload.assert_called_once()
    attach.assert_not_called()


def test_attachment_exception_preserves_id_and_in_progress_recovery_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    client = Mock()
    monkeypatch.setattr(script, "get_openai_client", lambda: client)
    monkeypatch.setattr(
        script,
        "upload_openai_file",
        lambda client, path: SimpleNamespace(id="file_uploaded"),
    )
    monkeypatch.setattr(
        script,
        "attach_file_and_poll",
        Mock(side_effect=RuntimeError("synthetic attach failure")),
    )
    provide_inputs(monkeypatch, str(vdr_folder), "UPLOAD")

    assert script.main() == 1
    persisted = load_manifest(vdr_folder).files[0]
    assert persisted.openai_file_id == "file_uploaded"
    assert persisted.upload_status == "uploaded"
    assert persisted.indexing_status == "in_progress"
    assert "requires recovery" in persisted.last_error


@pytest.mark.parametrize("remote_status", ["failed", "cancelled"])
def test_remote_terminal_failure_statuses_map_to_indexing_failed(
    tmp_path: Path,
    monkeypatch,
    remote_status: str,
) -> None:
    vdr_folder = make_case(tmp_path)
    client = Mock()
    monkeypatch.setattr(script, "get_openai_client", lambda: client)
    monkeypatch.setattr(
        script,
        "upload_openai_file",
        lambda client, path: SimpleNamespace(id="file_uploaded"),
    )
    monkeypatch.setattr(
        script,
        "attach_file_and_poll",
        lambda *args: SimpleNamespace(
            status=remote_status,
            last_error=SimpleNamespace(
                code="processing_error",
                message="synthetic remote failure",
            ),
        ),
    )
    provide_inputs(monkeypatch, str(vdr_folder), "UPLOAD")

    assert script.main() == 1
    persisted = load_manifest(vdr_folder).files[0]
    assert persisted.upload_status == "uploaded"
    assert persisted.indexing_status == "failed"
    assert remote_status in persisted.last_error
    assert "synthetic remote failure" not in persisted.last_error


def test_id_save_failure_stops_before_attachment_and_reports_id(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    vdr_folder = make_case(tmp_path, ("first.pdf", "second.pdf"))
    client = Mock()
    attach = Mock()
    upload = Mock(return_value=SimpleNamespace(id="file_recover"))
    monkeypatch.setattr(script, "get_openai_client", lambda: client)
    monkeypatch.setattr(script, "upload_openai_file", upload)
    monkeypatch.setattr(script, "attach_file_and_poll", attach)
    real_save = save_manifest
    calls = 0

    def fail_second_save(manifest, folder):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ManifestPersistenceError("synthetic ID save failure")
        return real_save(manifest, folder)

    monkeypatch.setattr(script, "save_manifest", fail_second_save)
    provide_inputs(monkeypatch, str(vdr_folder), "UPLOAD")

    assert script.main() == 1
    captured = capsys.readouterr()
    assert "file_recover" in captured.err
    assert "reconcile it manually" in captured.err
    attach.assert_not_called()
    upload.assert_called_once()
    client.files.delete.assert_not_called()
    persisted = load_manifest(vdr_folder)
    assert all(record.openai_file_id is None for record in persisted.files)


def test_in_progress_save_failure_stops_before_attachment_and_later_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path, ("first.pdf", "second.pdf"))
    client = Mock()
    upload = Mock(
        side_effect=lambda client, path: SimpleNamespace(
            id=f"file_{path.stem}"
        )
    )
    attach = Mock(return_value=SimpleNamespace(status="completed"))
    monkeypatch.setattr(script, "get_openai_client", lambda: client)
    monkeypatch.setattr(script, "upload_openai_file", upload)
    monkeypatch.setattr(script, "attach_file_and_poll", attach)
    real_save = save_manifest
    calls = 0

    def fail_third_save(manifest, folder):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ManifestPersistenceError("synthetic terminal save failure")
        return real_save(manifest, folder)

    monkeypatch.setattr(script, "save_manifest", fail_third_save)
    provide_inputs(monkeypatch, str(vdr_folder), "UPLOAD")

    assert script.main() == 1
    upload.assert_called_once()
    attach.assert_not_called()
    persisted = load_manifest(vdr_folder)
    first = persisted.files[0]
    second = persisted.files[1]
    assert first.openai_file_id == f"file_{Path(first.filename).stem}"
    assert first.indexing_status == "not_started"
    assert second.openai_file_id is None
    client.files.delete.assert_not_called()
    client.vector_stores.files.delete.assert_not_called()


def test_multiple_files_are_processed_sequentially(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path, ("first.pdf", "second.pdf"))
    events = []
    configure_success(monkeypatch, events)
    provide_inputs(monkeypatch, str(vdr_folder), "UPLOAD")

    assert script.main() == 0
    assert events == [
        "client",
        "upload:first.pdf",
        "attach:file_first",
        "upload:second.pdf",
        "attach:file_second",
    ]
