from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from openai.types.responses.response_output_text import AnnotationFileCitation

from src.chains import qa_chain
from src.config.constants import FALLBACK_ANSWER
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.schemas.answer import VDRAnswer
from src.schemas.quotation import (
    EvidenceExcerptCandidate,
    QuoteCandidate,
    QuoteSelection,
)


VERIFIABLE_TEXT = (
    "Subject to satisfactory completion of due diligence, "
    "the enterprise value is EUR 42 million."
)


def citation(file_id: str, filename: str):
    return AnnotationFileCitation(
        file_id=file_id,
        filename=filename,
        index=0,
        type="file_citation",
    )


def search_result(file_id, text, score=0.8, filename="Report.pdf"):
    return SimpleNamespace(
        file_id=file_id,
        filename=filename,
        text=text,
        score=score,
    )


def response(*annotations, answer="PROVISIONAL SECRET", results=None):
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
    if results is not None:
        output.append(
            SimpleNamespace(
                type="file_search_call",
                status="completed",
                results=results,
            )
        )
    return SimpleNamespace(output=output)


def manifest() -> VDRManifest:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = VDRFileRecord(
        relative_path="03 NBO/Offer.pdf",
        filename="Offer.pdf",
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


def install_supported_search(monkeypatch, results=None):
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "Offer.pdf"),
            results=[search_result("file-A", VERIFIABLE_TEXT)]
            if results is None
            else results,
        ),
    )


def supported_selection(
    *,
    quotes=True,
    best=True,
    additional=False,
    passage_index=0,
):
    return QuoteSelection(
        candidates=(
            [
                QuoteCandidate(
                    file_id="file-A",
                    passage_index=passage_index,
                    quote=VERIFIABLE_TEXT,
                )
            ]
            if quotes
            else []
        ),
        best_support_candidates=(
            [
                EvidenceExcerptCandidate(
                    file_id="file-A",
                    passage_index=passage_index,
                    text=VERIFIABLE_TEXT,
                )
            ]
            if best
            else []
        ),
        additional_context_candidates=(
            [
                EvidenceExcerptCandidate(
                    file_id="file-A",
                    passage_index=passage_index,
                    text="the enterprise value is EUR 42 million",
                )
            ]
            if additional
            else []
        ),
    )


@pytest.fixture(autouse=True)
def default_supported_selector(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: supported_selection(),
    )


def test_combined_selector_runs_after_primary_validation(monkeypatch) -> None:
    install_supported_search(monkeypatch)
    events = []
    original_validator = qa_chain.validate_answer

    def validate(**kwargs):
        events.append("validate")
        return original_validator(**kwargs)

    def select(**kwargs):
        events.append("select")
        return supported_selection()

    monkeypatch.setattr(qa_chain, "validate_answer", validate)
    monkeypatch.setattr(qa_chain, "select_quote_candidates", select)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert events == ["validate", "select"]


@pytest.mark.parametrize("status", ["not_found", "error"])
def test_combined_selector_does_not_run_after_failed_validation(
    monkeypatch,
    status,
) -> None:
    install_supported_search(monkeypatch)
    monkeypatch.setattr(
        qa_chain,
        "validate_answer",
        lambda **kwargs: VDRAnswer(
            answer=FALLBACK_ANSWER,
            status=status,
            workflow="qa",
        ),
    )
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: pytest.fail("selector must not run"),
    )

    assert qa_chain.run_qa_chain("Question", "vs-test").status == status


@pytest.mark.parametrize(
    ("quotes", "best", "expected"),
    [
        (False, True, qa_chain.QUOTE_SUPPORT_MISSING_ANSWER),
        (True, False, qa_chain.BEST_SUPPORT_MISSING_ANSWER),
        (False, False, qa_chain.BOTH_SUPPORT_MISSING_ANSWER),
    ],
)
def test_mandatory_gate_withholds_provisional_answer(
    monkeypatch,
    quotes,
    best,
    expected,
) -> None:
    install_supported_search(monkeypatch)
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: supported_selection(quotes=quotes, best=best),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")
    payload = answer.model_dump_json()

    assert answer.status == "not_found"
    assert answer.answer == expected
    assert answer.source_files == []
    assert answer.sources == []
    assert answer.verified_quotes == []
    assert answer.warnings == []
    assert "PROVISIONAL SECRET" not in payload


@pytest.mark.parametrize("selector_result", [None, RuntimeError("defect")])
def test_processing_failure_is_fail_closed(
    monkeypatch,
    selector_result,
) -> None:
    install_supported_search(monkeypatch)

    def select(**kwargs):
        if isinstance(selector_result, Exception):
            raise selector_result
        return selector_result

    monkeypatch.setattr(qa_chain, "select_quote_candidates", select)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "error"
    assert answer.answer == qa_chain.SUPPORT_PROCESSING_FAILED_ANSWER
    assert "PROVISIONAL SECRET" not in answer.model_dump_json()
    assert answer.warnings == []


def test_success_persists_verified_roles_without_mutating_raw_evidence(
    monkeypatch,
) -> None:
    install_supported_search(monkeypatch)
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: supported_selection(additional=True),
    )

    answer = qa_chain.run_qa_chain(
        "Question",
        "vs-test",
        manifest=manifest(),
    )

    source = answer.sources[0]
    assert answer.status == "success"
    assert answer.answer == "PROVISIONAL SECRET"
    assert answer.source_files == ["VDR \u2192 03 NBO \u2192 Offer.pdf"]
    assert source.evidence == [VERIFIABLE_TEXT]
    assert source.evidence_selection_status == "completed"
    assert [item.role for item in source.selected_evidence] == [
        "best_support",
        "additional_context",
    ]
    assert [item.passage_index for item in source.selected_evidence] == [0, 0]
    assert len(answer.verified_quotes) == 1


def test_wrong_passage_identity_cannot_substitute_matching_passage(
    monkeypatch,
) -> None:
    install_supported_search(
        monkeypatch,
        results=[
            search_result("file-A", "Unrelated first", score=0.9),
            search_result("file-A", VERIFIABLE_TEXT, score=0.8),
        ],
    )
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: supported_selection(passage_index=0),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.answer == qa_chain.BOTH_SUPPORT_MISSING_ANSWER
    assert "PROVISIONAL SECRET" not in answer.model_dump_json()


def test_selector_receives_exact_question_answer_context_and_cited_scope(
    monkeypatch,
) -> None:
    install_supported_search(
        monkeypatch,
        results=[
            search_result("file-uncited", "Unrelated"),
            search_result("file-A", VERIFIABLE_TEXT),
        ],
    )
    captured = {}

    def select(**kwargs):
        captured.update(kwargs)
        return supported_selection()

    monkeypatch.setattr(qa_chain, "select_quote_candidates", select)
    messages = [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
        {"role": "user", "content": "Exact question"},
    ]

    qa_chain.run_qa_chain(
        "Exact question",
        "vs-test",
        messages=messages,
    )

    assert captured["question"] == "Exact question"
    assert captured["provisional_answer"] == "PROVISIONAL SECRET"
    assert captured["recent_context"] == (
        "USER: Earlier question\n\nASSISTANT: Earlier answer"
    )
    captured_passages = [
        (item.file_id, item.passage_index, item.text)
        for item in captured["passages"]
    ]
    assert captured_passages == [
        ("file-A", 0, VERIFIABLE_TEXT)
    ]


def test_no_eligible_evidence_fails_both_support_checks(monkeypatch) -> None:
    install_supported_search(monkeypatch, results=[])
    captured = {"calls": 0}

    def select(**kwargs):
        captured["calls"] += 1
        assert kwargs["passages"] == []
        return QuoteSelection()

    monkeypatch.setattr(qa_chain, "select_quote_candidates", select)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert captured["calls"] == 1
    assert answer.answer == qa_chain.BOTH_SUPPORT_MISSING_ANSWER
    assert answer.sources == []


def test_retrieved_results_without_citations_never_reach_selector(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            results=[search_result("file-A", VERIFIABLE_TEXT)]
        ),
    )
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: pytest.fail("selector must not run"),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "not_found"
    assert answer.answer == FALLBACK_ANSWER


def test_main_prompt_defers_verified_quotation_selection() -> None:
    prompt = qa_chain.load_qa_prompt()

    assert "Do not present retrieved document text as a direct quotation" in prompt
    assert "Verified quotations are selected and source-checked separately." in prompt
