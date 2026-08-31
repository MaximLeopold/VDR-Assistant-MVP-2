from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError
from openai.types.responses.response_output_text import AnnotationFileCitation

from src.chains import qa_chain
from src.config.constants import FALLBACK_ANSWER
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.retrieval import quote_selector
from src.schemas.answer import VDRAnswer
from src.schemas.quotation import QuoteCandidate


VERIFIABLE_TEXT = (
    "Subject to satisfactory completion of due diligence, "
    "the enterprise value is EUR 42 million."
)


@pytest.fixture(autouse=True)
def default_noop_selector(monkeypatch) -> None:
    """Prevent any live selector request unless a test supplies a fake."""

    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: [],
    )


def citation(file_id: str, filename: str):
    return AnnotationFileCitation(
        file_id=file_id,
        filename=filename,
        index=0,
        type="file_citation",
    )


def search_result(
    file_id: str,
    text: str,
    score: float = 0.8,
    filename: str = "Report.pdf",
):
    return SimpleNamespace(
        file_id=file_id,
        filename=filename,
        text=text,
        score=score,
    )


def response(
    *annotations,
    answer: str = "Supported answer",
    results: list | None = None,
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


def install_supported_search(monkeypatch, results=None) -> None:
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


def test_selector_runs_only_after_successful_validation(monkeypatch) -> None:
    install_supported_search(monkeypatch)
    events = []
    original_validator = qa_chain.validate_answer

    def validate(**kwargs):
        events.append("validate")
        return original_validator(**kwargs)

    def select(**kwargs):
        events.append("select")
        return []

    monkeypatch.setattr(qa_chain, "validate_answer", validate)
    monkeypatch.setattr(qa_chain, "select_quote_candidates", select)

    answer = qa_chain.run_qa_chain("Question", "vs-test", manifest=manifest())

    assert answer.status == "success"
    assert events == ["validate", "select"]


@pytest.mark.parametrize("status", ["not_found", "error"])
def test_selector_does_not_run_after_non_success_validation(
    monkeypatch,
    status: str,
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

    def fail_selector(**kwargs):
        raise AssertionError("selector must not run")

    monkeypatch.setattr(qa_chain, "select_quote_candidates", fail_selector)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == status


def test_selector_does_not_run_for_retrieval_error(monkeypatch) -> None:
    def fail_search(**kwargs):
        raise RuntimeError("synthetic retrieval error")

    monkeypatch.setattr(qa_chain, "search_vector_store", fail_search)

    def fail_selector(**kwargs):
        raise AssertionError("selector must not run")

    monkeypatch.setattr(qa_chain, "select_quote_candidates", fail_selector)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "error"
    assert answer.answer == FALLBACK_ANSWER


def test_selector_does_not_run_without_eligible_evidence(monkeypatch) -> None:
    install_supported_search(monkeypatch, results=[])

    def fail_selector(**kwargs):
        raise AssertionError("selector must not run")

    monkeypatch.setattr(qa_chain, "select_quote_candidates", fail_selector)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert answer.verified_quotes == []
    assert answer.sources[0].evidence == []


def test_valid_answer_without_candidates_remains_successful(monkeypatch) -> None:
    install_supported_search(monkeypatch)
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: [],
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert answer.answer == "Supported answer"
    assert answer.verified_quotes == []
    assert answer.sources[0].evidence == [VERIFIABLE_TEXT]


def test_unverifiable_candidate_does_not_change_supported_answer(
    monkeypatch,
) -> None:
    install_supported_search(monkeypatch)
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: [
            QuoteCandidate(
                file_id="file-A",
                quote="The enterprise value is EUR 43 million.",
            )
        ],
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert answer.answer == "Supported answer"
    assert answer.verified_quotes == []
    assert answer.sources[0].evidence == [VERIFIABLE_TEXT]


def test_handled_selector_api_failure_leaves_answer_unchanged(
    monkeypatch,
) -> None:
    install_supported_search(monkeypatch)

    class FailingResponses:
        def parse(self, **kwargs):
            raise APIConnectionError(
                request=httpx.Request(
                    "POST",
                    "https://api.openai.com/v1/responses",
                )
            )

    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        quote_selector.select_quote_candidates,
    )
    monkeypatch.setattr(
        quote_selector,
        "get_openai_client",
        lambda: SimpleNamespace(responses=FailingResponses()),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert answer.answer == "Supported answer"
    assert answer.source_files == ["Offer.pdf"]
    assert answer.sources[0].evidence == [VERIFIABLE_TEXT]


def test_verified_quotes_attach_without_changing_sources_or_evidence(
    monkeypatch,
) -> None:
    install_supported_search(monkeypatch)
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: [
            QuoteCandidate(file_id="file-A", quote=VERIFIABLE_TEXT)
        ],
    )

    answer = qa_chain.run_qa_chain(
        "Question",
        "vs-test",
        manifest=manifest(),
    )

    breadcrumb = "VDR → 03 NBO → Offer.pdf"
    assert answer.status == "success"
    assert answer.source_files == [breadcrumb]
    assert answer.sources[0].display_name == breadcrumb
    assert answer.sources[0].file_id == "file-A"
    assert answer.sources[0].evidence == [VERIFIABLE_TEXT]
    assert len(answer.verified_quotes) == 1
    assert answer.verified_quotes[0].file_id == "file-A"
    assert answer.verified_quotes[0].source_display_name == breadcrumb
    assert answer.verified_quotes[0].text == VERIFIABLE_TEXT


def test_three_same_source_quotes_preserve_primary_result_and_raw_evidence(
    monkeypatch,
) -> None:
    quote_texts = [
        "The first distinct source quotation supports the accepted answer.",
        "The second distinct source quotation adds separate source support.",
        "The third distinct source quotation adds complementary source support.",
    ]
    raw_passage = "\n".join(quote_texts)
    install_supported_search(
        monkeypatch,
        results=[search_result("file-A", raw_passage)],
    )
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: [
            QuoteCandidate(file_id="file-A", quote=text)
            for text in quote_texts
        ],
    )

    answer = qa_chain.run_qa_chain(
        "Question",
        "vs-test",
        manifest=manifest(),
    )

    breadcrumb = "VDR → 03 NBO → Offer.pdf"
    assert answer.answer == "Supported answer"
    assert answer.status == "success"
    assert answer.source_files == [breadcrumb]
    assert [source.file_id for source in answer.sources] == ["file-A"]
    assert answer.sources[0].display_name == breadcrumb
    assert answer.sources[0].evidence == [raw_passage]
    assert [quote.text for quote in answer.verified_quotes] == quote_texts
    assert all(
        quote.source_display_name == breadcrumb
        for quote in answer.verified_quotes
    )


def test_uncited_results_are_not_sent_to_selector(monkeypatch) -> None:
    install_supported_search(
        monkeypatch,
        results=[
            search_result("file-uncited", "Unrelated retrieved passage"),
            search_result("file-A", VERIFIABLE_TEXT),
        ],
    )
    captured = {}

    def select(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(qa_chain, "select_quote_candidates", select)

    qa_chain.run_qa_chain("Question", "vs-test")

    assert [item.file_id for item in captured["quote_sources"]] == ["file-A"]
    assert captured["quote_sources"][0].evidence == [VERIFIABLE_TEXT]
    assert "Unrelated retrieved passage" not in str(captured["quote_sources"])


def test_selector_receives_only_bounded_ranked_source_evidence(
    monkeypatch,
) -> None:
    longest = "x" * (quote_selector.MAX_QUOTE_PASSAGE_CHARS + 100)
    install_supported_search(
        monkeypatch,
        results=[
            search_result("file-A", "third ranked", score=0.1),
            search_result("file-A", "second ranked", score=0.8),
            search_result("file-A", longest, score=0.9),
        ],
    )
    captured = {}

    def select(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(qa_chain, "select_quote_candidates", select)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    quote_source = captured["quote_sources"][0]
    assert quote_source.evidence == [
        longest[: quote_selector.MAX_QUOTE_PASSAGE_CHARS],
        "second ranked",
    ]
    assert answer.sources[0].evidence == [
        longest,
        "second ranked",
        "third ranked",
    ]


def test_quote_verification_receives_full_raw_source_evidence(
    monkeypatch,
) -> None:
    raw_text = (
        "\t Full raw passage\r\n"
        + "x" * (quote_selector.MAX_QUOTE_PASSAGE_CHARS + 100)
        + "  "
    )
    install_supported_search(
        monkeypatch,
        results=[search_result("file-A", raw_text)],
    )
    captured = {}

    def select(**kwargs):
        captured["selector_sources"] = kwargs["quote_sources"]
        return [QuoteCandidate(file_id="file-A", quote="x" * 20)]

    def verify(**kwargs):
        captured["verifier_sources"] = kwargs["quote_sources"]
        return []

    monkeypatch.setattr(qa_chain, "select_quote_candidates", select)
    monkeypatch.setattr(qa_chain, "verify_quote_candidates", verify)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.sources[0].evidence == [raw_text]
    assert captured["selector_sources"][0].evidence == [
        raw_text.strip()[: quote_selector.MAX_QUOTE_PASSAGE_CHARS]
    ]
    assert captured["verifier_sources"] == answer.sources
    assert captured["verifier_sources"][0].evidence == [raw_text]


def test_retrieved_results_alone_cannot_create_success_or_quotes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            answer="Unsupported answer",
            results=[search_result("file-A", VERIFIABLE_TEXT)],
        ),
    )

    def fail_selector(**kwargs):
        raise AssertionError("selector must not run")

    monkeypatch.setattr(qa_chain, "select_quote_candidates", fail_selector)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "not_found"
    assert answer.answer == (
        "I can not find this information in the VDR documents"
    )
    assert answer.answer == FALLBACK_ANSWER
    assert answer.source_files == []
    assert answer.sources == []
    assert answer.verified_quotes == []


def test_main_prompt_defers_verified_quotation_selection() -> None:
    prompt = qa_chain.load_qa_prompt()

    assert (
        "Do not present retrieved document text as a direct quotation in the answer."
        in prompt
    )
    assert "Verified quotations are selected and source-checked separately." in prompt
    assert "Include direct quotations" not in prompt
