from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from scripts import reconcile_existing_vector_store_files as script
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.ingestion.manifest_persistence import ManifestPersistenceError


def file_record(
    filename: str,
    size_bytes: int,
    *,
    relative_path: str | None = None,
    classification_status: str = "supported",
    openai_file_id: str | None = None,
) -> VDRFileRecord:
    return VDRFileRecord(
        relative_path=relative_path or filename,
        filename=filename,
        extension=Path(filename).suffix,
        size_bytes=size_bytes,
        classification_status=classification_status,
        classification_reason="test classification",
        openai_file_id=openai_file_id,
        upload_status="failed",
        indexing_status="in_progress",
        upload_attempts=3,
        last_error="historical error",
    )


def manifest_with(*records: VDRFileRecord) -> VDRManifest:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    supported = sum(
        record.classification_status == "supported" for record in records
    )
    unsupported = sum(
        record.classification_status == "unsupported" for record in records
    )
    return VDRManifest(
        case_name="Project Falcon",
        root_path="C:/Deals/Project Falcon/VDR",
        vector_store_id="vs_manifest",
        created_at=now,
        updated_at=now,
        total_files=len(records),
        supported_files=supported,
        unsupported_files=unsupported,
        ignored_files=0,
        error_files=0,
        files=list(records),
    )


def remote(
    file_id: str,
    filename: str,
    size_bytes: int,
) -> script.RemoteFileMetadata:
    return script.RemoteFileMetadata(file_id, filename, size_bytes)


def test_exact_filename_and_size_produces_one_match() -> None:
    manifest = manifest_with(file_record("document.pdf", 100))

    plan = script.build_reconciliation_plan(
        manifest,
        [remote("file_remote", "document.pdf", 100)],
    )

    assert len(plan["matched"]) == 1
    assert plan["matched"][0]["state"] == "will write"
    assert not plan["local_only"]
    assert not plan["remote_only"]
    assert manifest.files[0].openai_file_id is None


def test_same_filename_with_different_size_does_not_match() -> None:
    manifest = manifest_with(file_record("document.pdf", 100))

    plan = script.build_reconciliation_plan(
        manifest,
        [remote("file_remote", "document.pdf", 101)],
    )

    assert not plan["matched"]
    assert len(plan["local_only"]) == 1
    assert len(plan["remote_only"]) == 1


def test_duplicate_local_candidates_are_ambiguous() -> None:
    manifest = manifest_with(
        file_record("document.pdf", 100, relative_path="A/document.pdf"),
        file_record("document.pdf", 100, relative_path="B/document.pdf"),
    )

    plan = script.build_reconciliation_plan(
        manifest,
        [remote("file_remote", "document.pdf", 100)],
    )

    assert len(plan["ambiguous"]) == 1
    assert not plan["matched"]


def test_duplicate_remote_candidates_are_ambiguous() -> None:
    manifest = manifest_with(file_record("document.pdf", 100))

    plan = script.build_reconciliation_plan(
        manifest,
        [
            remote("file_first", "document.pdf", 100),
            remote("file_second", "document.pdf", 100),
        ],
    )

    assert len(plan["ambiguous"]) == 1
    assert not plan["matched"]


def test_unsupported_local_files_are_excluded() -> None:
    manifest = manifest_with(
        file_record(
            "archive.zip",
            100,
            classification_status="unsupported",
        )
    )

    plan = script.build_reconciliation_plan(
        manifest,
        [remote("file_remote", "archive.zip", 100)],
    )

    assert not plan["matched"]
    assert not plan["local_only"]
    assert len(plan["remote_only"]) == 1


def test_identical_existing_id_is_not_planned_for_rewrite() -> None:
    manifest = manifest_with(
        file_record(
            "document.pdf",
            100,
            openai_file_id="file_remote",
        )
    )

    plan = script.build_reconciliation_plan(
        manifest,
        [remote("file_remote", "document.pdf", 100)],
    )

    assert plan["matched"][0]["state"] == "already reconciled"


def test_conflicting_existing_id_is_not_overwritten() -> None:
    manifest = manifest_with(
        file_record(
            "document.pdf",
            100,
            openai_file_id="file_existing",
        )
    )

    plan = script.build_reconciliation_plan(
        manifest,
        [remote("file_remote", "document.pdf", 100)],
    )

    assert not plan["matched"]
    assert plan["ambiguous"][0]["reason"] == (
        "existing OpenAI file ID conflict"
    )
    assert manifest.files[0].openai_file_id == "file_existing"


def configure_main(
    monkeypatch,
    manifest: VDRManifest,
    confirmation: str,
):
    client = Mock()
    attachment = SimpleNamespace(id="file_remote")
    remote_file = SimpleNamespace(
        id="file_remote",
        filename="document.pdf",
        bytes=100,
    )
    save = Mock(return_value=Path("manifest.json"))
    answers = iter(["C:/Deals/Project Falcon/VDR", confirmation])

    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(script, "load_manifest", lambda path: manifest)
    monkeypatch.setattr(script, "get_openai_client", lambda: client)
    monkeypatch.setattr(
        script,
        "list_vector_store_files",
        lambda received_client, vector_store_id: [attachment],
    )
    monkeypatch.setattr(
        script,
        "retrieve_openai_file",
        lambda received_client, file_id: remote_file,
    )
    monkeypatch.setattr(script, "save_manifest", save)
    return client, save


def test_non_reconcile_input_aborts_without_saving(monkeypatch) -> None:
    manifest = manifest_with(file_record("document.pdf", 100))
    client, save = configure_main(monkeypatch, manifest, "yes")

    assert script.main() == 2
    save.assert_not_called()
    assert manifest.files[0].openai_file_id is None
    client.vector_stores.create.assert_not_called()
    client.files.create.assert_not_called()
    client.vector_stores.files.create.assert_not_called()
    client.vector_stores.files.update.assert_not_called()
    client.vector_stores.files.delete.assert_not_called()


def test_exact_reconcile_persists_only_unambiguous_id(monkeypatch) -> None:
    record = file_record("document.pdf", 100)
    manifest = manifest_with(record)
    original_state = {
        "relative_path": record.relative_path,
        "classification_status": record.classification_status,
        "upload_status": record.upload_status,
        "indexing_status": record.indexing_status,
        "upload_attempts": record.upload_attempts,
        "last_error": record.last_error,
    }
    client, save = configure_main(monkeypatch, manifest, "RECONCILE")

    assert script.main() == 0
    save.assert_called_once_with(
        manifest,
        "C:/Deals/Project Falcon/VDR",
    )
    assert manifest.files[0].openai_file_id == "file_remote"
    assert {
        "relative_path": record.relative_path,
        "classification_status": record.classification_status,
        "upload_status": record.upload_status,
        "indexing_status": record.indexing_status,
        "upload_attempts": record.upload_attempts,
        "last_error": record.last_error,
    } == original_state
    client.vector_stores.create.assert_not_called()
    client.files.create.assert_not_called()
    client.vector_stores.files.create.assert_not_called()
    client.vector_stores.files.update.assert_not_called()
    client.vector_stores.files.delete.assert_not_called()


def test_missing_manifest_vector_store_id_refuses_before_client(
    monkeypatch,
) -> None:
    manifest = manifest_with(file_record("document.pdf", 100))
    manifest.vector_store_id = None
    client_factory = Mock()
    monkeypatch.setattr("builtins.input", lambda prompt: "C:/VDR")
    monkeypatch.setattr(script, "load_manifest", lambda path: manifest)
    monkeypatch.setattr(script, "get_openai_client", client_factory)

    assert script.main() == 1
    client_factory.assert_not_called()


def test_already_reconciled_manifest_is_not_saved(monkeypatch) -> None:
    manifest = manifest_with(
        file_record(
            "document.pdf",
            100,
            openai_file_id="file_remote",
        )
    )
    client, save = configure_main(monkeypatch, manifest, "unused")

    assert script.main() == 0
    save.assert_not_called()
    client.vector_stores.create.assert_not_called()


def test_save_failure_does_not_report_success(
    monkeypatch,
    capsys,
) -> None:
    manifest = manifest_with(file_record("document.pdf", 100))
    _, save = configure_main(monkeypatch, manifest, "RECONCILE")
    save.side_effect = ManifestPersistenceError("synthetic failure")

    assert script.main() == 1
    captured = capsys.readouterr()
    assert "was not persisted" in captured.err
    assert "No OpenAI resources were modified" in captured.err
    assert "Reconciled manifest" not in captured.out
