from datetime import datetime, timezone

import pytest

from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.retrieval.citation_resolver import (
    format_vdr_breadcrumb,
    resolve_citations,
)
from src.schemas.citation import Citation


def record(
    file_id: str | None,
    relative_path: str,
    filename: str = "report.pdf",
) -> VDRFileRecord:
    return VDRFileRecord(
        relative_path=relative_path,
        filename=filename,
        extension=".pdf",
        size_bytes=100,
        classification_status="supported",
        classification_reason="test record",
        openai_file_id=file_id,
        upload_status="uploaded",
        indexing_status="completed",
    )


def manifest_with(*records: VDRFileRecord) -> VDRManifest:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return VDRManifest(
        case_name="Test Case",
        root_path="C:/private/local/VDR",
        vector_store_id="vs-test",
        created_at=now,
        updated_at=now,
        total_files=len(records),
        supported_files=len(records),
        unsupported_files=0,
        ignored_files=0,
        error_files=0,
        files=list(records),
    )


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        (
            r"01 Finance\Annual Reports\Report.pdf",
            "VDR → 01 Finance → Annual Reports → Report.pdf",
        ),
        (
            "01 Finance/Annual Reports/Report.pdf",
            "VDR → 01 Finance → Annual Reports → Report.pdf",
        ),
        ("Report.pdf", "VDR → Report.pdf"),
        ("  Folder/Report.pdf  ", "VDR → Folder → Report.pdf"),
    ],
)
def test_format_vdr_breadcrumb(relative_path: str, expected: str) -> None:
    assert format_vdr_breadcrumb(relative_path) == expected


@pytest.mark.parametrize(
    "relative_path",
    [
        None,
        "",
        "   ",
        "/private/VDR/Report.pdf",
        "C:/private/VDR/Report.pdf",
        r"C:\private\VDR\Report.pdf",
        r"C:relative\Report.pdf",
        r"\\server\share\Report.pdf",
        r"\Finance\Report.pdf",
        "Finance/./Report.pdf",
        "Finance/../Report.pdf",
        "../Report.pdf",
        "Finance//Report.pdf",
        "/",
        "\\\\",
    ],
)
def test_format_vdr_breadcrumb_rejects_unsafe_paths(
    relative_path: str | None,
) -> None:
    assert format_vdr_breadcrumb(relative_path) is None


def test_file_id_resolves_to_manifest_relative_path() -> None:
    manifest = manifest_with(
        record("file-A", "01 Finance/Annual Reports/Report.pdf")
    )

    assert resolve_citations(
        [Citation(file_id="file-A", filename="Report.pdf")],
        manifest,
    ) == ["VDR → 01 Finance → Annual Reports → Report.pdf"]


def test_duplicate_filenames_resolve_independently_by_file_id() -> None:
    manifest = manifest_with(
        record("file-A", "Folder A/report.pdf"),
        record("file-B", "Folder B/report.pdf"),
    )
    citations = [
        Citation(file_id="file-B", filename="report.pdf"),
        Citation(file_id="file-A", filename="report.pdf"),
    ]

    assert resolve_citations(citations, manifest) == [
        "VDR → Folder B → report.pdf",
        "VDR → Folder A → report.pdf",
    ]


def test_missing_manifest_falls_back_to_filename() -> None:
    assert resolve_citations(
        [Citation(file_id="file-A", filename="report.pdf")],
        None,
    ) == ["report.pdf"]


def test_unmatched_file_id_falls_back_to_filename() -> None:
    manifest = manifest_with(record("file-other", "Folder/report.pdf"))

    assert resolve_citations(
        [Citation(file_id="file-A", filename="report.pdf")],
        manifest,
    ) == ["report.pdf"]


@pytest.mark.parametrize("relative_path", ["", "../report.pdf", "C:/report.pdf"])
def test_invalid_manifest_path_falls_back_to_filename(
    relative_path: str,
) -> None:
    manifest = manifest_with(record("file-A", relative_path))

    assert resolve_citations(
        [Citation(file_id="file-A", filename="report.pdf")],
        manifest,
    ) == ["report.pdf"]


def test_duplicate_manifest_file_id_is_ambiguous() -> None:
    manifest = manifest_with(
        record("file-A", "Folder A/report.pdf"),
        record("file-A", "Folder B/report.pdf"),
    )

    assert resolve_citations(
        [Citation(file_id="file-A", filename="report.pdf")],
        manifest,
    ) == ["report.pdf"]


def test_missing_filename_uses_neutral_source_label() -> None:
    assert resolve_citations(
        [Citation(file_id="file-A", filename="  ")],
        None,
    ) == ["Unknown source"]
