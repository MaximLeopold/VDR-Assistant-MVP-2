"""Select bounded quotation candidates from cited retrieved evidence."""

import logging
from pathlib import Path

from openai import APIError
from pydantic import ValidationError

from src.config.settings import OPENAI_MODEL
from src.retrieval.openai_file_search import get_openai_client
from src.schemas.evidence import SourceReference
from src.schemas.quotation import QuoteCandidate, QuoteSelection


MAX_QUOTE_SOURCES = 4
MAX_QUOTE_PASSAGES_PER_SOURCE = 2
MAX_QUOTE_PASSAGE_CHARS = 2500
MAX_QUOTE_ANSWER_CHARS = 8000
MAX_QUOTE_CANDIDATES_TO_PROCESS = 6
MAX_QUOTE_OUTPUT_TOKENS = 800

PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "quote_selection.md"
)
LOGGER = logging.getLogger(__name__)


def _usable_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None


def build_quote_evidence_scope(
    sources: list[SourceReference],
) -> list[SourceReference]:
    """Return cited sources with evidence bounded for quote selection."""

    bounded_sources: list[SourceReference] = []

    for source in sources:
        file_id = _usable_text(source.file_id)
        if file_id is None:
            continue

        bounded_evidence: list[str] = []
        for passage in source.evidence:
            normalized = _usable_text(passage)
            if normalized is None:
                continue

            bounded_evidence.append(normalized[:MAX_QUOTE_PASSAGE_CHARS])
            if len(bounded_evidence) == MAX_QUOTE_PASSAGES_PER_SOURCE:
                break

        if not bounded_evidence:
            continue

        bounded_sources.append(
            SourceReference(
                file_id=file_id,
                display_name=source.display_name,
                evidence=bounded_evidence,
            )
        )
        if len(bounded_sources) == MAX_QUOTE_SOURCES:
            break

    return bounded_sources


def _build_quote_selector_input(
    answer: str,
    quote_sources: list[SourceReference],
) -> str:
    """Build a selector input without filenames, paths, scores, or uncited data."""

    sections = [
        "Answer:",
        answer.strip()[:MAX_QUOTE_ANSWER_CHARS],
        "",
        "Cited source evidence:",
    ]

    for source in quote_sources:
        sections.extend(["", f"Source ID: {source.file_id}"])
        for index, passage in enumerate(source.evidence, start=1):
            sections.extend([f"Passage {index}:", passage])

    return "\n".join(sections)


def select_quote_candidates(
    answer: str,
    quote_sources: list[SourceReference],
) -> list[QuoteCandidate]:
    """Request structured candidates, returning no candidates on expected failures."""

    if not quote_sources:
        return []

    instructions = PROMPT_PATH.read_text(encoding="utf-8")
    selector_input = _build_quote_selector_input(answer, quote_sources)
    client = get_openai_client()

    try:
        response = client.responses.parse(
            model=OPENAI_MODEL,
            input=selector_input,
            instructions=instructions,
            text_format=QuoteSelection,
            max_output_tokens=MAX_QUOTE_OUTPUT_TOKENS,
        )
    except (APIError, ValidationError) as error:
        LOGGER.warning(
            "Quote selection omitted after %s.",
            type(error).__name__,
        )
        return []

    if getattr(response, "status", None) != "completed":
        return []

    selection = getattr(response, "output_parsed", None)
    if not isinstance(selection, QuoteSelection):
        return []

    return list(selection.candidates[:MAX_QUOTE_CANDIDATES_TO_PROCESS])
