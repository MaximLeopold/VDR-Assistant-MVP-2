from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pytest

from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestJSONError,
    ManifestNotFoundError,
    ManifestPathError,
    ManifestPersistenceError,
    ManifestSchemaError,
    UnsupportedSchemaVersionError,
    create_manifest,
    derive_manifest_paths,
    load_backup_manifest,
    load_manifest,
    relink_manifest,
    save_manifest,
)


def make_case(tmp_path: Path) -> tuple[Path, Path]:
    project_folder = tmp_path / "Industry" / "Project Gamma"
    vdr_folder = project_folder / "Seller Export"
    vdr_folder.mkdir(parents=True)
    return project_folder, vdr_folder


def make_manifest(vdr_folder: Path) -> VDRManifest:
    created_at = datetime(2026, 1, 2, 10, 30, tzinfo=timezone.utc)
    record = VDRFileRecord(
        absolute_path=str(vdr_folder / "Legal" / "agreement.pdf"),
        relative_path="Legal/agreement.pdf",
        filename="agreement.pdf",
        extension=".pdf",
        size_bytes=123,
        classification_status="supported",
        classification_reason="Supported file type",
        openai_file_id="file_123",
        upload_status="failed",
        indexing_status="in_progress",
        upload_attempts=2,
        last_error="Temporary upload error",
    )
    return VDRManifest(
        schema_version=2,
        case_name="Project Gamma",
        root_path=str(vdr_folder),
        vector_store_id="vs_123",
        created_at=created_at,
        updated_at=created_at,
        total_files=1,
        supported_files=1,
        unsupported_files=0,
        ignored_files=0,
        error_files=0,
        files=[record],
    )


def write_manifest_data(path: Path, manifest: VDRManifest, **updates) -> None:
    data = manifest.model_dump(mode="json")
    data.update(updates)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_derive_manifest_paths_for_any_selected_folder_name(
    tmp_path: Path,
) -> None:
    project_folder, vdr_folder = make_case(tmp_path)

    paths = derive_manifest_paths(vdr_folder)

    assert paths.vdr_folder == vdr_folder.resolve()
    assert paths.project_folder == project_folder.resolve()
    assert paths.assistant_folder == project_folder / "VDR Assistant"
    assert paths.manifest_path == paths.assistant_folder / "manifest.json"
    assert paths.backup_path == (
        paths.assistant_folder / "manifest.backup.json"
    )
    assert not paths.assistant_folder.exists()


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_derive_manifest_paths_rejects_invalid_root(
    tmp_path: Path,
    kind: str,
) -> None:
    selected_path = tmp_path / kind
    if kind == "file":
        selected_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ManifestPathError):
        derive_manifest_paths(selected_path)


def test_create_manifest_creates_current_only_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    _, vdr_folder = make_case(tmp_path)
    manifest = make_manifest(vdr_folder)

    manifest_path = create_manifest(manifest, vdr_folder)
    paths = derive_manifest_paths(vdr_folder)

    assert manifest_path == paths.manifest_path
    assert paths.assistant_folder.is_dir()
    assert paths.manifest_path.is_file()
    assert not paths.backup_path.exists()
    assert "\n  \"schema_version\"" in paths.manifest_path.read_text(
        encoding="utf-8"
    )

    with pytest.raises(ManifestPersistenceError, match="already exists"):
        create_manifest(manifest, vdr_folder)


def test_save_load_round_trip_is_portable_and_preserves_state(
    tmp_path: Path,
) -> None:
    _, vdr_folder = make_case(tmp_path)
    manifest = make_manifest(vdr_folder)
    original_created_at = manifest.created_at
    original_updated_at = manifest.updated_at

    save_manifest(manifest, vdr_folder)
    paths = derive_manifest_paths(vdr_folder)
    persisted = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    loaded = load_manifest(vdr_folder)

    assert "absolute_path" not in persisted["files"][0]
    assert "absolute_path" not in loaded.files[0].model_dump()
    assert loaded.files[0].relative_path == "Legal/agreement.pdf"
    assert loaded.files[0].openai_file_id == "file_123"
    assert loaded.files[0].upload_status == "failed"
    assert loaded.files[0].indexing_status == "in_progress"
    assert loaded.files[0].upload_attempts == 2
    assert loaded.files[0].last_error == "Temporary upload error"
    assert loaded.vector_store_id == "vs_123"
    assert loaded.created_at == original_created_at
    assert loaded.updated_at == manifest.updated_at
    assert loaded.updated_at > original_updated_at
    assert not paths.backup_path.exists()


def test_backup_rotation_keeps_only_the_previous_current_state(
    tmp_path: Path,
) -> None:
    _, vdr_folder = make_case(tmp_path)
    manifest = make_manifest(vdr_folder)

    create_manifest(manifest, vdr_folder)
    manifest.files[0].last_error = "second"
    save_manifest(manifest, vdr_folder)

    first_backup = load_backup_manifest(vdr_folder)
    assert first_backup.files[0].last_error == "Temporary upload error"

    manifest.files[0].last_error = "third"
    save_manifest(manifest, vdr_folder)

    paths = derive_manifest_paths(vdr_folder)
    second_backup = load_backup_manifest(vdr_folder)
    current = load_manifest(vdr_folder)

    assert second_backup.files[0].last_error == "second"
    assert current.files[0].last_error == "third"
    assert sorted(path.name for path in paths.assistant_folder.iterdir()) == [
        "manifest.backup.json",
        "manifest.json",
    ]


def test_load_errors_distinguish_missing_json_schema_and_version(
    tmp_path: Path,
) -> None:
    _, vdr_folder = make_case(tmp_path)
    paths = derive_manifest_paths(vdr_folder)

    with pytest.raises(ManifestNotFoundError, match="Current"):
        load_manifest(vdr_folder)
    with pytest.raises(ManifestNotFoundError, match="Backup"):
        load_backup_manifest(vdr_folder)

    paths.assistant_folder.mkdir()
    paths.manifest_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ManifestJSONError):
        load_manifest(vdr_folder)

    manifest = make_manifest(vdr_folder)
    write_manifest_data(paths.manifest_path, manifest, schema_version=1)
    with pytest.raises(UnsupportedSchemaVersionError):
        load_manifest(vdr_folder)

    data = manifest.model_dump(mode="json")
    data["files"][0]["upload_status"] = "invalid"
    paths.manifest_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ManifestSchemaError):
        load_manifest(vdr_folder)


def test_load_ignores_unavailable_stored_root_without_changing_timestamps(
    tmp_path: Path,
) -> None:
    _, vdr_folder = make_case(tmp_path)
    manifest = make_manifest(vdr_folder)
    path=create_manifest(manifest,vdr_folder)
    manifest.root_path = "Z:/another-users-sync/Project Gamma/Seller Export"
    # Simulate a copied portable snapshot; loading does not require the stored root.
    write_manifest_data(path,manifest)
    loaded = load_manifest(vdr_folder)

    assert loaded.root_path == manifest.root_path
    assert loaded.created_at == manifest.created_at
    assert loaded.updated_at == manifest.updated_at


def test_read_permission_error_is_wrapped_clearly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, vdr_folder = make_case(tmp_path)
    manifest = make_manifest(vdr_folder)
    create_manifest(manifest, vdr_folder)

    def deny_read(self: Path, *args, **kwargs) -> str:
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "read_text", deny_read)

    with pytest.raises(ManifestPersistenceError, match="Could not read"):
        load_manifest(vdr_folder)


def test_failed_current_replacement_preserves_current_and_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, vdr_folder = make_case(tmp_path)
    manifest = make_manifest(vdr_folder)
    create_manifest(manifest, vdr_folder)
    paths = derive_manifest_paths(vdr_folder)
    original_json = paths.manifest_path.read_text(encoding="utf-8")
    original_updated_at = manifest.updated_at
    real_replace = os.replace

    def fail_current_replace(source, destination) -> None:
        if Path(destination) == paths.manifest_path:
            raise PermissionError("replacement denied")
        real_replace(source, destination)

    monkeypatch.setattr(
        "src.ingestion.manifest_persistence.os.replace",
        fail_current_replace,
    )

    with pytest.raises(ManifestPersistenceError, match="Could not save"):
        save_manifest(manifest, vdr_folder)

    assert paths.manifest_path.read_text(encoding="utf-8") == original_json
    assert manifest.updated_at == original_updated_at
    assert not list(paths.assistant_folder.glob("*.tmp"))


def test_relink_reconstructs_paths_without_requiring_files(
    tmp_path: Path,
) -> None:
    _, original_vdr = make_case(tmp_path / "original")
    manifest = make_manifest(original_vdr)
    create_manifest(manifest, original_vdr)
    loaded = load_manifest(original_vdr)

    _, new_vdr = make_case(tmp_path / "new-machine")
    relinked = relink_manifest(loaded, new_vdr)

    assert "absolute_path" not in loaded.files[0].model_dump()
    assert relinked.root_path == str(new_vdr.resolve())
    assert "absolute_path" not in relinked.files[0].model_dump()
    assert relinked.files[0].relative_path == "Legal/agreement.pdf"
    assert relinked.files[0].openai_file_id == "file_123"
    assert not (new_vdr / relinked.files[0].relative_path).exists()


def test_relink_rejects_invalid_root_and_path_traversal(
    tmp_path: Path,
) -> None:
    _, vdr_folder = make_case(tmp_path)
    manifest = make_manifest(vdr_folder)

    with pytest.raises(ManifestPathError):
        relink_manifest(manifest, tmp_path / "missing")

    manifest.files[0].relative_path = "../outside.pdf"
    with pytest.raises(ManifestPathError, match="escapes"):
        relink_manifest(manifest, vdr_folder)
