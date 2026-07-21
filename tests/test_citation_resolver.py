from datetime import datetime, timezone

import pytest

from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.retrieval.citation_resolver import (
    build_source_references,
    format_vdr_breadcrumb,
    resolve_citations,
)
from src.schemas.citation import Citation
from src.schemas.evidence import RetrievedSearchResult, SourceReference


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


def search_result(
    file_id: str | None,
    text: str | None,
    score: float | None = 0.75,
):
    return RetrievedSearchResult(
        file_id=file_id,
        filename="report.pdf",
        text=text,
        score=score,
    )


def test_build_source_references_matches_by_file_id_in_citation_order() -> None:
    citations = [
        Citation(file_id="file-B", filename="report.pdf"),
        Citation(file_id="file-A", filename="report.pdf"),
    ]
    source_files = ["VDR → Folder B → report.pdf", "VDR → Folder A → report.pdf"]
    results = [
        search_result("file-A", "A passage", 0.95),
        search_result("file-B", "B passage", 0.4),
    ]

    assert build_source_references(citations, source_files, results) == [
        SourceReference(
            file_id="file-B",
            display_name="VDR → Folder B → report.pdf",
            evidence=["B passage"],
        ),
        SourceReference(
            file_id="file-A",
            display_name="VDR → Folder A → report.pdf",
            evidence=["A passage"],
        ),
    ]


def test_uncited_results_are_omitted_and_cited_source_without_result_remains() -> None:
    sources = build_source_references(
        [Citation(file_id="file-A", filename="a.pdf")],
        ["a.pdf"],
        [search_result("file-uncited", "Unrelated")],
    )

    assert sources == [
        SourceReference(file_id="file-A", display_name="a.pdf", evidence=[])
    ]


def test_duplicate_filenames_with_different_ids_keep_separate_evidence() -> None:
    sources = build_source_references(
        [
            Citation(file_id="file-A", filename="report.pdf"),
            Citation(file_id="file-B", filename="report.pdf"),
        ],
        ["Folder A/report.pdf", "Folder B/report.pdf"],
        [
            search_result("file-B", "B passage"),
            search_result("file-A", "A passage"),
        ],
    )

    assert [source.evidence for source in sources] == [
        ["A passage"],
        ["B passage"],
    ]


def test_passages_retain_raw_text_and_deduplicate_by_stripped_key() -> None:
    passages = [
        " First passage \nwith a second line ",
        "First passage \nwith a second line",
        "Second passage",
        "Third passage",
        "Fourth passage",
        None,
        "   ",
    ]
    sources = build_source_references(
        [Citation(file_id="file-A", filename="report.pdf")],
        ["report.pdf"],
        [search_result("file-A", passage) for passage in passages],
    )

    assert sources[0].evidence == [
        " First passage \nwith a second line ",
        "Second passage",
        "Third passage",
        "Fourth passage",
    ]


def test_higher_scores_rank_before_lower_scores() -> None:
    sources = build_source_references(
        [Citation(file_id="file-A", filename="report.pdf")],
        ["report.pdf"],
        [
            search_result("file-A", "Low score", 0.2),
            search_result("file-A", "High score", 0.9),
            search_result("file-A", "Middle score", 0.5),
        ],
    )

    assert sources[0].evidence == [
        "High score",
        "Middle score",
        "Low score",
    ]


def test_equal_scores_preserve_original_retrieval_order() -> None:
    sources = build_source_references(
        [Citation(file_id="file-A", filename="report.pdf")],
        ["report.pdf"],
        [
            search_result("file-A", "First equal", 0.8),
            search_result("file-A", "Second equal", 0.8),
        ],
    )

    assert sources[0].evidence == ["First equal", "Second equal"]


def test_missing_scores_follow_numeric_scores_in_retrieval_order() -> None:
    sources = build_source_references(
        [Citation(file_id="file-A", filename="report.pdf")],
        ["report.pdf"],
        [
            search_result("file-A", "First unscored", None),
            search_result("file-A", "Lower scored", 0.3),
            search_result("file-A", "Second unscored", None),
            search_result("file-A", "Higher scored", 0.7),
        ],
    )

    assert sources[0].evidence == [
        "Higher scored",
        "Lower scored",
        "First unscored",
        "Second unscored",
    ]


def test_duplicate_text_keeps_highest_ranked_occurrence() -> None:
    sources = build_source_references(
        [Citation(file_id="file-A", filename="report.pdf")],
        ["report.pdf"],
        [
            search_result("file-A", " Duplicate passage ", 0.1),
            search_result("file-A", "Middle passage", 0.5),
            search_result("file-A", "Duplicate passage", 0.9),
        ],
    )

    assert sources[0].evidence == [
        "Duplicate passage",
        "Middle passage",
    ]


def test_highest_ranked_duplicate_retains_its_original_raw_text() -> None:
    sources = build_source_references(
        [Citation(file_id="file-A", filename="report.pdf")],
        ["report.pdf"],
        [
            search_result("file-A", " Duplicate passage ", 0.1),
            search_result("file-A", "\tDuplicate passage\r\n", 0.9),
        ],
    )

    assert sources[0].evidence == ["\tDuplicate passage\r\n"]


def test_identical_text_under_different_file_ids_is_preserved() -> None:
    sources = build_source_references(
        [
            Citation(file_id="file-A", filename="a.pdf"),
            Citation(file_id="file-B", filename="b.pdf"),
        ],
        ["a.pdf", "b.pdf"],
        [
            search_result("file-A", "Same passage"),
            search_result("file-B", "Same passage"),
        ],
    )

    assert [source.evidence for source in sources] == [
        ["Same passage"],
        ["Same passage"],
    ]


def test_missing_file_ids_never_match_by_filename() -> None:
    sources = build_source_references(
        [Citation(file_id=None, filename="report.pdf")],
        ["report.pdf"],
        [
            RetrievedSearchResult(
                file_id=None,
                filename="report.pdf",
                text="Must not match",
            )
        ],
    )

    assert sources[0].evidence == []


def test_mismatched_positional_inputs_raise() -> None:
    with pytest.raises(ValueError):
        build_source_references(
            [Citation(file_id="file-A", filename="a.pdf")],
            [],
            [],
        )
