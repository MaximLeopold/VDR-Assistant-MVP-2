"""Select bounded structured-presentation candidates from cited evidence."""

import logging
import re
from pathlib import Path

from openai import (
    APIError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)
from pydantic import ValidationError

from src.config.settings import OPENAI_MODEL
from src.retrieval.openai_file_search import get_openai_client
from src.schemas.evidence import SourceReference
from src.schemas.evidence_presentation import (
    MAX_CANDIDATE_METRICS,
    MAX_CANDIDATE_TABLE_CELLS,
    MAX_CANDIDATE_TABLE_COLUMNS,
    MAX_CANDIDATE_TABLE_ROWS,
    MAX_CANDIDATE_TABLES,
    MAX_PARALLEL_CANDIDATES,
    MAX_PRESENTATION_CHARS_PER_PASSAGE,
    EvidencePresentationPassage,
    EvidencePresentationSelection,
)


MAX_PRESENTATION_SOURCES = 4
MAX_PRESENTATION_PASSAGES_PER_SOURCE = 2
MAX_PRESENTATION_TOTAL_CHARS = 16000
MAX_PRESENTATION_OUTPUT_TOKENS = 5000

PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "evidence_presentation.md"
)
LOGGER = logging.getLogger(__name__)

_ALPHABETIC_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_ALPHABETIC_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_SENTENCE_TERMINATOR_RE = re.compile(r"[.!?]\s*$")
_NUMERIC_TOKEN_RE = re.compile(
    r"(?<![\w])"
    r"(?:\(?[-+]?"
    r"(?:\d{1,3}(?:[,.']\d{3})+|\d+(?:[,.]\d+)?)"
    r"(?:\s?%)?\)?)"
    r"(?![\w])"
)
_YEAR_OR_DATE_RE = re.compile(
    r"\b(?:FY\s*)?(?:19|20)\d{2}\b"
    r"|\b\d{1,2}[./-]\d{1,2}[./-](?:\d{2}|\d{4})\b",
    re.IGNORECASE,
)
_FINANCIAL_CATEGORY_RE = re.compile(
    r"(?<![\w])(?:"
    r"(?:19|20)\d{2}(?:PF|[AEF])?"
    r"|FY[ \t]*(?:\d{2}|(?:19|20)\d{2})(?:PF|[AEF])?"
    r"|(?:Q[1-4]|H[12])[ \t]+(?:\d{2}|(?:19|20)\d{2})(?:PF|[AEF])?"
    r"|LTM|NTM|Actual|Estimate|Forecast|Budget|Plan"
    r"|Base|Upside|Downside"
    r")(?![\w])",
    re.IGNORECASE,
)
_CURRENCY_OR_PERCENT_RE = re.compile(
    r"[%$€£¥]"
    r"|\b(?:USD|EUR|GBP|CHF|JPY|CNY|RMB|AUD|CAD|SEK|NOK|DKK)"
    r"(?:k|m|mn|bn|b)?\b"
    r"|\b(?:thousand|million|billion|percent|percentage)\b",
    re.IGNORECASE,
)


def _numeric_spans(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in _NUMERIC_TOKEN_RE.finditer(text)]


def _contains_value_outside_period(text: str) -> bool:
    period_spans = [match.span() for match in _YEAR_OR_DATE_RE.finditer(text)]
    for number_start, number_end in _numeric_spans(text):
        if not any(
            period_start <= number_start and number_end <= period_end
            for period_start, period_end in period_spans
        ):
            return True
    return False


def is_structured_evidence_candidate(text: str) -> bool:
    """Return whether raw text is plausibly worth a structuring attempt."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not text.strip():
        return False

    has_alphabetic = _ALPHABETIC_RE.search(text) is not None
    numeric_count = len(_numeric_spans(text))
    period_count = len(_YEAR_OR_DATE_RE.findall(text))
    has_currency_or_percent = _CURRENCY_OR_PERCENT_RE.search(text) is not None
    financial_category_count = len(_FINANCIAL_CATEGORY_RE.findall(text))

    if (
        has_alphabetic
        and financial_category_count >= 2
        and numeric_count >= 2
    ):
        return True

    if has_alphabetic and numeric_count >= 4:
        return True
    if period_count >= 3:
        return True
    if has_alphabetic and numeric_count >= 3 and has_currency_or_percent:
        return True

    if (
        has_alphabetic
        and period_count >= 1
        and has_currency_or_percent
        and _contains_value_outside_period(text)
    ):
        return True

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) == 1 and len(lines[0]) <= 160:
        alphabetic_words = _ALPHABETIC_WORD_RE.findall(lines[0])
        lacks_sentence_terminator = (
            _SENTENCE_TERMINATOR_RE.search(lines[0]) is None
        )
        if (
            lacks_sentence_terminator
            and period_count >= 1
            and len(alphabetic_words) <= 8
            and _contains_value_outside_period(text)
        ):
            return True
        if (
            lacks_sentence_terminator
            and 1 <= numeric_count <= 3
            and 1 <= len(alphabetic_words) <= 3
            and period_count == 0
        ):
            return True

    short_numeric_lines = [
        line
        for line in lines
        if len(line) <= 160 and len(_numeric_spans(line)) >= 2
    ]
    if has_alphabetic and len(short_numeric_lines) >= 2:
        return True

    for index, line in enumerate(lines[:-2]):
        if (
            len(line) <= 80
            and _ALPHABETIC_RE.search(line) is not None
            and not _numeric_spans(line)
            and all(
                len(row) <= 160 and len(_numeric_spans(row)) >= 2
                for row in lines[index + 1 : index + 3]
            )
        ):
            return True

    return False


def _usable_file_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    if not value or value.strip() != value:
        return None
    return value


def build_evidence_presentation_scope(
    sources: list[SourceReference],
) -> list[EvidencePresentationPassage]:
    """Build one bounded raw-only selector scope in citation order."""

    passages: list[EvidencePresentationPassage] = []
    included_sources = 0
    total_chars = 0

    for source in sources:
        file_id = _usable_file_id(source.file_id)
        if file_id is None:
            continue

        source_passage_count = 0
        for passage_index, raw_text in enumerate(source.evidence):
            if not isinstance(raw_text, str):
                continue

            bounded_text = raw_text[:MAX_PRESENTATION_CHARS_PER_PASSAGE]
            if not bounded_text.strip():
                continue
            if not is_structured_evidence_candidate(bounded_text):
                continue
            if total_chars + len(bounded_text) > MAX_PRESENTATION_TOTAL_CHARS:
                return passages

            passages.append(
                EvidencePresentationPassage(
                    file_id=file_id,
                    passage_index=passage_index,
                    text=bounded_text,
                )
            )
            total_chars += len(bounded_text)
            source_passage_count += 1

            if (
                source_passage_count
                == MAX_PRESENTATION_PASSAGES_PER_SOURCE
            ):
                break

        if source_passage_count:
            included_sources += 1
            if included_sources == MAX_PRESENTATION_SOURCES:
                break

    return passages


def _build_presentation_selector_input(
    passages: list[EvidencePresentationPassage],
) -> str:
    sections = ["<evidence_passages>"]

    for passage in passages:
        sections.extend(
            [
                "<passage>",
                f"<file_id>{passage.file_id}</file_id>",
                f"<passage_index>{passage.passage_index}</passage_index>",
                "<raw_text>",
                passage.text,
                "</raw_text>",
                "</passage>",
            ]
        )

    sections.append("</evidence_passages>")
    return "\n".join(sections)


def _response_contains_refusal(response: object) -> bool:
    output = getattr(response, "output", None)
    if not isinstance(output, (list, tuple)):
        return False

    for item in output:
        if getattr(item, "type", None) == "refusal":
            return True

        content = getattr(item, "content", None)
        if isinstance(content, (list, tuple)) and any(
            getattr(part, "type", None) == "refusal" for part in content
        ):
            return True

    return False


def select_evidence_presentations(
    passages: list[EvidencePresentationPassage],
) -> EvidencePresentationSelection:
    """Request candidates, returning an empty selection on expected failures."""

    empty_selection = EvidencePresentationSelection()
    if not passages:
        return empty_selection

    instructions = PROMPT_PATH.read_text(encoding="utf-8")
    selector_input = _build_presentation_selector_input(passages)
    client = get_openai_client()

    try:
        response = client.responses.parse(
            model=OPENAI_MODEL,
            input=selector_input,
            instructions=instructions,
            text_format=EvidencePresentationSelection,
            max_output_tokens=MAX_PRESENTATION_OUTPUT_TOKENS,
        )
    except (
        APIError,
        ContentFilterFinishReasonError,
        LengthFinishReasonError,
        ValidationError,
    ) as error:
        LOGGER.warning(
            "Evidence presentation selection omitted after %s.",
            type(error).__name__,
        )
        return empty_selection

    if getattr(response, "status", None) != "completed":
        return empty_selection
    if _response_contains_refusal(response):
        return empty_selection

    selection = getattr(response, "output_parsed", None)
    if not isinstance(selection, EvidencePresentationSelection):
        return empty_selection
    if (
        len(selection.metrics) > MAX_CANDIDATE_METRICS
        or len(selection.tables) > MAX_CANDIDATE_TABLES
        or len(selection.parallel_series) > MAX_PARALLEL_CANDIDATES
    ):
        return empty_selection

    return selection
