from types import SimpleNamespace

import httpx
import pytest
from openai import (
    APIConnectionError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)

from src.config.settings import OPENAI_MODEL
from src.presentation import evidence_selector
from src.schemas.evidence import SourceReference
from src.schemas.evidence_presentation import (
    EvidenceMetricCandidate,
    EvidencePresentationPassage,
    EvidencePresentationSelection,
)


ELIGIBLE_METRIC = "Revenue FY2024 EURm 28,051"


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


def metric_candidate() -> EvidenceMetricCandidate:
    return EvidenceMetricCandidate(
        file_id="file-A",
        passage_index=0,
        label="Revenue",
        value="28,051",
        period="FY2024",
        unit="EURm",
        source_span=ELIGIBLE_METRIC,
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
    monkeypatch.setattr(
        evidence_selector,
        "get_openai_client",
        lambda: client,
    )
    return captured


def completed_response(selection=None):
    return SimpleNamespace(
        status="completed",
        output_parsed=selection or EvidencePresentationSelection(),
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \r\n\t",
        "The company provides services to enterprise customers.",
        "The company has 1 office.",
        "The company has 1 office and 2 warehouses.",
    ],
)
def test_ordinary_or_sparse_text_is_not_eligible(text: str) -> None:
    assert evidence_selector.is_structured_evidence_candidate(text) is False


@pytest.mark.parametrize(
    "text",
    [
        ELIGIBLE_METRIC,
        "Revenue FY2024 28,051",
        "Adjusted EBITDA margin FY2024 15.6%",
        "Employees 12,000",
        "Reporting periods: 2022 2023 2024",
        "Margin 12.5% 13.0% 14.2%",
        "Revenue USD 10 20 30",
        "Revenue 10 20 30 40",
        "Year Revenue\n2023 23,683\n2024 28,051",
        (
            "Revenue 10,131 12,324 13,533 14,821 17,117 20,062 23,683\n"
            "28,051 15.6% 15.7%"
        ),
    ],
)
def test_number_heavy_or_row_oriented_text_is_eligible(text: str) -> None:
    assert evidence_selector.is_structured_evidence_candidate(text) is True


def test_eligibility_is_deterministic_and_does_not_mutate_text() -> None:
    original = "\r\n  Revenue FY2024 EURm 28,051  \r\n"
    snapshot = original[:]

    first = evidence_selector.is_structured_evidence_candidate(original)
    second = evidence_selector.is_structured_evidence_candidate(original)

    assert first is True
    assert second is True
    assert original == snapshot


def test_eligibility_requires_string_input() -> None:
    with pytest.raises(TypeError, match="string"):
        evidence_selector.is_structured_evidence_candidate(
            None  # type: ignore[arg-type]
        )


def test_scope_keeps_exact_raw_text_file_id_and_original_passage_index() -> None:
    raw = "\r\n  Revenue FY2024 EURm 28,051  \r\n"
    sources = [
        source(None, [ELIGIBLE_METRIC]),
        source("  ", [ELIGIBLE_METRIC]),
        source(" file-invalid", [ELIGIBLE_METRIC]),
        source(
            "file-A",
            ["Ordinary prose.", raw, "Margin 1% 2% 3%"],
        ),
    ]

    scope = evidence_selector.build_evidence_presentation_scope(sources)

    assert [(item.file_id, item.passage_index) for item in scope] == [
        ("file-A", 1),
        ("file-A", 2),
    ]
    assert scope[0].text == raw
    assert sources[3].evidence[1] == raw


def test_scope_preserves_source_and_ranked_passage_order() -> None:
    scope = evidence_selector.build_evidence_presentation_scope(
        [
            source("file-B", ["Revenue 1 2 3 4", "Margin 1% 2% 3%"]),
            source("file-A", ["Year Revenue\n2023 10\n2024 20"]),
        ]
    )

    assert [(item.file_id, item.passage_index) for item in scope] == [
        ("file-B", 0),
        ("file-B", 1),
        ("file-A", 0),
    ]


def test_scope_limits_eligible_sources_to_four() -> None:
    scope = evidence_selector.build_evidence_presentation_scope(
        [source(f"file-{index}", [ELIGIBLE_METRIC]) for index in range(6)]
    )

    assert [item.file_id for item in scope] == [
        "file-0",
        "file-1",
        "file-2",
        "file-3",
    ]


def test_scope_limits_eligible_passages_to_two_per_source() -> None:
    scope = evidence_selector.build_evidence_presentation_scope(
        [source("file-A", [ELIGIBLE_METRIC] * 4)]
    )

    assert [item.passage_index for item in scope] == [0, 1]


def test_scope_uses_exact_4500_character_raw_prefix_without_mutation() -> None:
    raw = "Revenue 1 2 3 4 " + "x" * 5000
    sources = [source("file-A", [raw])]

    scope = evidence_selector.build_evidence_presentation_scope(sources)

    assert len(scope[0].text) == 4500
    assert scope[0].text == raw[:4500]
    assert sources[0].evidence[0] == raw


def test_scope_stops_before_exceeding_total_character_limit() -> None:
    raw = "Revenue 1 2 3 4 " + "x" * 5000
    scope = evidence_selector.build_evidence_presentation_scope(
        [
            source("file-A", [raw, raw]),
            source("file-B", [raw, raw]),
            source("file-C", [raw]),
        ]
    )

    assert len(scope) == 3
    assert sum(len(item.text) for item in scope) == 13500
    assert [(item.file_id, item.passage_index) for item in scope] == [
        ("file-A", 0),
        ("file-A", 1),
        ("file-B", 0),
    ]


def test_selector_uses_one_raw_only_bounded_structured_request(monkeypatch) -> None:
    selection = EvidencePresentationSelection(metrics=[metric_candidate()])
    captured = install_fake_client(monkeypatch, completed_response(selection))
    passages = evidence_selector.build_evidence_presentation_scope(
        [
            source(
                "file-A",
                [ELIGIBLE_METRIC],
                "VDR → C:\\Users\\secret\\Report.pdf",
            )
        ]
    )

    selected = evidence_selector.select_evidence_presentations(passages)

    assert captured["calls"] == 1
    assert captured["model"] == OPENAI_MODEL
    assert captured["text_format"] is EvidencePresentationSelection
    assert captured["max_output_tokens"] == 5000
    assert captured["instructions"] == (
        evidence_selector.PROMPT_PATH.read_text(encoding="utf-8")
    )
    assert "<file_id>file-A</file_id>" in captured["input"]
    assert "<passage_index>0</passage_index>" in captured["input"]
    assert f"<raw_text>\n{ELIGIBLE_METRIC}\n</raw_text>" in captured["input"]
    assert "Report.pdf" not in captured["input"]
    assert "VDR" not in captured["input"]
    assert "C:\\Users" not in captured["input"]
    assert "question" not in captured["input"].lower()
    assert "answer" not in captured["input"].lower()
    assert "score" not in captured["input"].lower()
    assert selected == selection


@pytest.mark.parametrize(
    "text",
    [
        "Period 2024A 2025E 2026F\nRevenue 10 12 14",
        "Period FY25 FY26 FY27\nEBITDA 5.2 6.1 7.4",
        "Period Q1 27 Q2 27 Q3 27\nRevenue 10 12 14",
        "Period H1 2025 H2 2025\nRevenue 10 12",
        "Scenario Base Upside Downside\nRevenue 10 12 9",
        "Period LTM NTM\nRevenue 10 12",
    ],
)
def test_horizontal_financial_markers_are_eligible(text: str) -> None:
    assert evidence_selector.is_structured_evidence_candidate(text) is True


def test_prompt_requests_fail_closed_parallel_series_without_charts() -> None:
    prompt = evidence_selector.PROMPT_PATH.read_text(encoding="utf-8")

    assert "parallel-series candidate" in prompt
    assert "one logical line" in prompt
    assert "flattened onto one line" in prompt
    assert "Do not return an incomplete table" in prompt
    assert "chart specification" in prompt


def test_empty_scope_does_not_create_client(monkeypatch) -> None:
    def fail_client_creation():
        raise AssertionError("client must not be created")

    monkeypatch.setattr(
        evidence_selector,
        "get_openai_client",
        fail_client_creation,
    )

    assert (
        evidence_selector.select_evidence_presentations([])
        == EvidencePresentationSelection()
    )


@pytest.mark.parametrize(
    "response",
    [
        completed_response(),
        SimpleNamespace(status="completed", output_parsed=None),
        SimpleNamespace(
            status="completed",
            output_parsed=None,
            output=[SimpleNamespace(type="refusal")],
        ),
        SimpleNamespace(
            status="completed",
            output_parsed=EvidencePresentationSelection(
                metrics=[metric_candidate()]
            ),
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="refusal")],
                )
            ],
        ),
        SimpleNamespace(status="incomplete", output_parsed=None),
        SimpleNamespace(status="failed", output_parsed=None),
        SimpleNamespace(status="completed", output_parsed={}),
    ],
)
def test_empty_refused_incomplete_failed_or_malformed_states_return_empty(
    monkeypatch,
    response,
) -> None:
    install_fake_client(monkeypatch, response)

    selected = evidence_selector.select_evidence_presentations(
        [
            EvidencePresentationPassage(
                file_id="file-A",
                passage_index=0,
                text=ELIGIBLE_METRIC,
            )
        ]
    )

    assert selected == EvidencePresentationSelection()


def test_structured_validation_error_returns_empty_without_sensitive_logs(
    monkeypatch,
    caplog,
) -> None:
    class InvalidResponses:
        def parse(self, **kwargs):
            EvidencePresentationSelection.model_validate(
                {"metrics": [{"file_id": "file-secret"}]}
            )

    monkeypatch.setattr(
        evidence_selector,
        "get_openai_client",
        lambda: SimpleNamespace(responses=InvalidResponses()),
    )

    selected = evidence_selector.select_evidence_presentations(
        [
            EvidencePresentationPassage(
                file_id="file-secret",
                passage_index=0,
                text="Sensitive revenue 1 2 3 4",
            )
        ]
    )

    assert selected == EvidencePresentationSelection()
    assert "ValidationError" in caplog.text
    assert "Sensitive revenue" not in caplog.text
    assert "file-secret" not in caplog.text


def test_openai_api_error_returns_empty_without_sensitive_logs(
    monkeypatch,
    caplog,
) -> None:
    error = APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com/v1/responses")
    )
    install_fake_client(monkeypatch, error=error)

    selected = evidence_selector.select_evidence_presentations(
        [
            EvidencePresentationPassage(
                file_id="file-secret",
                passage_index=0,
                text="Sensitive revenue 1 2 3 4",
            )
        ]
    )

    assert selected == EvidencePresentationSelection()
    assert "APIConnectionError" in caplog.text
    assert "Sensitive revenue" not in caplog.text
    assert "file-secret" not in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        ContentFilterFinishReasonError(),
        LengthFinishReasonError.__new__(LengthFinishReasonError),
    ],
)
def test_structured_finish_reason_errors_return_empty(
    monkeypatch,
    error,
) -> None:
    Exception.__init__(error, "structured response was not completed")
    install_fake_client(monkeypatch, error=error)

    selected = evidence_selector.select_evidence_presentations(
        [
            EvidencePresentationPassage(
                file_id="file-A",
                passage_index=0,
                text=ELIGIBLE_METRIC,
            )
        ]
    )

    assert selected == EvidencePresentationSelection()


def test_unexpected_programming_error_is_not_hidden(monkeypatch) -> None:
    install_fake_client(monkeypatch, error=RuntimeError("programming defect"))

    with pytest.raises(RuntimeError, match="programming defect"):
        evidence_selector.select_evidence_presentations(
            [
                EvidencePresentationPassage(
                    file_id="file-A",
                    passage_index=0,
                    text=ELIGIBLE_METRIC,
                )
            ]
        )
