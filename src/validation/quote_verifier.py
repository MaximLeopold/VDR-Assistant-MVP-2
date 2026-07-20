"""Deterministically verify quotation candidates against cited evidence."""

from src.schemas.evidence import SourceReference
from src.schemas.quotation import QuoteCandidate, VerifiedQuote


MAX_VERIFIED_QUOTES = 2
MAX_VERIFIED_QUOTES_PER_SOURCE = 1
MIN_VERIFIED_QUOTE_CHARS = 20
MAX_VERIFIED_QUOTE_CHARS = 500
MAX_QUOTE_CANDIDATES_TO_PROCESS = 6


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
) -> str | None:
    exact_start = passage.find(candidate_text)
    if exact_start >= 0:
        exact_source_text = passage[
            exact_start : exact_start + len(candidate_text)
        ]
        return _collapse_whitespace(exact_source_text)

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
    return _collapse_whitespace(source_text)


def verify_quote_candidate(
    candidate: QuoteCandidate,
    quote_sources: list[SourceReference],
) -> VerifiedQuote | None:
    """Verify one candidate and return only source-derived quotation text."""

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

    for passage in source.evidence:
        source_text = _source_derived_match(
            candidate_text,
            normalized_candidate,
            passage,
        )
        if source_text is not None:
            return VerifiedQuote(
                file_id=candidate.file_id,
                source_display_name=source.display_name,
                text=source_text,
            )

    return None


def verify_quote_candidates(
    candidates: list[QuoteCandidate],
    quote_sources: list[SourceReference],
    max_quotes: int = MAX_VERIFIED_QUOTES,
) -> list[VerifiedQuote]:
    """Verify candidates in order with answer- and source-level limits."""

    quote_limit = min(max(max_quotes, 0), MAX_VERIFIED_QUOTES)
    if quote_limit == 0:
        return []

    verified_quotes: list[VerifiedQuote] = []
    verified_per_source: dict[str, int] = {}

    for candidate in candidates[:MAX_QUOTE_CANDIDATES_TO_PROCESS]:
        if len(verified_quotes) == quote_limit:
            break

        if (
            verified_per_source.get(candidate.file_id, 0)
            >= MAX_VERIFIED_QUOTES_PER_SOURCE
        ):
            continue

        verified = verify_quote_candidate(candidate, quote_sources)
        if verified is None:
            continue

        verified_quotes.append(verified)
        verified_per_source[verified.file_id] = (
            verified_per_source.get(verified.file_id, 0) + 1
        )

    return verified_quotes
