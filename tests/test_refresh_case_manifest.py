from pathlib import Path
from unittest.mock import Mock

from scripts import refresh_case_manifest as script
from src.ingestion.manifest_builder import build_manifest
from src.ingestion.manifest_persistence import (
    create_manifest,
    load_manifest,
    save_manifest,
)


def make_case(tmp_path: Path) -> Path:
    vdr_folder = tmp_path / "Industry" / "Project Falcon" / "VDR"
    vdr_folder.mkdir(parents=True)
    (vdr_folder / "existing.pdf").write_bytes(b"original")
    manifest = build_manifest(str(vdr_folder))
    manifest.vector_store_id = "vs_synthetic"
    manifest.files[0].openai_file_id = "file_existing"
    manifest.files[0].upload_status = "uploaded"
    manifest.files[0].indexing_status = "completed"
    manifest.files[0].upload_attempts = 2
    manifest.files[0].last_error = "historical note"
    manifest.files[0].checksum_sha256 = "synthetic-checksum"
    create_manifest(manifest, vdr_folder)
    return vdr_folder


def provide_inputs(monkeypatch, *responses: str) -> None:
    answers = iter(responses)
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))


def test_new_nested_file_is_detected_and_appended(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    nested = vdr_folder / "Legal" / "Contracts"
    nested.mkdir(parents=True)
    (nested / "new-agreement.pdf").write_bytes(b"new")
    provide_inputs(monkeypatch, str(vdr_folder), "REFRESH")

    assert script.main() == 0

    refreshed = load_manifest(vdr_folder)
    added = next(
        record
        for record in refreshed.files
        if record.relative_path == "Legal/Contracts/new-agreement.pdf"
    )
    assert added.openai_file_id is None
    assert added.upload_status == "not_uploaded"
    assert added.indexing_status == "not_started"
    assert added.upload_attempts == 0
    assert added.last_error is None
    assert added.checksum_sha256 is None


def test_existing_record_is_preserved_when_local_file_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    before = load_manifest(vdr_folder).files[0].model_dump()
    (vdr_folder / "existing.pdf").write_bytes(b"changed and larger")
    (vdr_folder / "new.pdf").write_bytes(b"new")
    provide_inputs(monkeypatch, str(vdr_folder), "REFRESH")

    assert script.main() == 0

    after = load_manifest(vdr_folder).files[0].model_dump()
    assert after == before


def test_removed_historical_record_remains_in_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    (vdr_folder / "existing.pdf").unlink()
    (vdr_folder / "replacement.pdf").write_bytes(b"replacement")
    provide_inputs(monkeypatch, str(vdr_folder), "REFRESH")

    assert script.main() == 0

    refreshed = load_manifest(vdr_folder)
    assert {record.relative_path for record in refreshed.files} == {
        "existing.pdf",
        "replacement.pdf",
    }


def test_incorrect_confirmation_aborts_without_saving(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    (vdr_folder / "new.pdf").write_bytes(b"new")
    before = load_manifest(vdr_folder).model_dump()
    save = Mock()
    monkeypatch.setattr(script, "save_manifest", save)
    provide_inputs(monkeypatch, str(vdr_folder), "yes")

    assert script.main() == 2
    save.assert_not_called()
    assert load_manifest(vdr_folder).model_dump() == before


def test_exact_refresh_appends_only_new_records_and_saves_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    (vdr_folder / "new.pdf").write_bytes(b"new")
    real_save = save_manifest
    save = Mock(side_effect=real_save)
    monkeypatch.setattr(script, "save_manifest", save)
    provide_inputs(monkeypatch, str(vdr_folder), "REFRESH")

    assert script.main() == 0

    save.assert_called_once()
    refreshed = load_manifest(vdr_folder)
    assert [record.relative_path for record in refreshed.files] == [
        "existing.pdf",
        "new.pdf",
    ]
    assert refreshed.vector_store_id == "vs_synthetic"


def test_no_new_files_skips_confirmation_and_save(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    save = Mock()
    monkeypatch.setattr(script, "save_manifest", save)
    prompts = []

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        if len(prompts) > 1:
            raise AssertionError("confirmation must not be requested")
        return str(vdr_folder)

    monkeypatch.setattr("builtins.input", answer)

    assert script.main() == 0
    assert len(prompts) == 1
    save.assert_not_called()


def test_counters_increment_only_for_appended_records(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_case(tmp_path)
    (vdr_folder / "supported.pdf").write_bytes(b"supported")
    (vdr_folder / "unsupported.zip").write_bytes(b"unsupported")
    (vdr_folder / "~$temporary.docx").write_bytes(b"ignored")
    provide_inputs(monkeypatch, str(vdr_folder), "REFRESH")

    assert script.main() == 0

    refreshed = load_manifest(vdr_folder)
    assert refreshed.total_files == 4
    assert refreshed.supported_files == 2
    assert refreshed.unsupported_files == 1
    assert refreshed.ignored_files == 1
    assert refreshed.error_files == 0


def test_quoted_folder_input_is_normalized() -> None:
    raw_path = '  "C:\\Deals\\Project Falcon\\VDR"  '

    assert (
        script.normalize_vdr_folder_input(raw_path)
        == "C:\\Deals\\Project Falcon\\VDR"
    )
