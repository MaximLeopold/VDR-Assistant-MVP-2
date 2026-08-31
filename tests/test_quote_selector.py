from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

from src.config.settings import OPENAI_MODEL
from src.retrieval import quote_selector
from src.schemas.evidence import SourceReference
from src.schemas.quotation import QuoteCandidate, QuoteSelection


def source(
    file_id: str | None,
    evidence: list[str],
    display_name: str = "VDR → Finance → Report.pdf",
) -> SourceReference:
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

    client = SimpleNamespace(responses=FakeResponses())
    monkeypatch.setattr(quote_selector, "get_openai_client", lambda: client)
    return captured


def completed_response(candidates=None):
    return SimpleNamespace(
        status="completed",
        output_parsed=QuoteSelection(candidates=candidates or []),
    )


def test_scope_keeps_only_sources_with_file_ids_and_evidence() -> None:
    sources = [
        source("file-A", ["  A passage  "]),
        source(None, ["No identity"]),
        source("  ", ["Blank identity"]),
        source("file-empty", []),
        source("file-blank", ["   "]),
        source("file-B", ["B passage"]),
    ]

    bounded = quote_selector.build_quote_evidence_scope(sources)

    assert [item.file_id for item in bounded] == ["file-A", "file-B"]
    assert [item.evidence for item in bounded] == [
        ["A passage"],
        ["B passage"],
    ]


def test_scope_preserves_source_and_ranked_passage_order() -> None:
    bounded = quote_selector.build_quote_evidence_scope(
        [
            source("file-B", ["B first", "B second", "B third"]),
            source("file-A", ["A first", "A second"]),
        ]
    )

    assert [item.file_id for item in bounded] == ["file-B", "file-A"]
    assert bounded[0].evidence == ["B first", "B second"]
    assert bounded[1].evidence == ["A first", "A second"]


def test_scope_limits_sources_to_four() -> None:
    bounded = quote_selector.build_quote_evidence_scope(
        [source(f"file-{index}", [f"Passage {index}"]) for index in range(6)]
    )

    assert [item.file_id for item in bounded] == [
        "file-0",
        "file-1",
        "file-2",
        "file-3",
    ]


def test_scope_truncates_passage_without_ellipsis() -> None:
    passage = "x" * (quote_selector.MAX_QUOTE_PASSAGE_CHARS + 20)

    bounded = quote_selector.build_quote_evidence_scope(
        [source("file-A", [passage])]
    )

    assert bounded[0].evidence == [
        "x" * quote_selector.MAX_QUOTE_PASSAGE_CHARS
    ]
    assert "…" not in bounded[0].evidence[0]


def test_prompt_allows_three_distinct_candidates_from_one_source() -> None:
    prompt = quote_selector.PROMPT_PATH.read_text(encoding="utf-8")

    assert "Return at most three candidates." in prompt
    assert "Multiple candidates may come from the same source" in prompt
    assert "distinct, complementary support" in prompt
    assert "Return at most two candidates" not in prompt


def test_selector_uses_one_bounded_structured_request(monkeypatch) -> None:
    candidates = [
        QuoteCandidate(file_id=f"file-{index}", quote=f"Candidate {index}")
        for index in range(7)
    ]
    captured = install_fake_client(
        monkeypatch,
        completed_response(candidates),
    )
    display_name = "VDR → C:\\Users\\secret\\Report.pdf"
    quote_sources = quote_selector.build_quote_evidence_scope(
        [source("file-A", ["First passage", "Second passage"], display_name)]
    )
    answer = "A" * quote_selector.MAX_QUOTE_ANSWER_CHARS + "SECRET_TAIL"

    selected = quote_selector.select_quote_candidates(answer, quote_sources)

    assert captured["calls"] == 1
    assert captured["model"] == OPENAI_MODEL
    assert captured["text_format"] is QuoteSelection
    assert captured["max_output_tokens"] == (
        quote_selector.MAX_QUOTE_OUTPUT_TOKENS
    )
    assert captured["instructions"] == (
        quote_selector.PROMPT_PATH.read_text(encoding="utf-8")
    )
    assert captured["input"].split(
        "\n\nCited source evidence:", maxsplit=1
    )[0] == "Answer:\n" + "A" * quote_selector.MAX_QUOTE_ANSWER_CHARS
    assert "SECRET_TAIL" not in captured["input"]
    assert "Source ID: file-A" in captured["input"]
    assert "Passage 1:\nFirst passage" in captured["input"]
    assert "Passage 2:\nSecond passage" in captured["input"]
    assert "Report.pdf" not in captured["input"]
    assert "VDR" not in captured["input"]
    assert "C:\\Users" not in captured["input"]
    assert "0.8" not in captured["input"]
    assert len(selected) == quote_selector.MAX_QUOTE_CANDIDATES_TO_PROCESS


def test_empty_scope_does_not_create_client(monkeypatch) -> None:
    def fail_client_creation():
        raise AssertionError("client must not be created")

    monkeypatch.setattr(
        quote_selector,
        "get_openai_client",
        fail_client_creation,
    )

    assert quote_selector.select_quote_candidates("Answer", []) == []


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (completed_response(), []),
        (SimpleNamespace(status="completed", output_parsed=None), []),
        (
            SimpleNamespace(
                status="completed",
                output_parsed=None,
                output=[SimpleNamespace(type="refusal")],
            ),
            [],
        ),
        (SimpleNamespace(status="incomplete", output_parsed=None), []),
        (SimpleNamespace(status="failed", output_parsed=None), []),
        (SimpleNamespace(status="completed", output_parsed={}), []),
    ],
)
def test_non_successful_or_empty_structured_states_return_no_candidates(
    monkeypatch,
    response,
    expected,
) -> None:
    install_fake_client(monkeypatch, response)

    assert quote_selector.select_quote_candidates(
        "Answer",
        [source("file-A", ["Evidence passage"])],
    ) == expected


def test_structured_validation_error_returns_empty_without_sensitive_log_data(
    monkeypatch,
    caplog,
) -> None:
    class InvalidResponses:
        def parse(self, **kwargs):
            QuoteSelection.model_validate(
                {"candidates": [{"file_id": "file-secret"}]}
            )

    monkeypatch.setattr(
        quote_selector,
        "get_openai_client",
        lambda: SimpleNamespace(responses=InvalidResponses()),
    )

    selected = quote_selector.select_quote_candidates(
        "Sensitive answer",
        [source("file-secret", ["Sensitive evidence"])],
    )

    assert selected == []
    assert "ValidationError" in caplog.text
    assert "Sensitive answer" not in caplog.text
    assert "Sensitive evidence" not in caplog.text
    assert "file-secret" not in caplog.text


def test_openai_api_error_returns_empty_without_sensitive_log_data(
    monkeypatch,
    caplog,
) -> None:
    error = APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com/v1/responses")
    )
    install_fake_client(monkeypatch, error=error)

    selected = quote_selector.select_quote_candidates(
        "Sensitive answer",
        [source("file-secret", ["Sensitive evidence"])],
    )

    assert selected == []
    assert "APIConnectionError" in caplog.text
    assert "Sensitive answer" not in caplog.text
    assert "Sensitive evidence" not in caplog.text
    assert "file-secret" not in caplog.text


def test_unexpected_programming_error_is_not_hidden(monkeypatch) -> None:
    install_fake_client(monkeypatch, error=RuntimeError("programming defect"))

    with pytest.raises(RuntimeError, match="programming defect"):
        quote_selector.select_quote_candidates(
            "Answer",
            [source("file-A", ["Evidence passage"])],
        )
