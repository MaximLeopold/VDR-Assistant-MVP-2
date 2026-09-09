import json
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from src.ingestion.manifest import VDRManifest, VDRFileRecord, ExcelPreprocessing
from src.ingestion.manifest_builder import build_manifest
from src.ingestion.manifest_persistence import (
    create_manifest,
    load_manifest,
    UnsupportedSchemaVersionError,
)


def test_v2_roundtrip(tmp_path):
    root = tmp_path / "VDR"
    root.mkdir()
    (root / "book.xlsx").write_bytes(b"fixture")
    (root / "memo.pdf").write_bytes(b"pdf")
    (root / "old.xls").write_bytes(b"xls")
    m = build_manifest(str(root))
    path = create_manifest(m, root)
    loaded = load_manifest(root)
    assert loaded == m
    assert (
        m.supported_files,
        m.preprocess_files,
        m.unsupported_files,
        m.total_files,
    ) == (1, 1, 1, 3)
    data = json.loads(path.read_text())
    assert (
        not {
            "total_files",
            "supported_files",
            "unsupported_files",
            "ignored_files",
            "error_files",
        }
        & data.keys()
    )
    assert all(
        "absolute_path" not in f and "checksum_sha256" not in f for f in data["files"]
    )


@pytest.mark.parametrize("version", [1, None, 3])
def test_reject_versions(tmp_path, version):
    root = tmp_path / "VDR"
    root.mkdir()
    m = build_manifest(str(root))
    p = create_manifest(m, root)
    data = m.model_dump(mode="json")
    data["schema_version"] = version
    if version is None:
        del data["schema_version"]
    p.write_text(json.dumps(data))
    with pytest.raises(UnsupportedSchemaVersionError, match="Recreate"):
        load_manifest(root)


@pytest.mark.parametrize("path", ["../a", "/a", "C:a", "C:/a", "a/../b", "a//b"])
def test_unsafe_paths(path):
    with pytest.raises(ValidationError):
        VDRFileRecord(
            relative_path=path,
            filename="a",
            extension=".pdf",
            size_bytes=1,
            classification_status="supported",
            classification_reason="test",
        )


def test_duplicate_paths(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"a")
    m = build_manifest(str(tmp_path))
    data = m.model_dump()
    data["files"] *= 2
    with pytest.raises(ValidationError, match="Duplicate"):
        VDRManifest.model_validate(data)


def test_exclusion_requires_reason():
    with pytest.raises(ValidationError):
        ExcelPreprocessing(status="excluded", exclusion_reason=" ")
