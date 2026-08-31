"""Deterministically verify quotation candidates against cited evidence."""

from dataclasses import dataclass

from src.schemas.evidence import SourceReference
from src.schemas.quotation import QuoteCandidate, VerifiedQuote


MAX_VERIFIED_QUOTES = 3
MIN_VERIFIED_QUOTE_CHARS = 20
MAX_VERIFIED_QUOTE_CHARS = 500
MAX_QUOTE_CANDIDATES_TO_PROCESS = 6


@dataclass(frozen=True)
class _SourceDerivedMatch:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _VerifiedQuoteMatch:
    quote: VerifiedQuote
    passage_index: int
    start: int
    end: int
    normalized_text: str


def _normalize_whitespace_with_spans(
    text: str,
) -> tuple[str, list[tuple[int, int]]]:
    """Collapse whitespace while mapping normalized characters to source spans."""

    normalized_characters: list[str] = []
    source_spans: list[tuple[int, int]] = []
    index = 0

    while index < len(text):
        if text[index].isspace():
            whitespace_start = index
            while index < len(text) and text[index].isspace():
                index += 1

            if normalized_characters and index < len(text):
                normalized_characters.append(" ")
                source_spans.append((whitespace_start, index))
            continue

        normalized_characters.append(text[index])
        source_spans.append((index, index + 1))
        index += 1

    return "".join(normalized_characters), source_spans


def _collapse_whitespace(text: str) -> str:
    normalized, _ = _normalize_whitespace_with_spans(text)
    return normalized


def _source_derived_match(
    candidate_text: str,
    normalized_candidate: str,
    passage: str,
) -> _SourceDerivedMatch | None:
    exact_start = passage.find(candidate_text)
    if exact_start >= 0:
        exact_source_text = passage[
            exact_start : exact_start + len(candidate_text)
        ]
        return _SourceDerivedMatch(
            text=_collapse_whitespace(exact_source_text),
            start=exact_start,
            end=exact_start + len(candidate_text),
        )

    normalized_passage, source_spans = _normalize_whitespace_with_spans(
        passage
    )
    normalized_start = normalized_passage.find(normalized_candidate)
    if normalized_start < 0:
        return None

    normalized_end = normalized_start + len(normalized_candidate) - 1
    source_start = source_spans[normalized_start][0]
    source_end = source_spans[normalized_end][1]
    source_text = passage[source_start:source_end]
    return _SourceDerivedMatch(
        text=_collapse_whitespace(source_text),
        start=source_start,
        end=source_end,
    )


def _verify_quote_candidate_with_match(
    candidate: QuoteCandidate,
    quote_sources: list[SourceReference],
) -> _VerifiedQuoteMatch | None:
    """Verify one candidate and retain local passage-match metadata."""

    if (
        not candidate.file_id
        or candidate.file_id.strip() != candidate.file_id
    ):
        return None

    source = next(
        (
            item
            for item in quote_sources
            if item.file_id is not None
            and item.file_id == candidate.file_id
            and item.evidence
        ),
        None,
    )
    if source is None:
        return None

    candidate_text = candidate.quote.strip()
    normalized_candidate = _collapse_whitespace(candidate_text)
    if not (
        MIN_VERIFIED_QUOTE_CHARS
        <= len(normalized_candidate)
        <= MAX_VERIFIED_QUOTE_CHARS
    ):
        return None

    for passage_index, passage in enumerate(source.evidence):
        source_match = _source_derived_match(
            candidate_text,
            normalized_candidate,
            passage,
        )
        if source_match is not None:
            quote = VerifiedQuote(
                file_id=candidate.file_id,
                source_display_name=source.display_name,
                text=source_match.text,
            )
            return _VerifiedQuoteMatch(
                quote=quote,
                passage_index=passage_index,
                start=source_match.start,
                end=source_match.end,
                normalized_text=_collapse_whitespace(quote.text),
            )

    return None


def verify_quote_candidate(
    candidate: QuoteCandidate,
    quote_sources: list[SourceReference],
) -> VerifiedQuote | None:
    """Verify one candidate and return only source-derived quotation text."""

    verified = _verify_quote_candidate_with_match(candidate, quote_sources)
    return None if verified is None else verified.quote


def _is_contained_by(
    candidate: _VerifiedQuoteMatch,
    other: _VerifiedQuoteMatch,
) -> bool:
    """Return whether another nonidentical match wholly contains a candidate."""

    return (
        candidate.quote.file_id == other.quote.file_id
        and candidate.passage_index == other.passage_index
        and candidate.normalized_text != other.normalized_text
        and other.start <= candidate.start
        and candidate.end <= other.end
    )


def verify_quote_candidates(
    candidates: list[QuoteCandidate],
    quote_sources: list[SourceReference],
    max_quotes: int = MAX_VERIFIED_QUOTES,
) -> list[VerifiedQuote]:
    """Verify, deduplicate, and limit quotation candidates in stable order."""

    quote_limit = min(max(max_quotes, 0), MAX_VERIFIED_QUOTES)
    if quote_limit == 0:
        return []

    verified_matches: list[_VerifiedQuoteMatch] = []
    seen_text: set[str] = set()

    for candidate in candidates[:MAX_QUOTE_CANDIDATES_TO_PROCESS]:
        verified = _verify_quote_candidate_with_match(candidate, quote_sources)
        if verified is None:
            continue

        if verified.normalized_text in seen_text:
            continue
        seen_text.add(verified.normalized_text)
        verified_matches.append(verified)

    survivors = [
        candidate
        for index, candidate in enumerate(verified_matches)
        if not any(
            index != other_index and _is_contained_by(candidate, other)
            for other_index, other in enumerate(verified_matches)
        )
    ]

    return [match.quote for match in survivors[:quote_limit]]
