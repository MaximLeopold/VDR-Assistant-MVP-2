import pytest
from pydantic import ValidationError

from src.schemas.answer import VDRAnswer
from src.schemas.quotation import (
    EvidenceExcerptCandidate,
    QuoteCandidate,
    QuoteSelection,
    VerifiedQuote,
)


def test_vdr_answer_defaults_verified_quotes_to_empty_list() -> None:
    answer = VDRAnswer(answer="Answer")

    assert answer.verified_quotes == []


def test_old_payload_without_verified_quotes_still_validates() -> None:
    answer = VDRAnswer.model_validate(
        {
            "answer": "Legacy answer",
            "source_files": ["Report.pdf"],
            "status": "success",
            "workflow": "qa",
        }
    )

    assert answer.verified_quotes == []


def test_legacy_quotes_remain_string_list_and_validate() -> None:
    answer = VDRAnswer.model_validate(
        {
            "answer": "Legacy answer",
            "source_files": ["Report.pdf"],
            "quotes": ["Legacy quote"],
        }
    )

    assert answer.quotes == ["Legacy quote"]
    assert all(isinstance(quote, str) for quote in answer.quotes)
    assert answer.verified_quotes == []


def test_verified_quote_serializes_and_deserializes() -> None:
    answer = VDRAnswer(
        answer="Supported answer",
        source_files=["VDR → Finance → Report.pdf"],
        verified_quotes=[
            VerifiedQuote(
                file_id="file-A",
                source_display_name="VDR → Finance → Report.pdf",
                text="Revenue increased from €38.1 million to €42.6 million.",
            )
        ],
    )

    payload = answer.model_dump(mode="json")
    restored = VDRAnswer.model_validate(payload)

    assert restored == answer
    assert restored.verified_quotes[0].text == (
        "Revenue increased from €38.1 million to €42.6 million."
    )


@pytest.mark.parametrize("passage_index", ["0", 0.0, True, -1])
def test_transient_candidates_reject_non_strict_or_negative_indices(
    passage_index,
) -> None:
    with pytest.raises(ValidationError):
        QuoteCandidate(
            file_id="file-A",
            passage_index=passage_index,
            quote="Source text",
        )


def test_combined_selection_enforces_candidate_surplus_bounds() -> None:
    quote = QuoteCandidate(
        file_id="file-A",
        passage_index=0,
        quote="Source text",
    )
    excerpt = EvidenceExcerptCandidate(
        file_id="file-A",
        passage_index=0,
        text="Source text",
    )

    with pytest.raises(ValidationError):
        QuoteSelection(candidates=[quote] * 7)
    with pytest.raises(ValidationError):
        QuoteSelection(best_support_candidates=[excerpt] * 13)
    with pytest.raises(ValidationError):
        QuoteSelection(additional_context_candidates=[excerpt] * 25)
