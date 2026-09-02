"""Verify and persist model-selected evidence excerpts locally."""

from dataclasses import dataclass

from src.schemas.evidence import SourceReference, VerifiedEvidenceExcerpt
from src.schemas.quotation import EvidenceExcerptCandidate, QuoteSelection
from src.validation.quote_verifier import (
    _collapse_whitespace,
    _source_derived_match,
)


MAX_VERIFIED_BEST_PER_SOURCE = 1
MAX_VERIFIED_ADDITIONAL_PER_SOURCE = 3


@dataclass(frozen=True)
class EvidenceSelectionVerification:
    """Persisted sources and aggregate support counts."""

    sources: list[SourceReference]
    best_support_count: int
    additional_context_count: int


def _verify_candidate(
    candidate: EvidenceExcerptCandidate,
    sources: list[SourceReference],
) -> tuple[int, VerifiedEvidenceExcerpt, str] | None:
    if (
        not candidate.file_id
        or candidate.file_id.strip() != candidate.file_id
    ):
        return None

    matching_sources = [
        (index, source)
        for index, source in enumerate(sources)
        if source.file_id == candidate.file_id
    ]
    if len(matching_sources) != 1:
        return None

    source_index, source = matching_sources[0]
    passage_index = candidate.passage_index
    if (
        type(passage_index) is not int
        or passage_index < 0
        or passage_index >= len(source.evidence)
    ):
        return None

    candidate_text = candidate.text.strip()
    normalized_candidate = _collapse_whitespace(candidate_text)
    if not normalized_candidate:
        return None

    match = _source_derived_match(
        candidate_text,
        normalized_candidate,
        source.evidence[passage_index],
    )
    if match is None:
        return None

    normalized_match = _collapse_whitespace(match.text)
    return (
        source_index,
        VerifiedEvidenceExcerpt(
            role="best_support",
            passage_index=passage_index,
            text=match.text,
        ),
        normalized_match,
    )


def verify_evidence_selection(
    selection: QuoteSelection,
    sources: list[SourceReference],
) -> EvidenceSelectionVerification:
    """Verify candidates by identified passage and mark selection completed."""

    selected_by_source: list[list[VerifiedEvidenceExcerpt]] = [
        [] for _ in sources
    ]
    seen_by_source: list[set[str]] = [set() for _ in sources]
    best_counts = [0 for _ in sources]
    additional_counts = [0 for _ in sources]

    for candidate in selection.best_support_candidates:
        verified = _verify_candidate(candidate, sources)
        if verified is None:
            continue
        source_index, excerpt, normalized_text = verified
        if best_counts[source_index] >= MAX_VERIFIED_BEST_PER_SOURCE:
            continue
        if normalized_text in seen_by_source[source_index]:
            continue

        selected_by_source[source_index].append(excerpt)
        seen_by_source[source_index].add(normalized_text)
        best_counts[source_index] += 1

    for candidate in selection.additional_context_candidates:
        verified = _verify_candidate(candidate, sources)
        if verified is None:
            continue
        source_index, excerpt, normalized_text = verified
        if (
            additional_counts[source_index]
            >= MAX_VERIFIED_ADDITIONAL_PER_SOURCE
        ):
            continue
        if normalized_text in seen_by_source[source_index]:
            continue

        additional_excerpt = excerpt.model_copy(
            update={"role": "additional_context"}
        )
        selected_by_source[source_index].append(additional_excerpt)
        seen_by_source[source_index].add(normalized_text)
        additional_counts[source_index] += 1

    verified_sources = [
        source.model_copy(
            update={
                "evidence_selection_status": "completed",
                "selected_evidence": selected_by_source[index],
            }
        )
        for index, source in enumerate(sources)
    ]
    return EvidenceSelectionVerification(
        sources=verified_sources,
        best_support_count=sum(best_counts),
        additional_context_count=sum(additional_counts),
    )
