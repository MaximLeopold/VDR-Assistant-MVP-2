from types import SimpleNamespace

import pytest
from openai.types.responses.response_output_text import AnnotationFileCitation

from src.chains import qa_chain
from src.config.constants import FALLBACK_ANSWER
from src.schemas.evidence_presentation import (
    EvidenceParallelSeriesCandidate,
    EvidencePresentationSelection,
    EvidenceSeriesCandidate,
    VerifiedEvidenceMetric,
    VerifiedEvidencePresentation,
    VerifiedEvidenceTable,
)
from src.schemas.quotation import (
    EvidenceExcerptCandidate,
    QuoteCandidate,
    QuoteSelection,
)


ELIGIBLE_TEXT = (
    "Revenue FY2024 EURm 28,051 EBITDA 4,905 Margin 17.5%"
)
QUOTE_TEXT = (
    "Subject to satisfactory due diligence, the enterprise value is "
    "EUR 42 million."
)


@pytest.fixture(autouse=True)
def default_supported_quote_selector(monkeypatch) -> None:
    def select(**kwargs):
        if not kwargs["passages"]:
            return QuoteSelection()
        passage = kwargs["passages"][0]
        quote_text = passage.text.strip()[:500]
        return QuoteSelection(
            candidates=[
                QuoteCandidate(
                    file_id=passage.file_id,
                    passage_index=passage.passage_index,
                    quote=quote_text,
                )
            ],
            best_support_candidates=[
                EvidenceExcerptCandidate(
                    file_id=passage.file_id,
                    passage_index=passage.passage_index,
                    text=passage.text,
                )
            ],
        )

    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        select,
    )


def citation(file_id: str, filename: str):
    return AnnotationFileCitation(
        file_id=file_id,
        filename=filename,
        index=0,
        type="file_citation",
    )


def search_result(file_id: str, filename: str, text: str, score=0.8):
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


def test_eligible_evidence_runs_one_selector_call_and_attaches_metric(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "Report.pdf"),
            results=[search_result("file-A", "Report.pdf", ELIGIBLE_TEXT)],
        ),
    )
    selector_calls = []

    def select(passages):
        selector_calls.append(passages)
        return EvidencePresentationSelection()

    presentation = VerifiedEvidencePresentation(
        passage_index=0,
        metrics=[
            VerifiedEvidenceMetric(
                label="Revenue",
                value="28,051",
                period="FY2024",
                unit="EURm",
                source_text="Revenue FY2024 EURm 28,051",
            )
        ],
    )
    monkeypatch.setattr(qa_chain, "select_evidence_presentations", select)
    monkeypatch.setattr(
        qa_chain,
        "verify_evidence_presentations",
        lambda **kwargs: {"file-A": [presentation]},
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert len(selector_calls) == 1
    assert selector_calls[0][0].file_id == "file-A"
    assert selector_calls[0][0].passage_index == 0
    assert selector_calls[0][0].text == ELIGIBLE_TEXT
    assert answer.sources[0].presentations == [presentation]
    assert answer.sources[0].evidence == [ELIGIBLE_TEXT]
    assert answer.source_files == ["Report.pdf"]


def test_verified_table_attaches_to_exact_source_only(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "report.pdf"),
            citation("file-B", "report.pdf"),
            results=[
                search_result("file-A", "report.pdf", ELIGIBLE_TEXT),
                search_result(
                    "file-B",
                    "report.pdf",
                    "Year Revenue\n2023 23,683\n2024 28,051",
                ),
            ],
        ),
    )
    table = VerifiedEvidenceTable(
        columns=["Year", "Revenue"],
        rows=[["2023", "23,683"], ["2024", "28,051"]],
        source_texts=[
            "Year Revenue",
            "2023 23,683",
            "2024 28,051",
        ],
    )
    presentation = VerifiedEvidencePresentation(
        passage_index=0,
        tables=[table],
    )
    monkeypatch.setattr(
        qa_chain,
        "select_evidence_presentations",
        lambda passages: EvidencePresentationSelection(),
    )
    monkeypatch.setattr(
        qa_chain,
        "verify_evidence_presentations",
        lambda **kwargs: {"file-B": [presentation]},
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert [source.file_id for source in answer.sources] == [
        "file-A",
        "file-B",
    ]
    assert answer.sources[0].presentations == []
    assert answer.sources[1].presentations == [presentation]
    assert answer.sources[1].evidence == [
        "Year Revenue\n2023 23,683\n2024 28,051"
    ]


def test_ineligible_prose_skips_structured_selector(monkeypatch) -> None:
    prose = "The agreement remains subject to customary conditions."
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "Agreement.pdf"),
            results=[search_result("file-A", "Agreement.pdf", prose)],
        ),
    )

    def fail_selector(passages):
        raise AssertionError("structured selector must not run")

    monkeypatch.setattr(
        qa_chain,
        "select_evidence_presentations",
        fail_selector,
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert answer.sources[0].evidence == [prose]
    assert answer.sources[0].presentations == []


def test_empty_selection_leaves_successful_answer_unchanged(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "Report.pdf"),
            results=[search_result("file-A", "Report.pdf", ELIGIBLE_TEXT)],
        ),
    )
    monkeypatch.setattr(
        qa_chain,
        "select_evidence_presentations",
        lambda passages: EvidencePresentationSelection(),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert answer.answer == "Supported answer"
    assert answer.source_files == ["Report.pdf"]
    assert answer.sources[0].evidence == [ELIGIBLE_TEXT]
    assert answer.sources[0].presentations == []


def test_all_rejected_candidates_leave_answer_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "Report.pdf"),
            results=[search_result("file-A", "Report.pdf", ELIGIBLE_TEXT)],
        ),
    )
    monkeypatch.setattr(
        qa_chain,
        "select_evidence_presentations",
        lambda passages: EvidencePresentationSelection(),
    )
    monkeypatch.setattr(
        qa_chain,
        "verify_evidence_presentations",
        lambda **kwargs: {},
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert answer.sources[0].presentations == []
    assert answer.sources[0].evidence == [ELIGIBLE_TEXT]


@pytest.mark.parametrize("stage", [
    "build_evidence_presentation_scope",
    "select_evidence_presentations",
    "verify_evidence_presentations",
    "attach_verified_presentations",
])
@pytest.mark.parametrize("with_quotes", [True, False])
def test_unexpected_structured_failure_preserves_all_normal_support(
    monkeypatch, stage, with_quotes,
) -> None:
    monkeypatch.setattr(
        qa_chain, "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "Report.pdf"),
            citation("file-B", "Other.pdf"),
            results=[search_result("file-A", "Report.pdf", ELIGIBLE_TEXT)],
        ),
    )
    selection = QuoteSelection(
        candidates=[QuoteCandidate(
            file_id="file-A", passage_index=0, quote=ELIGIBLE_TEXT,
        )] if with_quotes else [],
        best_support_candidates=[EvidenceExcerptCandidate(
            file_id="file-A", passage_index=0, text=ELIGIBLE_TEXT,
        )],
        additional_context_candidates=[EvidenceExcerptCandidate(
            file_id="file-A", passage_index=0, text="EBITDA 4,905 Margin 17.5%",
        )],
    )
    monkeypatch.setattr(qa_chain, "select_quote_candidates", lambda **kwargs: selection)
    monkeypatch.setattr(
        qa_chain, "select_evidence_presentations",
        lambda passages: EvidencePresentationSelection(),
    )
    supported_answer = qa_chain.run_qa_chain("Question", "vs-test")
    assert supported_answer.status == "success"

    if stage == "attach_verified_presentations":
        monkeypatch.setattr(
            qa_chain, "verify_evidence_presentations",
            lambda **kwargs: {"file-A": [VerifiedEvidencePresentation(passage_index=0)]},
        )
    calls = []

    def fail(*args, **kwargs):
        calls.append(stage)
        raise RuntimeError("Sensitive exception details must not reach the user")

    monkeypatch.setattr(qa_chain, stage, fail)
    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert calls == [stage]
    assert answer == supported_answer.model_copy(update={
        "warnings": [qa_chain.STRUCTURED_PROCESSING_FAILED_WARNING],
    })
    assert answer.source_files == ["Report.pdf", "Other.pdf"]
    assert [item.role for item in answer.sources[0].selected_evidence] == [
        "best_support", "additional_context",
    ]
    assert all(not source.presentations for source in answer.sources)
    assert "Sensitive" not in answer.model_dump_json()


def test_failed_support_gate_prevents_phase_2a(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "Report.pdf"),
            results=[search_result("file-A", "Report.pdf", ELIGIBLE_TEXT)],
        ),
    )
    monkeypatch.setattr(
        qa_chain,
        "build_quote_evidence_scope",
        lambda sources: [],
    )
    called = []
    monkeypatch.setattr(
        qa_chain,
        "select_evidence_presentations",
        lambda passages: called.append(passages)
        or EvidencePresentationSelection(),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "not_found"
    assert answer.answer == qa_chain.BEST_SUPPORT_MISSING_ANSWER
    assert called == []


def test_phase_2a_ineligibility_does_not_prevent_quotations(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "Offer.pdf"),
            results=[search_result("file-A", "Offer.pdf", QUOTE_TEXT)],
        ),
    )
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: QuoteSelection(
            candidates=[
                QuoteCandidate(
                    file_id="file-A", passage_index=0, quote=QUOTE_TEXT
                )
            ],
            best_support_candidates=[
                EvidenceExcerptCandidate(
                    file_id="file-A", passage_index=0, text=QUOTE_TEXT
                )
            ],
        ),
    )

    def fail_selector(passages):
        raise AssertionError("structured selector must not run")

    monkeypatch.setattr(
        qa_chain,
        "select_evidence_presentations",
        fail_selector,
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert len(answer.verified_quotes) == 1
    assert answer.verified_quotes[0].text == QUOTE_TEXT
    assert answer.sources[0].presentations == []


def test_verified_quotes_and_structure_are_attached_independently(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "Offer.pdf"),
            results=[
                search_result("file-A", "Offer.pdf", QUOTE_TEXT, score=0.9),
                search_result("file-A", "Offer.pdf", ELIGIBLE_TEXT, score=0.8),
            ],
        ),
    )
    monkeypatch.setattr(
        qa_chain,
        "select_quote_candidates",
        lambda **kwargs: QuoteSelection(
            candidates=[
                QuoteCandidate(
                    file_id="file-A", passage_index=0, quote=QUOTE_TEXT
                )
            ],
            best_support_candidates=[
                EvidenceExcerptCandidate(
                    file_id="file-A", passage_index=0, text=QUOTE_TEXT
                )
            ],
        ),
    )
    presentation = VerifiedEvidencePresentation(
        passage_index=1,
        metrics=[
            VerifiedEvidenceMetric(
                label="Revenue",
                value="28,051",
                period="FY2024",
                unit="EURm",
                source_text="Revenue FY2024 EURm 28,051",
            )
        ],
    )
    captured = {}
    monkeypatch.setattr(
        qa_chain,
        "select_evidence_presentations",
        lambda passages: EvidencePresentationSelection(),
    )

    def verify(**kwargs):
        captured.update(kwargs)
        return {"file-A": [presentation]}

    monkeypatch.setattr(qa_chain, "verify_evidence_presentations", verify)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert [quote.text for quote in answer.verified_quotes] == [QUOTE_TEXT]
    assert answer.sources[0].presentations == [presentation]
    assert answer.sources[0].evidence == [QUOTE_TEXT, ELIGIBLE_TEXT]
    assert captured["sources"][0].evidence == [QUOTE_TEXT, ELIGIBLE_TEXT]
    assert [item.passage_index for item in captured["passage_scope"]] == [1]
    assert answer.source_files == ["Offer.pdf"]


def test_not_found_answer_never_runs_phase_2a(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(answer="Unsupported answer", results=[]),
    )
    monkeypatch.setattr(
        qa_chain,
        "build_evidence_presentation_scope",
        lambda sources: (_ for _ in ()).throw(
            AssertionError("Phase 2A must not run")
        ),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "not_found"
    assert answer.answer == FALLBACK_ANSWER
    assert answer.answer == "I can not find this information in the VDR documents"
    assert answer.sources == []


def test_retrieval_error_never_runs_phase_2a(monkeypatch) -> None:
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("failure")),
    )
    monkeypatch.setattr(
        qa_chain,
        "build_evidence_presentation_scope",
        lambda sources: (_ for _ in ()).throw(
            AssertionError("Phase 2A must not run")
        ),
    )

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "error"
    assert answer.answer == FALLBACK_ANSWER
    assert answer.sources == []


def test_same_selector_call_converts_parallel_series_for_correct_source(
    monkeypatch,
) -> None:
    horizontal = (
        "Period 2024A 2025E 2026E\n"
        "Revenue 10 12 14\n"
        "Costs 7 8 9"
    )
    monkeypatch.setattr(
        qa_chain,
        "search_vector_store",
        lambda **kwargs: response(
            citation("file-A", "Report.pdf"),
            results=[search_result("file-A", "Report.pdf", horizontal)],
        ),
    )
    selector_calls = []

    def select(passages):
        selector_calls.append(passages)
        return EvidencePresentationSelection(
            parallel_series=[
                EvidenceParallelSeriesCandidate(
                    file_id="file-A",
                    passage_index=0,
                    category_label="Period",
                    categories=["2024A", "2025E", "2026E"],
                    category_source_span="Period 2024A 2025E 2026E",
                    series=[
                        EvidenceSeriesCandidate(
                            label="Revenue",
                            values=["10", "12", "14"],
                            source_span="Revenue 10 12 14",
                        ),
                        EvidenceSeriesCandidate(
                            label="Costs",
                            values=["7", "8", "9"],
                            source_span="Costs 7 8 9",
                        ),
                    ],
                )
            ]
        )

    monkeypatch.setattr(qa_chain, "select_evidence_presentations", select)

    answer = qa_chain.run_qa_chain("Question", "vs-test")

    assert answer.status == "success"
    assert len(selector_calls) == 1
    assert answer.sources[0].file_id == "file-A"
    assert answer.sources[0].presentations[0].tables[0].columns == [
        "Period",
        "Revenue",
        "Costs",
    ]
    assert answer.sources[0].presentations[0].tables[0].rows[0] == [
        "2024A",
        "10",
        "7",
    ]
