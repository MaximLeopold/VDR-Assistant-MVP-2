from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ingestion.case_vector_store import (
    CaseVectorStoreConflictError,
    NoCaseVectorStoreError,
    VectorStoreCreatedButNotPersistedError,
    adopt_case_vector_store,
    ensure_case_vector_store,
)
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    load_manifest,
    save_manifest,
)
from src.ingestion.vector_store_manager import VectorStoreConnectionError


def make_case(tmp_path: Path, vector_store_id: str | None = None):
    project = tmp_path / "Industry" / "Project Falcon"
    vdr = project / "VDR"
    vdr.mkdir(parents=True)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = VDRFileRecord(
        relative_path="Legal/sample.pdf",
        filename="sample.pdf",
        extension=".pdf",
        size_bytes=12,
        classification_status="supported",
        classification_reason="Supported file type",
    )
    manifest = VDRManifest(
        case_name="Project Falcon",
        root_path=str(vdr),
        vector_store_id=vector_store_id,
        created_at=now,
        updated_at=now,
        total_files=1,
        supported_files=1,
        unsupported_files=0,
        ignored_files=0,
        error_files=0,
        files=[record],
    )
    save_manifest(manifest, vdr)
    return vdr, manifest


def make_client() -> Mock:
    client = Mock()
    client.vector_stores = Mock()
    return client


def remote(store_id: str, name: str = "Historical Store"):
    return SimpleNamespace(id=store_id, name=name)


def test_existing_manifest_id_is_validated_and_reused(
    tmp_path: Path,
) -> None:
    vdr, _ = make_case(tmp_path, "vs_existing")
    client = make_client()
    client.vector_stores.retrieve.return_value = remote("vs_existing")
    previous_json = (
        vdr.parent / "VDR Assistant" / "manifest.json"
    ).read_text(encoding="utf-8")

    result = ensure_case_vector_store(client, vdr)

    assert result.action == "reused"
    assert result.vector_store_id == "vs_existing"
    client.vector_stores.retrieve.assert_called_once_with("vs_existing")
    client.vector_stores.create.assert_not_called()
    assert (
        vdr.parent / "VDR Assistant" / "manifest.json"
    ).read_text(encoding="utf-8") == previous_json


def test_same_candidate_is_idempotently_reused(tmp_path: Path) -> None:
    vdr, _ = make_case(tmp_path, "vs_same")
    client = make_client()
    client.vector_stores.retrieve.return_value = remote("vs_same")

    result = adopt_case_vector_store(client, vdr, " vs_same ")

    assert result.action == "reused"
    client.vector_stores.create.assert_not_called()


def test_conflicting_ids_fail_before_remote_calls(tmp_path: Path) -> None:
    vdr, _ = make_case(tmp_path, "vs_manifest")
    client = make_client()

    with pytest.raises(CaseVectorStoreConflictError):
        ensure_case_vector_store(
            client,
            vdr,
            adoption_candidate="vs_environment",
            allow_create=True,
        )

    client.vector_stores.retrieve.assert_not_called()
    client.vector_stores.create.assert_not_called()
    assert load_manifest(vdr).vector_store_id == "vs_manifest"


def test_valid_candidate_is_retrieved_then_adopted(tmp_path: Path) -> None:
    vdr, _ = make_case(tmp_path)
    client = make_client()
    client.vector_stores.retrieve.return_value = remote("vs_adopted")

    result = ensure_case_vector_store(
        client,
        vdr,
        adoption_candidate="vs_adopted",
        allow_create=True,
    )

    assert result.action == "adopted"
    assert load_manifest(vdr).vector_store_id == "vs_adopted"
    client.vector_stores.retrieve.assert_called_once_with("vs_adopted")
    client.vector_stores.create.assert_not_called()


def test_invalid_candidate_is_not_persisted(tmp_path: Path) -> None:
    vdr, _ = make_case(tmp_path)
    client = make_client()
    client.vector_stores.retrieve.side_effect = VectorStoreConnectionError(
        "uncertain"
    )

    with pytest.raises(VectorStoreConnectionError):
        ensure_case_vector_store(client, vdr, adoption_candidate="vs_candidate")

    assert load_manifest(vdr).vector_store_id is None


def test_creation_requires_explicit_permission(tmp_path: Path) -> None:
    vdr, _ = make_case(tmp_path)
    client = make_client()

    with pytest.raises(NoCaseVectorStoreError):
        ensure_case_vector_store(client, vdr)

    client.vector_stores.create.assert_not_called()


def test_new_case_creates_once_and_persists_all_state(tmp_path: Path) -> None:
    vdr, _ = make_case(tmp_path)
    client = make_client()
    client.vector_stores.create.return_value = remote(
        "vs_created", "VDR Assistant - Project Falcon"
    )

    created = ensure_case_vector_store(client, vdr, allow_create=True)
    client.vector_stores.retrieve.return_value = remote("vs_created")
    reused = ensure_case_vector_store(client, vdr, allow_create=True)
    persisted = load_manifest(vdr)

    assert created.action == "created"
    assert reused.action == "reused"
    client.vector_stores.create.assert_called_once_with(
        name="VDR Assistant - Project Falcon"
    )
    assert persisted.vector_store_id == "vs_created"
    assert persisted.files[0].relative_path == "Legal/sample.pdf"
    assert persisted.files[0].openai_file_id is None
    assert persisted.files[0].upload_status == "not_uploaded"
    assert persisted.files[0].indexing_status == "not_started"


def test_remote_creation_failure_leaves_manifest_unchanged(
    tmp_path: Path,
) -> None:
    vdr, _ = make_case(tmp_path)
    client = make_client()
    client.vector_stores.create.side_effect = RuntimeError("remote failed")

    with pytest.raises(Exception):
        ensure_case_vector_store(client, vdr, allow_create=True)

    assert load_manifest(vdr).vector_store_id is None


def test_save_failure_after_creation_exposes_recovery_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vdr, _ = make_case(tmp_path)
    client = make_client()
    client.vector_stores.create.return_value = remote(
        "vs_recover", "VDR Assistant - Project Falcon"
    )
    save_error = ManifestPersistenceError("synthetic save failure")

    def fail_save(*args, **kwargs):
        raise save_error

    monkeypatch.setattr(
        "src.ingestion.case_vector_store.save_manifest",
        fail_save,
    )

    with pytest.raises(VectorStoreCreatedButNotPersistedError) as captured:
        ensure_case_vector_store(client, vdr, allow_create=True)

    error = captured.value
    assert error.vector_store_id == "vs_recover"
    assert error.vector_store_name == "VDR Assistant - Project Falcon"
    assert error.original_save_error is save_error
    assert error.manifest.vector_store_id == "vs_recover"
    assert load_manifest(vdr).vector_store_id is None
    assert not hasattr(client.vector_stores, "delete") or not (
        client.vector_stores.delete.called
    )


def test_connection_uncertainty_does_not_clear_existing_id(
    tmp_path: Path,
) -> None:
    vdr, _ = make_case(tmp_path, "vs_existing")
    client = make_client()
    client.vector_stores.retrieve.side_effect = VectorStoreConnectionError(
        "uncertain"
    )

    with pytest.raises(VectorStoreConnectionError):
        ensure_case_vector_store(client, vdr, allow_create=True)

    assert load_manifest(vdr).vector_store_id == "vs_existing"
    client.vector_stores.create.assert_not_called()
