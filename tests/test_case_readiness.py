from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.ingestion.case_readiness import assess_case_readiness
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.ingestion.manifest_persistence import create_manifest


def make_record(
    relative_path: str = "document.pdf",
    *,
    classification_status: str = "supported",
    openai_file_id: str | None = "file_document",
    upload_status: str = "uploaded",
    indexing_status: str = "completed",
) -> VDRFileRecord:
    return VDRFileRecord(
        relative_path=relative_path,
        filename=Path(relative_path).name,
        extension=Path(relative_path).suffix or ".pdf",
        size_bytes=10,
        classification_status=classification_status,
        classification_reason="test",
        openai_file_id=openai_file_id,
        upload_status=upload_status,
        indexing_status=indexing_status,
    )


def create_case(
    tmp_path: Path,
    records: list[VDRFileRecord],
    *,
    case_name: str = "Readiness Case",
    vector_store_id: str | None = "vs_readiness",
    root_path: str | None = None,
) -> Path:
    vdr_folder = tmp_path / "Project" / "VDR"
    vdr_folder.mkdir(parents=True)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manifest = VDRManifest(
        schema_version=2,
        case_name=case_name,
        root_path=root_path or str(vdr_folder.resolve()),
        vector_store_id=vector_store_id,
        created_at=now,
        updated_at=now,
        total_files=999,
        supported_files=999,
        unsupported_files=999,
        ignored_files=999,
        error_files=999,
        files=records,
    )
    if root_path:
        original=manifest.root_path
        manifest.root_path=str(vdr_folder.resolve())
        path=create_manifest(manifest,vdr_folder)
        manifest.root_path=original
        path.write_text(manifest.model_dump_json(),encoding="utf-8")
    else:
        create_manifest(manifest, vdr_folder)
    return vdr_folder


def test_ready_counts_are_derived_from_records(tmp_path: Path) -> None:
    records = [
        make_record(),
        make_record(
            "spreadsheet.xlsx",
            classification_status="unsupported",
            openai_file_id=None,
            upload_status="not_uploaded",
            indexing_status="not_started",
        ),
        make_record(
            "temporary.tmp",
            classification_status="ignored",
            openai_file_id=None,
            upload_status="not_uploaded",
            indexing_status="not_started",
        ),
    ]
    vdr_folder = create_case(tmp_path, records)

    readiness = assess_case_readiness(vdr_folder)

    assert readiness.is_ready
    assert readiness.supported_count == 1
    assert readiness.completed_count == 1
    assert readiness.unuploaded_count == 0
    assert readiness.failed_count == 0
    assert readiness.classification_error_count == 0


@pytest.mark.parametrize(
    ("record", "expected_reason"),
    [
        (make_record(openai_file_id=None), "file ID"),
        (
            make_record(
                openai_file_id=None,
                upload_status="not_uploaded",
                indexing_status="not_started",
            ),
            "completed upload",
        ),
        (
            make_record(
                openai_file_id=None,
                upload_status="uploading",
                indexing_status="not_started",
            ),
            "completed upload",
        ),
        (
            make_record(indexing_status="not_started"),
            "completed indexing",
        ),
        (
            make_record(indexing_status="in_progress"),
            "completed indexing",
        ),
        (
            make_record(indexing_status="failed"),
            "completed indexing",
        ),
        (
            make_record(upload_status="failed", indexing_status="failed"),
            "completed upload",
        ),
    ],
)
def test_supported_incomplete_states_block_readiness(
    tmp_path: Path,
    record: VDRFileRecord,
    expected_reason: str,
) -> None:
    vdr_folder = create_case(tmp_path, [record])

    readiness = assess_case_readiness(vdr_folder)

    assert not readiness.is_ready
    assert any(expected_reason in reason for reason in readiness.blocking_reasons)


@pytest.mark.parametrize(
    ("case_name", "vector_store_id", "reason"),
    [
        ("   ", "vs_ready", "case name"),
        ("Ready", None, "vector-store ID"),
    ],
)
def test_manifest_metadata_blocks_readiness(
    tmp_path: Path,
    case_name: str,
    vector_store_id: str | None,
    reason: str,
) -> None:
    vdr_folder = create_case(
        tmp_path,
        [make_record()],
        case_name=case_name,
        vector_store_id=vector_store_id,
    )

    readiness = assess_case_readiness(vdr_folder)

    assert not readiness.is_ready
    assert any(reason in item for item in readiness.blocking_reasons)


def test_zero_supported_and_classification_error_block(tmp_path: Path) -> None:
    record = make_record(
        "broken.bin",
        classification_status="error",
        openai_file_id=None,
        upload_status="not_uploaded",
        indexing_status="not_started",
    )
    vdr_folder = create_case(tmp_path, [record])

    readiness = assess_case_readiness(vdr_folder)

    assert not readiness.is_ready
    assert readiness.supported_count == 0
    assert readiness.classification_error_count == 1
    assert any("searchable target" in reason for reason in readiness.blocking_reasons)
    assert any("classification" in reason for reason in readiness.blocking_reasons)


def test_invalid_folder_missing_manifest_and_folder_mismatch_are_blocked(
    tmp_path: Path,
) -> None:
    assert not assess_case_readiness(tmp_path / "missing").is_ready

    no_manifest = tmp_path / "No Manifest" / "VDR"
    no_manifest.mkdir(parents=True)
    assert not assess_case_readiness(no_manifest).is_ready

    mismatch = create_case(
        tmp_path / "mismatch",
        [make_record()],
        root_path=str((tmp_path / "another" / "VDR").resolve()),
    )
    readiness = assess_case_readiness(mismatch)
    assert not readiness.is_ready
    assert any("does not belong" in reason for reason in readiness.blocking_reasons)
