from src.schemas.answer import VDRAnswer
from src.schemas.quotation import VerifiedQuote


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
