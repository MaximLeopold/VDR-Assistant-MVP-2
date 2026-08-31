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
        if passage != "first":
            return None
        return quote_verifier._SourceDerivedMatch(
            text="Source-derived first match",
            start=0,
            end=len(passage),
        )

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

    monkeypatch.setattr(
        quote_verifier,
        "_verify_quote_candidate_with_match",
        reject,
    )
    candidates = [candidate(file_id=f"file-{index}") for index in range(8)]

    assert quote_verifier.verify_quote_candidates(candidates, [source()]) == []
    assert inspected == [f"file-{index}" for index in range(6)]


def test_limits_to_three_quotes_and_preserves_selector_order() -> None:
    sources = [
        source("file-A", ["First sufficiently long quotation text."]),
        source("file-B", ["Second sufficiently long quotation text."]),
        source("file-C", ["Third sufficiently long quotation text."]),
        source("file-D", ["Fourth sufficiently long quotation text."]),
    ]
    candidates = [
        candidate("Second sufficiently long quotation text.", "file-B"),
        candidate("First sufficiently long quotation text.", "file-A"),
        candidate("Third sufficiently long quotation text.", "file-C"),
        candidate("Fourth sufficiently long quotation text.", "file-D"),
    ]

    verified = quote_verifier.verify_quote_candidates(candidates, sources)

    assert [quote.file_id for quote in verified] == [
        "file-B",
        "file-A",
        "file-C",
    ]


def test_three_disjoint_quotes_from_one_passage_are_kept() -> None:
    first = "The first verified quotation is long enough."
    second = "The second verified quotation is also long enough."
    third = "The third verified quotation remains distinct and useful."
    sources = [source(evidence=[f"{first} {second} {third}"])]

    verified = quote_verifier.verify_quote_candidates(
        [candidate(first), candidate(second), candidate(third)],
        sources,
    )

    assert [quote.text for quote in verified] == [first, second, third]


def test_identical_wording_from_different_file_ids_keeps_first_source() -> None:
    shared = "Identical verified wording exists in both source documents."
    sources = [
        source("file-A", [shared], "First source"),
        source("file-B", [shared], "Second source"),
    ]

    verified = quote_verifier.verify_quote_candidates(
        [candidate(shared, "file-A"), candidate(shared, "file-B")],
        sources,
    )

    assert verified == [
        VerifiedQuote(
            file_id="file-A",
            source_display_name="First source",
            text=shared,
        )
    ]


def test_whitespace_equivalent_duplicates_are_kept_once_overall() -> None:
    normalized = "Revenue increased to EUR 42 million in the period."
    sources = [
        source("file-A", ["Revenue increased to\nEUR 42 million in the period."]),
        source("file-B", ["Revenue  increased to EUR 42 million in the period."]),
    ]

    verified = quote_verifier.verify_quote_candidates(
        [candidate(normalized, "file-A"), candidate(normalized, "file-B")],
        sources,
    )

    assert len(verified) == 1
    assert verified[0].file_id == "file-A"
    assert verified[0].text == normalized


@pytest.mark.parametrize("candidate_order", ["short-first", "long-first"])
def test_contained_quote_is_replaced_by_longer_match_regardless_of_order(
    candidate_order: str,
) -> None:
    short = "completion of due diligence remains required"
    long = f"Satisfactory {short} before closing."
    sources = [source(evidence=[f"Prefix. {long} Suffix."])]
    quotes = [candidate(short), candidate(long)]
    if candidate_order == "long-first":
        quotes.reverse()

    verified = quote_verifier.verify_quote_candidates(quotes, sources)

    assert [quote.text for quote in verified] == [long]


def test_containment_applies_only_within_the_same_source_passage() -> None:
    short = "completion of due diligence remains required"
    long = f"Satisfactory {short} before closing."
    sources = [source(evidence=[short, long])]

    verified = quote_verifier.verify_quote_candidates(
        [candidate(short), candidate(long)],
        sources,
    )

    assert [quote.text for quote in verified] == [short, long]


def test_repeated_text_uses_first_local_match_deterministically() -> None:
    short = "completion of due diligence remains required"
    long = f"Satisfactory {short} before closing."
    passage = f"{short} elsewhere. Later, {long}"

    verified = quote_verifier.verify_quote_candidates(
        [candidate(short), candidate(long)],
        [source(evidence=[passage])],
    )

    assert [quote.text for quote in verified] == [short, long]


def test_partial_overlap_is_not_rejected() -> None:
    passage = "Alpha section provides material support and context for closing."
    first = "Alpha section provides material support and context"
    second = "material support and context for closing."

    verified = quote_verifier.verify_quote_candidates(
        [candidate(first), candidate(second)],
        [source(evidence=[passage])],
    )

    assert [quote.text for quote in verified] == [first, second]


def test_candidate_surplus_fills_three_slots_after_rejections() -> None:
    first = "The first accepted quotation contains useful support."
    second = "The second accepted quotation contains different support."
    third = "The third accepted quotation contains complementary support."
    passage = f"{first} {second} {third}"
    candidates = [
        candidate("This fabricated quotation is not in the passage."),
        candidate(first),
        candidate(f"The first accepted quotation\ncontains useful support."),
        candidate("accepted quotation contains useful support"),
        candidate(second),
        candidate(third),
    ]

    verified = quote_verifier.verify_quote_candidates(
        candidates,
        [source(evidence=[passage])],
    )

    assert [quote.text for quote in verified] == [first, second, third]


def test_all_bounded_candidates_are_checked_before_final_limit(
    monkeypatch,
) -> None:
    inspected = []

    def accept(candidate, quote_sources):
        inspected.append(candidate.file_id)
        quote = VerifiedQuote(
            file_id=candidate.file_id,
            source_display_name=candidate.file_id,
            text=f"{BASE_QUOTE} {candidate.file_id}",
        )
        return quote_verifier._VerifiedQuoteMatch(
            quote=quote,
            passage_index=0,
            start=0,
            end=len(quote.text),
            normalized_text=quote.text,
        )

    monkeypatch.setattr(
        quote_verifier,
        "_verify_quote_candidate_with_match",
        accept,
    )
    candidates = [candidate(file_id=f"file-{index}") for index in range(5)]

    verified = quote_verifier.verify_quote_candidates(candidates, [source()])

    assert len(verified) == 3
    assert inspected == ["file-0", "file-1", "file-2", "file-3", "file-4"]
