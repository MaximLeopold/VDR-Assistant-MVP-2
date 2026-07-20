from datetime import datetime, timezone
from pathlib import Path

from src.config import settings
from src.ingestion import active_manifest
from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestJSONError,
    create_manifest,
)


def manifest(vector_store_id: str | None = "vs-test") -> VDRManifest:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return VDRManifest(
        case_name="Test Case",
        vector_store_id=vector_store_id,
        created_at=now,
        updated_at=now,
        total_files=0,
        supported_files=0,
        unsupported_files=0,
        ignored_files=0,
        error_files=0,
        files=[],
    )


def create_case(tmp_path: Path, vector_store_id: str = "vs-test") -> Path:
    project = tmp_path / "Project"
    vdr_folder = project / "VDR"
    vdr_folder.mkdir(parents=True)
    create_manifest(manifest(vector_store_id), vdr_folder)
    return vdr_folder


def test_matching_vector_store_id_allows_manifest(tmp_path: Path) -> None:
    vdr_folder = create_case(tmp_path)

    selected = active_manifest.load_active_manifest(vdr_folder, " vs-test ")

    assert selected is not None
    assert selected.vector_store_id == "vs-test"


def test_mismatched_vector_store_id_rejects_manifest(tmp_path: Path) -> None:
    vdr_folder = create_case(tmp_path)

    assert active_manifest.load_active_manifest(vdr_folder, "vs-other") is None


def test_missing_vdr_folder_skips_manifest_loading(monkeypatch) -> None:
    def unexpected_load(path):
        raise AssertionError("manifest loading should have been skipped")

    monkeypatch.setattr(active_manifest, "load_manifest", unexpected_load)

    assert active_manifest.load_active_manifest(None, "vs-test") is None
    assert active_manifest.load_active_manifest("   ", "vs-test") is None


def test_missing_or_invalid_manifest_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert active_manifest.load_active_manifest(missing, "vs-test") is None


def test_expected_manifest_loading_failure_returns_none(
    monkeypatch,
) -> None:
    def fail_load(path):
        raise ManifestJSONError("synthetic invalid manifest")

    monkeypatch.setattr(active_manifest, "load_manifest", fail_load)

    assert active_manifest.load_active_manifest("configured", "vs-test") is None


def test_filesystem_manifest_loading_failure_returns_none(monkeypatch) -> None:
    def fail_load(path):
        raise PermissionError("synthetic access denial")

    monkeypatch.setattr(active_manifest, "load_manifest", fail_load)

    assert active_manifest.load_active_manifest("configured", "vs-test") is None


def test_manifest_without_vector_store_id_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(
        active_manifest,
        "load_manifest",
        lambda path: manifest(vector_store_id=None),
    )

    assert active_manifest.load_active_manifest("configured", "vs-test") is None


def test_vdr_folder_is_not_a_required_setting(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "VECTOR_STORE_ID", "vs-test")
    monkeypatch.setattr(settings, "VDR_FOLDER", None)

    assert settings.validate_settings() == []
