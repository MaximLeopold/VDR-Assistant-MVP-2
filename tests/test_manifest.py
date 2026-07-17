from pathlib import Path

import pytest
from pydantic import ValidationError

from src.ingestion.file_filter import classify_file
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.ingestion.manifest_builder import build_manifest


def make_file_record(**overrides) -> dict:
    values = {
        "absolute_path": "/tmp/vdr/document.pdf",
        "relative_path": "Legal/document.pdf",
        "filename": "document.pdf",
        "extension": ".pdf",
        "size_bytes": 10,
        "classification_status": "supported",
        "classification_reason": "Supported file type",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("filename", "extension", "size_bytes", "expected_status"),
    [
        ("document.pdf", ".pdf", 10, "supported"),
        ("archive.zip", ".zip", 10, "unsupported"),
        ("~$document.docx", ".docx", 10, "ignored"),
    ],
)
def test_classify_file_uses_renamed_fields(
    filename: str,
    extension: str,
    size_bytes: int,
    expected_status: str,
) -> None:
    classified = classify_file(
        {
            "filename": filename,
            "extension": extension,
            "size_bytes": size_bytes,
        }
    )

    assert classified["classification_status"] == expected_status
    assert classified["classification_reason"]
    assert "status" not in classified
    assert "reason" not in classified


def test_file_record_has_ingestion_defaults() -> None:
    record = VDRFileRecord(**make_file_record())

    assert record.checksum_sha256 is None
    assert record.openai_file_id is None
    assert record.upload_status == "not_uploaded"
    assert record.indexing_status == "not_started"
    assert record.upload_attempts == 0
    assert record.last_error is None


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("classification_status", "pending"),
        ("upload_status", "pending"),
        ("indexing_status", "pending"),
    ],
)
def test_file_record_rejects_invalid_status(
    field: str,
    invalid_value: str,
) -> None:
    values = make_file_record()
    values[field] = invalid_value

    with pytest.raises(ValidationError):
        VDRFileRecord(**values)


def test_manifest_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    manifest = build_manifest(str(tmp_path))

    assert manifest.schema_version == 1

    values = manifest.model_dump()
    values["schema_version"] = 2

    with pytest.raises(ValidationError):
        VDRManifest.model_validate(values)


def test_build_manifest_counts_classifications_and_preserves_nested_path(
    tmp_path: Path,
) -> None:
    nested_folder = tmp_path / "Legal" / "Contracts"
    nested_folder.mkdir(parents=True)
    (nested_folder / "agreement.pdf").write_bytes(b"pdf")
    (tmp_path / "archive.zip").write_bytes(b"zip")
    (tmp_path / "~$draft.docx").write_bytes(b"temporary")

    manifest = build_manifest(str(tmp_path))

    assert manifest.total_files == 3
    assert manifest.supported_files == 1
    assert manifest.unsupported_files == 1
    assert manifest.ignored_files == 1
    assert manifest.error_files == 0
    assert (
        manifest.supported_files
        + manifest.unsupported_files
        + manifest.ignored_files
        + manifest.error_files
        == manifest.total_files
    )
    assert manifest.case_name == tmp_path.parent.name
    assert manifest.root_path == str(tmp_path.resolve())
    assert manifest.vector_store_id is None
    assert manifest.created_at == manifest.updated_at
    assert manifest.created_at.tzinfo is not None

    supported_file = next(
        file
        for file in manifest.files
        if file.classification_status == "supported"
    )
    assert supported_file.relative_path == "Legal/Contracts/agreement.pdf"


def test_builder_counts_error_classifications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanned_file = {
        "absolute_path": str(tmp_path / "broken.pdf"),
        "relative_path": "broken.pdf",
        "filename": "broken.pdf",
        "extension": ".pdf",
        "size_bytes": 10,
    }
    classified_file = {
        **scanned_file,
        "classification_status": "error",
        "classification_reason": "Classification failed",
    }

    monkeypatch.setattr(
        "src.ingestion.manifest_builder.scan_vdr_folder",
        lambda folder_path: [scanned_file],
    )
    monkeypatch.setattr(
        "src.ingestion.manifest_builder.classify_files",
        lambda files: [classified_file],
    )

    manifest = build_manifest(str(tmp_path))

    assert manifest.total_files == 1
    assert manifest.error_files == 1
    assert manifest.supported_files == 0
    assert manifest.unsupported_files == 0
    assert manifest.ignored_files == 0
