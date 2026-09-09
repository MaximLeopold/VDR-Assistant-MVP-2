from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from src.config.case_registry import CaseRegistryError, load_case_registry
from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_persistence import create_manifest, derive_manifest_paths


def make_manifest(
    vdr_folder: Path,
    *,
    case_name: str = "Prepared Case",
    vector_store_id: str | None = "vs_prepared",
) -> VDRManifest:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return VDRManifest(
        schema_version=2,
        snapshot_state="sealed",
        case_name=case_name,
        root_path=str(vdr_folder.resolve()),
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


def make_case(
    root: Path,
    name: str,
    *,
    case_name: str | None = None,
    vector_store_id: str | None = None,
) -> Path:
    vdr_folder = root / name / "VDR"
    vdr_folder.mkdir(parents=True)
    create_manifest(
        make_manifest(
            vdr_folder,
            case_name=case_name or f"Prepared {name}",
            vector_store_id=vector_store_id or f"vs_{name.lower()}",
        ),
        vdr_folder,
    )
    return vdr_folder


def write_registry(path: Path, cases: list[dict]) -> None:
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")


def test_valid_registry_loads_two_manifest_owned_cases(tmp_path: Path) -> None:
    first = make_case(
        tmp_path,
        "First",
        case_name="Manifest First",
        vector_store_id="vs_first_manifest",
    )
    second = make_case(
        tmp_path,
        "Second",
        case_name="Manifest Second",
        vector_store_id="vs_second_manifest",
    )
    registry_path = tmp_path / "cases.json"
    write_registry(
        registry_path,
        [
            {"case_id": "first", "vdr_folder": str(first)},
            {"case_id": "second", "vdr_folder": str(second)},
        ],
    )

    cases = load_case_registry(registry_path)

    assert [case.case_id for case in cases] == ["first", "second"]
    assert [case.case_name for case in cases] == [
        "Manifest First",
        "Manifest Second",
    ]
    assert [case.vector_store_id for case in cases] == [
        "vs_first_manifest",
        "vs_second_manifest",
    ]
    assert all(case.is_ready for case in cases)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{broken", "malformed JSON"),
        (json.dumps({}), "required schema"),
        (json.dumps({"cases": [{}]}), "required schema"),
        (
            json.dumps({"cases": [{"case_id": "case-a"}]}),
            "required schema",
        ),
        (
            json.dumps({"cases": [{"case_id": "", "vdr_folder": "VDR"}]}),
            "required schema",
        ),
        (
            json.dumps(
                {
                    "cases": [
                        {
                            "case_id": "case-a",
                            "vdr_folder": "VDR",
                            "case_name": "Duplicated metadata",
                        }
                    ]
                }
            ),
            "required schema",
        ),
    ],
)
def test_invalid_registry_structure_is_blocked(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    registry_path = tmp_path / "cases.json"
    registry_path.write_text(content, encoding="utf-8")

    with pytest.raises(CaseRegistryError, match=message):
        load_case_registry(registry_path)


def test_missing_registry_is_blocked_without_exposing_path(tmp_path: Path) -> None:
    missing = tmp_path / "sensitive" / "cases.json"

    with pytest.raises(CaseRegistryError) as error:
        load_case_registry(missing)

    assert "could not be found" in str(error.value)
    assert str(missing) not in str(error.value)


def test_duplicate_case_id_is_blocked(tmp_path: Path) -> None:
    registry_path = tmp_path / "cases.json"
    write_registry(
        registry_path,
        [
            {"case_id": "duplicate", "vdr_folder": "First/VDR"},
            {"case_id": "duplicate", "vdr_folder": "Second/VDR"},
        ],
    )

    with pytest.raises(CaseRegistryError, match="duplicate case_id"):
        load_case_registry(registry_path)


def test_relative_vdr_folder_is_resolved_from_registry(tmp_path: Path) -> None:
    vdr_folder = make_case(tmp_path, "Relative")
    registry_folder = tmp_path / "config"
    registry_folder.mkdir()
    registry_path = registry_folder / "cases.json"
    relative_vdr = vdr_folder.relative_to(registry_folder.parent)
    write_registry(
        registry_path,
        [{"case_id": "relative", "vdr_folder": f"../{relative_vdr.as_posix()}"}],
    )

    prepared = load_case_registry(registry_path)[0]

    assert prepared.vdr_folder == vdr_folder.resolve()
    assert prepared.is_ready


def test_missing_vdr_folder_returns_blocked_case(tmp_path: Path) -> None:
    registry_path = tmp_path / "cases.json"
    write_registry(
        registry_path,
        [{"case_id": "missing-root", "vdr_folder": "missing/VDR"}],
    )

    prepared = load_case_registry(registry_path)[0]

    assert not prepared.is_ready
    assert prepared.display_name == "missing-root"
    assert prepared.error == "The configured VDR folder is unavailable."


def test_missing_manifest_returns_blocked_case(tmp_path: Path) -> None:
    vdr_folder = tmp_path / "No Manifest" / "VDR"
    vdr_folder.mkdir(parents=True)
    registry_path = tmp_path / "cases.json"
    write_registry(
        registry_path,
        [{"case_id": "missing-manifest", "vdr_folder": str(vdr_folder)}],
    )

    prepared = load_case_registry(registry_path)[0]

    assert not prepared.is_ready
    assert "manifest" in prepared.error.lower()


def test_malformed_manifest_returns_blocked_case(tmp_path: Path) -> None:
    vdr_folder = tmp_path / "Malformed" / "VDR"
    vdr_folder.mkdir(parents=True)
    paths = derive_manifest_paths(vdr_folder)
    paths.assistant_folder.mkdir()
    paths.manifest_path.write_text("{broken", encoding="utf-8")
    registry_path = tmp_path / "cases.json"
    write_registry(
        registry_path,
        [{"case_id": "malformed", "vdr_folder": str(vdr_folder)}],
    )

    prepared = load_case_registry(registry_path)[0]

    assert not prepared.is_ready
    assert prepared.manifest is None
    assert "invalid" in prepared.error.lower()


def test_blank_manifest_vector_store_id_returns_blocked_case(
    tmp_path: Path,
) -> None:
    vdr_folder = tmp_path / "Blank Vector" / "VDR"
    vdr_folder.mkdir(parents=True)
    create_manifest(
        make_manifest(vdr_folder, vector_store_id=None),
        vdr_folder,
    )
    registry_path = tmp_path / "cases.json"
    write_registry(
        registry_path,
        [{"case_id": "blank-vector", "vdr_folder": str(vdr_folder)}],
    )

    prepared = load_case_registry(registry_path)[0]

    assert not prepared.is_ready
    assert prepared.case_name == "Prepared Case"
    assert prepared.vector_store_id is None
    assert "vector-store ID" in prepared.error


def test_blank_manifest_case_name_returns_blocked_case(tmp_path: Path) -> None:
    vdr_folder = tmp_path / "Blank Name" / "VDR"
    vdr_folder.mkdir(parents=True)
    create_manifest(
        make_manifest(vdr_folder, case_name="   "),
        vdr_folder,
    )
    registry_path = tmp_path / "cases.json"
    write_registry(
        registry_path,
        [{"case_id": "blank-name", "vdr_folder": str(vdr_folder)}],
    )

    prepared = load_case_registry(registry_path)[0]

    assert not prepared.is_ready
    assert prepared.display_name == "blank-name"
    assert "case name" in prepared.error
