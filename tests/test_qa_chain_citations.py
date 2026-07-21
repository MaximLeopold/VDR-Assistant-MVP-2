from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from openai.types.responses.response_output_text import AnnotationFileCitation

from src.chains import qa_chain
from src.config.constants import FALLBACK_ANSWER
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.schemas.answer import VDRAnswer


@pytest.fixture(autouse=True)
def disable_quote_selection(monkeypatch) -> None:
    """Keep Milestone 1A/1B regression tests isolated from API selection."""

    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: [],
    )


def fake_response(
    *annotations,
    answer: str = "Supported answer",
    search_results: list | None = None,
):
    output = [
        SimpleNamespace(
            type="message",
            content=[
                SimpleNamespace(
                    type="output_text",
                    text=answer,
                    annotations=list(annotations),
                )
            ],
        )
    ]
    if search_results is not None:
        output.append(
            SimpleNamespace(
                type="file_search_call",
                status="completed",
                results=search_results,
            )
        )
    return SimpleNamespace(output=output)


def citation(file_id: str, filename: str):
    return AnnotationFileCitation(
        file_id=file_id,
        filename=filename,
        index=0,
        type="file_citation",
    )


def search_result(file_id: str, filename: str, text: str):
    return SimpleNamespace(
        file_id=file_id,
        filename=filename,
        text=text,
        score=0.8,
    )


def manifest() -> VDRManifest:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = VDRFileRecord(
        relative_path="01 Finance/Annual Reports/Report.pdf",
        filename="Report.pdf",
        extension=".pdf",
        size_bytes=100,
        classification_status="supported",
        classification_reason="test record",
        openai_file_id="file-A",
        upload_status="uploaded",
        indexing_status="completed",
    )
    return VDRManifest(
        case_name="Test Case",
        vector_store_id="vs-test",
        created_at=now,
        updated_at=now,
        total_files=1,
        supported_files=1,
        unsupported_files=0,
        ignored_files=0,
        error_files=0,
        files=[record],
    )


def test_resolved_citations_are_passed_to_unchanged_validator(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: fake_response(citation("file-A", "Report.pdf")),
    )
    received = {}

    def capture_validator(**kwargs):
        received.update(kwargs)
        return VDRAnswer(
            answer=kwargs["answer"],
            source_files=kwargs["source_files"],
            workflow=kwargs["workflow"],
        )

    monkeypatch.setattr(qa_chain, "validate_answer", capture_validator)

    answer = qa_chain.run_qa_chain(
        "What is in the report?",
        "vs-test",
        manifest=manifest(),
    )

    assert received["source_files"] == [
        "VDR → 01 Finance → Annual Reports → Report.pdf"
    ]
    assert received["quotes"] == []
    assert "sources" not in received
    assert answer.source_files == received["source_files"]


def test_search_results_attach_after_successful_validation(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: fake_response(
            citation("file-A", "Report.pdf"),
            search_results=[
                search_result(
                    "file-A",
                    "Report.pdf",
                    "  Retrieved passage  ",
                ),
                search_result("file-uncited", "Other.pdf", "Unrelated"),
            ],
        ),
    )

    answer = qa_chain.run_qa_chain(
        "What is in the report?",
        "vs-test",
        manifest=manifest(),
    )

    assert answer.status == "success"
    assert len(answer.sources) == 1
    assert answer.sources[0].display_name == (
        "VDR → 01 Finance → Annual Reports → Report.pdf"
    )
    assert answer.sources[0].evidence == ["  Retrieved passage  "]


def test_exact_raw_evidence_reaches_structured_answer(monkeypatch) -> None:
    raw_text = "\t Leading evidence\r\nwith €42.6m \u2003"
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: fake_response(
            citation("file-A", "Report.pdf"),
            search_results=[
                search_result("file-A", "Report.pdf", raw_text),
            ],
        ),
    )

    answer = qa_chain.run_qa_chain(
        "What is in the report?",
        "vs-test",
        manifest=manifest(),
    )

    assert answer.status == "success"
    assert answer.sources[0].evidence == [raw_text]
    assert answer.source_files == [
        "VDR → 01 Finance → Annual Reports → Report.pdf"
    ]


def test_manifest_none_preserves_filename_only_citations(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: fake_response(citation("file-A", "Report.pdf")),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test", manifest=None)

    assert answer.status == "success"
    assert answer.source_files == ["Report.pdf"]
    assert answer.sources[0].display_name == "Report.pdf"
    assert answer.sources[0].evidence == []


def test_no_citations_preserves_not_found_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: fake_response(answer="Unsupported answer"),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test", manifest=manifest())

    assert answer.status == "not_found"
    assert answer.answer == FALLBACK_ANSWER
    assert answer.answer == (
        "I can not find this information in the VDR documents"
    )
    assert answer.source_files == []
    assert answer.sources == []


def test_retrieved_result_without_citation_does_not_create_success(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: fake_response(
            answer="Unsupported answer",
            search_results=[
                search_result("file-A", "Report.pdf", "Retrieved passage")
            ],
        ),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "not_found"
    assert answer.answer == FALLBACK_ANSWER
    assert answer.source_files == []
    assert answer.sources == []


def test_empty_search_results_do_not_invalidate_cited_answer(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: fake_response(
            citation("file-A", "Report.pdf"),
            search_results=[],
        ),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert answer.source_files == ["Report.pdf"]
    assert answer.sources[0].evidence == []


def test_structured_sources_are_not_attached_after_failed_validation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: fake_response(
            citation("file-A", "Report.pdf"),
            search_results=[
                search_result("file-A", "Report.pdf", "Retrieved passage")
            ],
        ),
    )
    monkeypatch.setattr(
        qa_chain,
        "validate_answer",
        lambda **kwargs: VDRAnswer(
            answer=FALLBACK_ANSWER,
            status="not_found",
            workflow="qa",
        ),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "not_found"
    assert answer.sources == []


def test_retrieval_exception_preserves_error_fallback(monkeypatch) -> None:
    def fail_search(**kwargs):
        raise RuntimeError("synthetic retrieval failure")

    monkeypatch.setattr(qa_chain, "search_vector_store", fail_search)

    answer = qa_chain.run_qa_chain("Question", "vs-test", manifest=manifest())

    assert answer.status == "error"
    assert answer.answer == FALLBACK_ANSWER
    assert answer.source_files == []
    assert answer.warnings == [
        "The Q&A workflow failed while searching the VDR.",
        "synthetic retrieval failure",
    ]
