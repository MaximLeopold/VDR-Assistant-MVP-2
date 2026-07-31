from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from src.config import case_registry
from src.config.case_registry import (
    CaseRegistryError,
    load_case_registry,
    register_prepared_case,
)
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.ingestion.manifest_persistence import create_manifest


def make_case(
    root: Path,
    name: str,
    *,
    ready: bool = True,
) -> Path:
    vdr_folder = root / name / "VDR"
    vdr_folder.mkdir(parents=True)
    document = vdr_folder / "document.pdf"
    document.write_bytes(b"ready")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = VDRFileRecord(
        relative_path="document.pdf",
        filename="document.pdf",
        extension=".pdf",
        size_bytes=5,
        classification_status="supported",
        classification_reason="test",
        openai_file_id="file_ready" if ready else None,
        upload_status="uploaded" if ready else "not_uploaded",
        indexing_status="completed" if ready else "not_started",
    )
    manifest = VDRManifest(
        case_name=f"Case {name}",
        root_path=str(vdr_folder.resolve()),
        vector_store_id=f"vs_{name.lower()}",
        created_at=now,
        updated_at=now,
        total_files=1,
        supported_files=1,
        unsupported_files=0,
        ignored_files=0,
        error_files=0,
        files=[record],
    )
    create_manifest(manifest, vdr_folder)
    return vdr_folder


def registry_with_existing(tmp_path: Path) -> tuple[Path, Path]:
    existing = make_case(tmp_path, "Existing")
    registry_path = tmp_path / "cases.json"
    registry_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "existing",
                        "vdr_folder": str(existing),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return registry_path, existing


def test_registration_normalizes_id_and_writes_only_minimal_entry(
    tmp_path: Path,
) -> None:
    registry_path, _ = registry_with_existing(tmp_path)
    candidate = make_case(tmp_path, "Candidate")

    result = register_prepared_case(
        registry_path,
        "  CASE_02  ",
        candidate,
    )

    assert result.status == "registered"
    assert result.case_id == "case_02"
    stored = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = stored["cases"][-1]
    assert entry == {
        "case_id": "case_02",
        "vdr_folder": candidate.resolve().as_posix(),
    }
    assert Path(entry["vdr_folder"]).is_absolute()
    loaded = load_case_registry(registry_path)
    assert [case.case_id for case in loaded] == ["existing", "case_02"]
    assert loaded[-1].is_ready


def test_registration_requires_strict_readiness_and_valid_id(
    tmp_path: Path,
) -> None:
    registry_path, _ = registry_with_existing(tmp_path)
    incomplete = make_case(tmp_path, "Incomplete", ready=False)
    before = registry_path.read_bytes()

    with pytest.raises(CaseRegistryError, match="not ready"):
        register_prepared_case(registry_path, "case-02", incomplete)
    with pytest.raises(CaseRegistryError, match="1-64"):
        register_prepared_case(registry_path, "invalid case", incomplete)

    assert registry_path.read_bytes() == before


def test_duplicate_id_and_folder_are_rejected_case_insensitively(
    tmp_path: Path,
) -> None:
    registry_path, existing = registry_with_existing(tmp_path)
    candidate = make_case(tmp_path, "Candidate")

    with pytest.raises(CaseRegistryError, match="case ID"):
        register_prepared_case(registry_path, "EXISTING", candidate)
    with pytest.raises(CaseRegistryError, match="folder"):
        register_prepared_case(registry_path, "another", existing)


def test_identical_registration_is_idempotent(tmp_path: Path) -> None:
    registry_path, existing = registry_with_existing(tmp_path)
    before = registry_path.read_bytes()

    result = register_prepared_case(registry_path, "EXISTING", existing)

    assert result.status == "already_registered"
    assert registry_path.read_bytes() == before


def test_existing_relative_entry_remains_readable_after_registration(
    tmp_path: Path,
) -> None:
    existing = make_case(tmp_path, "Existing")
    candidate = make_case(tmp_path, "Candidate")
    config_folder = tmp_path / "config"
    config_folder.mkdir()
    registry_path = config_folder / "cases.json"
    relative = existing.relative_to(tmp_path)
    registry_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "existing",
                        "vdr_folder": f"../{relative.as_posix()}",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    register_prepared_case(registry_path, "candidate", candidate)

    loaded = load_case_registry(registry_path)
    assert loaded[0].vdr_folder == existing.resolve()
    stored = json.loads(registry_path.read_text(encoding="utf-8"))
    assert stored["cases"][0]["vdr_folder"].startswith("../")


def test_atomic_replace_failure_preserves_original_registry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path, _ = registry_with_existing(tmp_path)
    candidate = make_case(tmp_path, "Candidate")
    original = registry_path.read_bytes()
    real_replace = case_registry.os.replace

    def fail_registry_replace(source, destination):
        if Path(destination) == registry_path:
            raise OSError("synthetic replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(case_registry.os, "replace", fail_registry_replace)

    with pytest.raises(CaseRegistryError, match="replaced safely"):
        register_prepared_case(registry_path, "candidate", candidate)

    assert registry_path.read_bytes() == original


def test_temporary_write_failure_preserves_original_and_retry_succeeds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path, _ = registry_with_existing(tmp_path)
    candidate = make_case(tmp_path, "Candidate")
    original = registry_path.read_bytes()
    real_writer = case_registry._write_registry_temporary
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CaseRegistryError("synthetic temporary failure")
        return real_writer(*args, **kwargs)

    monkeypatch.setattr(case_registry, "_write_registry_temporary", fail_once)

    with pytest.raises(CaseRegistryError, match="synthetic"):
        register_prepared_case(registry_path, "candidate", candidate)
    assert registry_path.read_bytes() == original

    result = register_prepared_case(registry_path, "candidate", candidate)
    assert result.status == "registered"


def test_fsync_failure_preserves_original_registry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path, _ = registry_with_existing(tmp_path)
    candidate = make_case(tmp_path, "Candidate")
    original = registry_path.read_bytes()
    monkeypatch.setattr(
        case_registry.os,
        "fsync",
        lambda _file_descriptor: (_ for _ in ()).throw(
            OSError("synthetic fsync failure")
        ),
    )

    with pytest.raises(CaseRegistryError, match="written safely"):
        register_prepared_case(registry_path, "candidate", candidate)

    assert registry_path.read_bytes() == original


def test_case_insensitive_duplicates_in_existing_registry_are_rejected(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "cases.json"
    registry_path.write_text(
        json.dumps(
            {
                "cases": [
                    {"case_id": "Case-A", "vdr_folder": "First/VDR"},
                    {"case_id": "case-a", "vdr_folder": "Second/VDR"},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CaseRegistryError, match="duplicate case_id"):
        load_case_registry(registry_path)
