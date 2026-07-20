from datetime import datetime, timezone
from types import SimpleNamespace

from openai.types.responses.response_output_text import AnnotationFileCitation

from src.chains import qa_chain
from src.config.constants import FALLBACK_ANSWER
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.schemas.answer import VDRAnswer


def fake_response(*annotations, answer: str = "Supported answer"):
    return SimpleNamespace(
        output=[
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
    )


def citation(file_id: str, filename: str):
    return AnnotationFileCitation(
        file_id=file_id,
        filename=filename,
        index=0,
        type="file_citation",
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
    assert answer.source_files == received["source_files"]


def test_manifest_none_preserves_filename_only_citations(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: fake_response(citation("file-A", "Report.pdf")),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test", manifest=None)

    assert answer.status == "success"
    assert answer.source_files == ["Report.pdf"]


def test_no_citations_preserves_not_found_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: fake_response(answer="Unsupported answer"),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test", manifest=manifest())

    assert answer.status == "not_found"
    assert answer.answer == FALLBACK_ANSWER
    assert answer.source_files == []


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
