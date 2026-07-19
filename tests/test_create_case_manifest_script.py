from pathlib import Path

from scripts import create_case_manifest as script
from src.ingestion.manifest_persistence import (
    derive_manifest_paths,
    load_manifest,
)


def make_vdr(tmp_path: Path) -> Path:
    vdr_folder = tmp_path / "Industry" / "Project Falcon" / "VDR"
    vdr_folder.mkdir(parents=True)
    (vdr_folder / "sample.pdf").write_bytes(b"sample")
    return vdr_folder


def provide_inputs(monkeypatch, *responses: str) -> None:
    answers = iter(responses)
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))


def test_exact_create_confirmation_creates_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_vdr(tmp_path)
    provide_inputs(monkeypatch, str(vdr_folder), "CREATE")

    result = script.main()

    paths = derive_manifest_paths(vdr_folder)
    assert result == 0
    assert paths.manifest_path.is_file()
    assert load_manifest(vdr_folder).case_name == "Project Falcon"


def test_incorrect_confirmation_aborts_without_creating_folder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_vdr(tmp_path)
    paths = derive_manifest_paths(vdr_folder)
    provide_inputs(monkeypatch, str(vdr_folder), "yes")

    result = script.main()

    assert result == 2
    assert not paths.assistant_folder.exists()
    assert not paths.manifest_path.exists()


def test_manifest_does_not_exist_when_confirmation_is_requested(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_vdr(tmp_path)
    paths = derive_manifest_paths(vdr_folder)
    prompts = []

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        if len(prompts) == 1:
            return str(vdr_folder)
        assert not paths.assistant_folder.exists()
        assert not paths.manifest_path.exists()
        return "CREATE"

    monkeypatch.setattr("builtins.input", answer)

    assert script.main() == 0
    assert paths.manifest_path.is_file()


def test_existing_manifest_is_not_overwritten(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_vdr(tmp_path)
    provide_inputs(monkeypatch, str(vdr_folder), "CREATE")
    assert script.main() == 0

    paths = derive_manifest_paths(vdr_folder)
    original_content = paths.manifest_path.read_text(encoding="utf-8")
    provide_inputs(monkeypatch, str(vdr_folder))

    assert script.main() == 1
    assert paths.manifest_path.read_text(encoding="utf-8") == original_content
    assert not paths.backup_path.exists()


def test_quoted_windows_path_input_is_normalized() -> None:
    raw_path = '  "C:\\Deals\\Project Falcon\\VDR"  '

    assert (
        script.normalize_vdr_folder_input(raw_path)
        == "C:\\Deals\\Project Falcon\\VDR"
    )
