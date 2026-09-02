import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

from src.config.settings import OPENAI_MODEL
from src.retrieval import quote_selector
from src.schemas.evidence import SourceReference
from src.schemas.quotation import (
    EvidenceExcerptCandidate,
    QuoteCandidate,
    QuoteSelection,
)


def source(file_id, evidence, display_name="Secret Report.pdf"):
    return SourceReference(
        file_id=file_id,
        display_name=display_name,
        evidence=evidence,
    )


def install_fake_client(monkeypatch, response=None, error=None):
    captured = {"calls": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            captured["calls"] += 1
            captured.update(kwargs)
            if error is not None:
                raise error
            return response

    monkeypatch.setattr(
        quote_selector,
        "get_openai_client",
        lambda: SimpleNamespace(responses=FakeResponses()),
    )
    return captured


def completed(selection=None):
    return SimpleNamespace(
        status="completed",
        output_parsed=selection or QuoteSelection(),
    )


def test_scope_retains_original_zero_based_passage_identity() -> None:
    passages = quote_selector.build_support_evidence_scope(
        [source("file-A", ["   ", "Second", "Third"])]
    )

    assert [(item.file_id, item.passage_index, item.text) for item in passages] == [
        ("file-A", 1, "Second"),
        ("file-A", 2, "Third"),
    ]


def test_scope_is_cited_only_ranked_and_bounded() -> None:
    long_text = "x" * (quote_selector.MAX_SUPPORT_PASSAGE_CHARS + 10)
    sources = [
        source("file-A", [long_text] + [f"A{index}" for index in range(8)]),
        source(None, ["No ID"]),
        source(" bad ", ["Bad ID"]),
    ] + [source(f"file-{index}", [str(index)]) for index in range(1, 8)]

    passages = quote_selector.build_support_evidence_scope(sources)

    assert len({item.file_id for item in passages}) == 6
    assert sum(item.file_id == "file-A" for item in passages) == 6
    assert passages[0].text == long_text[:3500]
    assert all(len(item.text) <= 3500 for item in passages)


def test_scope_honors_total_character_cap(monkeypatch) -> None:
    monkeypatch.setattr(quote_selector, "MAX_SUPPORT_TOTAL_PASSAGE_CHARS", 7)

    passages = quote_selector.build_support_evidence_scope(
        [source("file-A", ["1234", "5678", "x"])]
    )

    assert [item.text for item in passages] == ["1234"]


def test_recent_context_excludes_current_duplicate_and_keeps_two_pairs() -> None:
    messages = [
        {"role": "system", "content": "ignore"},
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "one"},
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": "three"},
        {"role": "user", "content": "four"},
        {"role": "assistant", "content": "five"},
        {"role": "user", "content": "Current question"},
    ]

    context = quote_selector.build_recent_selector_context(
        messages,
        "Current question",
    )

    assert context == (
        "USER: two\n\nASSISTANT: three\n\n"
        "USER: four\n\nASSISTANT: five"
    )
    assert "Current question" not in context


def test_selector_uses_one_bounded_typed_request(monkeypatch) -> None:
    selection = QuoteSelection(
        candidates=[
            QuoteCandidate(file_id="file-A", passage_index=0, quote="Quote")
        ],
        best_support_candidates=[
            EvidenceExcerptCandidate(
                file_id="file-A", passage_index=0, text="Evidence"
            )
        ],
    )
    captured = install_fake_client(monkeypatch, completed(selection))
    passages = quote_selector.build_support_evidence_scope(
        [source("file-A", ["Evidence"])]
    )

    selected = quote_selector.select_quote_candidates(
        question="Q" * 4000 + "QUESTION_SECRET",
        provisional_answer="A" * 8000 + "ANSWER_SECRET",
        recent_context="C" * 6000 + "CONTEXT_SECRET",
        passages=passages,
    )

    payload = json.loads(captured["input"])
    assert captured["calls"] == 1
    assert captured["model"] == OPENAI_MODEL
    assert captured["text_format"] is QuoteSelection
    assert captured["max_output_tokens"] == 6000
    assert captured["instructions"] == quote_selector.PROMPT_PATH.read_text(
        encoding="utf-8"
    )
    assert len(payload["current_question"]) == 4000
    assert len(payload["provisional_answer"]) == 8000
    assert len(payload["recent_conversation_context"]) == 6000
    assert payload["retrieved_passages"] == [
        {"file_id": "file-A", "passage_index": 0, "text": "Evidence"}
    ]
    assert "Secret Report.pdf" not in captured["input"]
    assert selected == selection


def test_empty_scope_is_completed_empty_without_client(monkeypatch) -> None:
    monkeypatch.setattr(
        quote_selector,
        "get_openai_client",
        lambda: pytest.fail("client must not be created"),
    )

    assert quote_selector.select_quote_candidates(
        question="Q",
        provisional_answer="A",
        recent_context="",
        passages=[],
    ) == QuoteSelection()


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(status="incomplete", output_parsed=None),
        SimpleNamespace(status="failed", output_parsed=None),
        SimpleNamespace(status="completed", output_parsed=None),
        SimpleNamespace(status="completed", output_parsed={}),
        SimpleNamespace(
            status="completed",
            output_parsed=QuoteSelection(),
            output=[SimpleNamespace(type="refusal")],
        ),
    ],
)
def test_noncompleted_refused_or_malformed_response_is_processing_failure(
    monkeypatch,
    response,
) -> None:
    install_fake_client(monkeypatch, response)

    assert quote_selector.select_quote_candidates(
        question="Q",
        provisional_answer="A",
        recent_context="",
        passages=quote_selector.build_support_evidence_scope(
            [source("file-A", ["Evidence"])]
        ),
    ) is None


def test_expected_api_error_is_processing_failure_without_sensitive_log(
    monkeypatch,
    caplog,
) -> None:
    error = APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com/v1/responses")
    )
    install_fake_client(monkeypatch, error=error)

    result = quote_selector.select_quote_candidates(
        question="Sensitive question",
        provisional_answer="Sensitive answer",
        recent_context="Sensitive context",
        passages=quote_selector.build_support_evidence_scope(
            [source("file-secret", ["Sensitive evidence"])]
        ),
    )

    assert result is None
    assert "APIConnectionError" in caplog.text
    assert "Sensitive" not in caplog.text
    assert "file-secret" not in caplog.text


def test_unexpected_programming_error_is_not_hidden(monkeypatch) -> None:
    install_fake_client(monkeypatch, error=RuntimeError("programming defect"))

    with pytest.raises(RuntimeError, match="programming defect"):
        quote_selector.select_quote_candidates(
            question="Q",
            provisional_answer="A",
            recent_context="",
            passages=quote_selector.build_support_evidence_scope(
                [source("file-A", ["Evidence"])]
            ),
        )


def test_prompt_requires_all_roles_and_exact_passage_identity() -> None:
    prompt = quote_selector.PROMPT_PATH.read_text(encoding="utf-8")

    assert "zero-based `passage_index`" in prompt
    assert "exact contiguous excerpt" in prompt
    assert "best_support_candidates" in prompt
    assert "additional_context_candidates" in prompt
    assert "Do not paraphrase" in prompt
