from src.schemas.evidence import SourceReference, VerifiedEvidenceExcerpt
from src.schemas.quotation import EvidenceExcerptCandidate, QuoteSelection
from src.validation.evidence_selection_verifier import verify_evidence_selection


def candidate(file_id="file-A", passage_index=0, text="Direct support"):
    return EvidenceExcerptCandidate(
        file_id=file_id,
        passage_index=passage_index,
        text=text,
    )


def source(file_id="file-A", evidence=None):
    return SourceReference(
        file_id=file_id,
        display_name=f"{file_id}.pdf",
        evidence=evidence or ["Direct support. Additional context."],
    )


def test_verifies_source_derived_text_and_preserves_raw_evidence() -> None:
    raw = "Direct\n support. Additional   context."
    sources = [source(evidence=[raw])]
    selection = QuoteSelection(
        best_support_candidates=[candidate(text="Direct support")],
        additional_context_candidates=[candidate(text="Additional context")],
    )

    verified = verify_evidence_selection(selection, sources)

    assert verified.best_support_count == 1
    assert verified.additional_context_count == 1
    assert verified.sources[0].evidence == [raw]
    assert verified.sources[0].evidence_selection_status == "completed"
    assert verified.sources[0].selected_evidence == [
        VerifiedEvidenceExcerpt(
            role="best_support", passage_index=0, text="Direct support"
        ),
        VerifiedEvidenceExcerpt(
            role="additional_context",
            passage_index=0,
            text="Additional context",
        ),
    ]


def test_wrong_passage_identity_is_rejected_without_substitution() -> None:
    selection = QuoteSelection(
        best_support_candidates=[candidate(passage_index=0, text="Target text")]
    )
    sources = [source(evidence=["Not here", "Target text"])]

    verified = verify_evidence_selection(selection, sources)

    assert verified.best_support_count == 0
    assert verified.sources[0].selected_evidence == []


def test_invalid_early_candidates_do_not_block_later_valid_candidates() -> None:
    raw = "Best valid. One context. Two context. Three context. Four context."
    selection = QuoteSelection(
        best_support_candidates=[
            candidate(file_id="wrong", text="Best valid"),
            candidate(text="Best valid"),
            candidate(text="One context"),
        ],
        additional_context_candidates=[
            candidate(text="missing"),
            candidate(text="One context"),
            candidate(text="Two context"),
            candidate(text="Three context"),
            candidate(text="Four context"),
        ],
    )

    verified = verify_evidence_selection(selection, [source(evidence=[raw])])

    assert verified.best_support_count == 1
    assert verified.additional_context_count == 3
    assert [item.text for item in verified.sources[0].selected_evidence] == [
        "Best valid",
        "One context",
        "Two context",
        "Three context",
    ]


def test_completed_empty_is_distinct_from_legacy_absence_for_every_source() -> None:
    sources = [source("file-A"), source("file-B")]

    verified = verify_evidence_selection(QuoteSelection(), sources)

    assert all(
        item.evidence_selection_status == "completed"
        for item in verified.sources
    )
    assert all(item.selected_evidence == [] for item in verified.sources)
    assert all(original.evidence_selection_status == "legacy" for original in sources)
