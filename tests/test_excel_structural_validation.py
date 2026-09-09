from datetime import datetime, timezone
import copy
from pathlib import Path
import os
import subprocess
import pytest
from pydantic import ValidationError
from src.ingestion.manifest import VDRManifest
from src.ingestion.paths import managed_path
from src.ingestion.manifest_persistence import derive_manifest_paths, ManifestPathError


def completed_data():
    return dict(
        schema_version=2,
        case_name="Fixture",
        root_path="C:/fixture/VDR",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        files=[
            dict(
                relative_path="book.xlsx",
                filename="book.xlsx",
                extension=".xlsx",
                size_bytes=100,
                classification_status="preprocess",
                classification_reason="Excel",
                excel_preprocessing=dict(
                    status="completed",
                    source_sha256="a" * 64,
                    transformation_version="excel_proxy_v1",
                    generation_id="b" * 64,
                    worksheets=[
                        dict(
                            worksheet_name="Revenue",
                            worksheet_index=1,
                            outcome="included",
                            reason="Visible",
                        )
                    ],
                ),
                derived_artifacts=[
                    dict(
                        artifact_id="c" * 64,
                        worksheet_name="Revenue",
                        worksheet_index=1,
                        proxy_relative_path="derived/excel/"
                        + ("b" * 64)
                        + "/sheet_001.md",
                        size_bytes=30,
                        artifact_sha256="d" * 64,
                    )
                ],
            )
        ],
    )


@pytest.mark.parametrize(
    "defect",
    [
        "missing_artifact",
        "duplicate_artifact",
        "wrong_sheet",
        "wrong_index",
        "excluded_with_artifact",
        "duplicate_coverage",
        "wrong_generation_path",
        "attempt_path",
        "direct_artifact",
        "incomplete_artifact",
        "excluded_artifact",
        "parent_id",
        "parent_upload",
        "parent_indexing",
        "parent_attempts",
        "duplicate_remote_ids",
        "duplicate_artifact_ids",
    ],
)
def test_structural_validation_without_source_access(defect, monkeypatch):
    data = completed_data()
    record = data["files"][0]
    artifact = record["derived_artifacts"][0]
    prep = record["excel_preprocessing"]
    if defect == "missing_artifact":
        record["derived_artifacts"] = []
    elif defect == "duplicate_artifact":
        record["derived_artifacts"].append(copy.deepcopy(artifact))
    elif defect == "wrong_sheet":
        artifact["worksheet_name"] = "Wrong"
    elif defect == "wrong_index":
        artifact["worksheet_index"] = 2
    elif defect == "excluded_with_artifact":
        prep["worksheets"][0]["outcome"] = "excluded"
    elif defect == "duplicate_coverage":
        prep["worksheets"].append(copy.deepcopy(prep["worksheets"][0]))
    elif defect == "wrong_generation_path":
        artifact["proxy_relative_path"] = "derived/excel/wrong/sheet_001.md"
    elif defect == "attempt_path":
        artifact["proxy_relative_path"] = "derived/excel/.attempts/a/sheet_001.md"
    elif defect == "direct_artifact":
        record["classification_status"] = "supported"
    elif defect == "incomplete_artifact":
        prep["status"] = "processing"
    elif defect == "excluded_artifact":
        prep.update(status="excluded", exclusion_reason="reason")
    elif defect == "parent_id":
        record["openai_file_id"] = "file_parent"
    elif defect == "parent_upload":
        record["upload_status"] = "uploading"
    elif defect == "parent_indexing":
        record["indexing_status"] = "in_progress"
    elif defect == "parent_attempts":
        record["upload_attempts"] = 1
    else:
        second = copy.deepcopy(record)
        second["relative_path"] = "Other/book.xlsx"
        data["files"].append(second)
        if defect == "duplicate_remote_ids":
            second["derived_artifacts"][0]["artifact_id"] = "e" * 64
            artifact["openai_file_id"] = second["derived_artifacts"][0][
                "openai_file_id"
            ] = "file_duplicate"
    monkeypatch.setattr(
        Path,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Structural validation must not read source files")
        ),
    )
    with pytest.raises(ValidationError):
        VDRManifest.model_validate(data)


def test_completed_model_is_valid_and_counts_are_derived():
    m = VDRManifest.model_validate(completed_data())
    assert m.preprocess_files == 1 and m.total_files == 1 and m.supported_files == 0
    assert VDRManifest.model_validate_json(m.model_dump_json()) == m


def junction(link, target):
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)


def test_resolved_junction_output_cannot_escape_to_raw(tmp_path):
    raw = tmp_path / "VDR"
    raw.mkdir()
    (raw / "source.txt").write_text("source")
    assistant = tmp_path / "VDR Assistant"
    assistant.mkdir()
    junction(assistant / "derived", raw)
    with pytest.raises(ValueError):
        managed_path(raw, assistant, "derived/proxy.md")
    assert sorted(p.name for p in raw.iterdir()) == ["source.txt"]
    assert (raw / "source.txt").read_text() == "source"


def test_assistant_junction_to_raw_is_rejected(tmp_path):
    raw = tmp_path / "VDR"
    raw.mkdir()
    junction(tmp_path / "VDR Assistant", raw)
    with pytest.raises(ManifestPathError):
        derive_manifest_paths(raw)
