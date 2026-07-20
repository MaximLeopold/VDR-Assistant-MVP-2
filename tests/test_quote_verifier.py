import pytest

from src.schemas.evidence import SourceReference
from src.schemas.quotation import QuoteCandidate, VerifiedQuote
from src.validation import quote_verifier


BASE_QUOTE = "Subject to satisfactory completion of due diligence."


def source(
    file_id: str | None = "file-A",
    evidence: list[str] | None = None,
    display_name: str = "VDR → 03 NBO → Offer.pdf",
) -> SourceReference:
    return SourceReference(
        file_id=file_id,
        display_name=display_name,
        evidence=[BASE_QUOTE] if evidence is None else evidence,
    )


def candidate(
    quote: str = BASE_QUOTE,
    file_id: str = "file-A",
) -> QuoteCandidate:
    return QuoteCandidate(file_id=file_id, quote=quote)


def test_exact_substring_verifies_with_source_derived_text() -> None:
    verified = quote_verifier.verify_quote_candidate(
        candidate(f"  {BASE_QUOTE}  "),
        [source(evidence=[f"Prefix {BASE_QUOTE} Suffix"])],
    )

    assert verified == VerifiedQuote(
        file_id="file-A",
        source_display_name="VDR → 03 NBO → Offer.pdf",
        text=BASE_QUOTE,
    )


@pytest.mark.parametrize(
    ("candidate_value", "candidate_file_id", "sources"),
    [
        (BASE_QUOTE, "file-B", [source()]),
        (BASE_QUOTE, "file-uncited", [source(), source("file-B")]),
        (BASE_QUOTE, "", [source()]),
        (BASE_QUOTE, "", [source("", [BASE_QUOTE])]),
        (BASE_QUOTE, " file-A ", [source()]),
        (BASE_QUOTE, "file-A", [source(evidence=[])]),
        ("", "file-A", [source()]),
        ("   ", "file-A", [source()]),
        ("This candidate is absent from the source.", "file-A", [source()]),
        (BASE_QUOTE.lower(), "file-A", [source()]),
        (
            "Subject to satisfactory completion of due diligence!",
            "file-A",
            [source()],
        ),
        ("Revenue was EUR 43 million in 2025.", "file-A", [source(evidence=["Revenue was EUR 42 million in 2025."])]),
        ("Revenue was EUR 42 million in 2026.", "file-A", [source(evidence=["Revenue was EUR 42 million in 2025."])]),
        ("Revenue was EUR 42 million in 2025.", "file-A", [source(evidence=["Revenue was €42 million in 2025."])]),
        ("The transaction is expected to close.", "file-A", [source(evidence=["The transaction may close after approval."])]),
    ],
)
def test_invalid_or_unverifiable_candidate_fails(
    candidate_value,
    candidate_file_id,
    sources,
) -> None:
    assert quote_verifier.verify_quote_candidate(
        candidate(candidate_value, candidate_file_id),
        sources,
    ) is None


@pytest.mark.parametrize(
    "source_text",
    [
        "Subject to satisfactory\ncompletion of due diligence.",
        "Subject  to   satisfactory completion of due diligence.",
        "Subject\tto satisfactory completion of due diligence.",
        "Subject \n\tto satisfactory\r\ncompletion of due diligence.",
    ],
)
def test_whitespace_only_differences_verify(source_text: str) -> None:
    verified = quote_verifier.verify_quote_candidate(
        candidate(),
        [source(evidence=[source_text])],
    )

    assert verified is not None
    assert verified.text == BASE_QUOTE


def test_normalized_match_recovers_and_collapses_original_source_span() -> None:
    candidate_text = (
        "Board Approval: Revenue was €42.6 million — up 12.5%."
    )
    passage = (
        "Prefix Board Approval:\nRevenue  was €42.6 million — up 12.5%. Suffix"
    )

    verified = quote_verifier.verify_quote_candidate(
        candidate(candidate_text),
        [source(evidence=[passage])],
    )

    assert verified is not None
    assert verified.text == candidate_text
    assert "Approval:" in verified.text
    assert "€42.6" in verified.text
    assert "—" in verified.text
    assert "12.5%" in verified.text


def test_unicode_symbol_substitution_does_not_verify() -> None:
    assert quote_verifier.verify_quote_candidate(
        candidate("Revenue was EUR 42.6 million — up 12.5%."),
        [source(evidence=["Revenue was €42.6 million — up 12.5%."])],
    ) is None


def test_highest_ranked_passage_is_checked_first(monkeypatch) -> None:
    calls = []

    def fake_match(candidate_text, normalized_candidate, passage):
        calls.append(passage)
        return "Source-derived first match" if passage == "first" else None

    monkeypatch.setattr(quote_verifier, "_source_derived_match", fake_match)

    verified = quote_verifier.verify_quote_candidate(
        candidate(),
        [source(evidence=["first", "second"])],
    )

    assert verified is not None
    assert verified.text == "Source-derived first match"
    assert calls == ["first"]


@pytest.mark.parametrize(
    ("length", "should_verify"),
    [
        (quote_verifier.MIN_VERIFIED_QUOTE_CHARS - 1, False),
        (quote_verifier.MIN_VERIFIED_QUOTE_CHARS, True),
        (quote_verifier.MAX_VERIFIED_QUOTE_CHARS, True),
        (quote_verifier.MAX_VERIFIED_QUOTE_CHARS + 1, False),
    ],
)
def test_normalized_candidate_length_limits(
    length: int,
    should_verify: bool,
) -> None:
    text = "x" * length
    verified = quote_verifier.verify_quote_candidate(
        candidate(text),
        [source(evidence=[text])],
    )

    assert (verified is not None) is should_verify


def test_no_more_than_six_candidates_are_inspected(monkeypatch) -> None:
    inspected = []

    def reject(candidate, quote_sources):
        inspected.append(candidate.file_id)
        return None

    monkeypatch.setattr(quote_verifier, "verify_quote_candidate", reject)
    candidates = [candidate(file_id=f"file-{index}") for index in range(8)]

    assert quote_verifier.verify_quote_candidates(candidates, [source()]) == []
    assert inspected == [f"file-{index}" for index in range(6)]


def test_limits_to_two_quotes_and_preserves_selector_order() -> None:
    sources = [
        source("file-A", ["First sufficiently long quotation text."]),
        source("file-B", ["Second sufficiently long quotation text."]),
        source("file-C", ["Third sufficiently long quotation text."]),
    ]
    candidates = [
        candidate("Second sufficiently long quotation text.", "file-B"),
        candidate("First sufficiently long quotation text.", "file-A"),
        candidate("Third sufficiently long quotation text.", "file-C"),
    ]

    verified = quote_verifier.verify_quote_candidates(candidates, sources)

    assert [quote.file_id for quote in verified] == ["file-B", "file-A"]


def test_only_first_verified_quote_per_source_is_kept() -> None:
    first = "The first verified quotation is long enough."
    nested = "first verified quotation is long enough"
    overlapping = "The first verified quotation is long enough. Another clause."
    sources = [source(evidence=[f"{overlapping} Final clause."])]

    verified = quote_verifier.verify_quote_candidates(
        [candidate(first), candidate(nested), candidate(overlapping)],
        sources,
    )

    assert [quote.text for quote in verified] == [first]


def test_identical_wording_from_different_file_ids_may_remain() -> None:
    shared = "Identical verified wording exists in both source documents."
    sources = [source("file-A", [shared]), source("file-B", [shared])]

    verified = quote_verifier.verify_quote_candidates(
        [candidate(shared, "file-A"), candidate(shared, "file-B")],
        sources,
    )

    assert [quote.file_id for quote in verified] == ["file-A", "file-B"]
    assert [quote.text for quote in verified] == [shared, shared]


def test_verification_stops_after_final_limit(monkeypatch) -> None:
    inspected = []

    def accept(candidate, quote_sources):
        inspected.append(candidate.file_id)
        return VerifiedQuote(
            file_id=candidate.file_id,
            source_display_name=candidate.file_id,
            text=BASE_QUOTE,
        )

    monkeypatch.setattr(quote_verifier, "verify_quote_candidate", accept)
    candidates = [candidate(file_id=f"file-{index}") for index in range(5)]

    verified = quote_verifier.verify_quote_candidates(candidates, [source()])

    assert len(verified) == 2
    assert inspected == ["file-0", "file-1"]
