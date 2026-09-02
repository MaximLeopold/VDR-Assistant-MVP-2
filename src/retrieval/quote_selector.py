"""Select bounded quotation and evidence candidates in one model call."""

import json
import logging
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
from src.schemas.quotation import QuoteSelection, SupportSelectionPassage


MAX_SUPPORT_SOURCES = 6
MAX_SUPPORT_PASSAGES_PER_SOURCE = 6
MAX_SUPPORT_PASSAGE_CHARS = 3500
MAX_SUPPORT_TOTAL_PASSAGE_CHARS = 60000
MAX_SUPPORT_QUESTION_CHARS = 4000
MAX_SUPPORT_ANSWER_CHARS = 8000
MAX_SUPPORT_CONTEXT_CHARS = 6000
MAX_SUPPORT_CONTEXT_MESSAGES = 4
MAX_QUOTE_CANDIDATES_TO_PROCESS = 6
MAX_SUPPORT_OUTPUT_TOKENS = 6000

# Compatibility names retained for integrations that inspect these bounds.
MAX_QUOTE_SOURCES = MAX_SUPPORT_SOURCES
MAX_QUOTE_PASSAGES_PER_SOURCE = MAX_SUPPORT_PASSAGES_PER_SOURCE
MAX_QUOTE_PASSAGE_CHARS = MAX_SUPPORT_PASSAGE_CHARS
MAX_QUOTE_ANSWER_CHARS = MAX_SUPPORT_ANSWER_CHARS
MAX_QUOTE_OUTPUT_TOKENS = MAX_SUPPORT_OUTPUT_TOKENS

PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "quote_selection.md"
)
LOGGER = logging.getLogger(__name__)


def _usable_file_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if not value or value.strip() != value:
        return None
    return value


def build_support_evidence_scope(
    sources: list[SourceReference],
) -> list[SupportSelectionPassage]:
    """Build a bounded cited-only scope while retaining original indices."""

    passages: list[SupportSelectionPassage] = []
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

            bounded_text = raw_text[:MAX_SUPPORT_PASSAGE_CHARS]
            if not bounded_text.strip():
                continue
            if total_chars + len(bounded_text) > MAX_SUPPORT_TOTAL_PASSAGE_CHARS:
                return passages

            passages.append(
                SupportSelectionPassage(
                    file_id=file_id,
                    passage_index=passage_index,
                    text=bounded_text,
                )
            )
            total_chars += len(bounded_text)
            source_passage_count += 1

            if source_passage_count == MAX_SUPPORT_PASSAGES_PER_SOURCE:
                break

        if source_passage_count:
            included_sources += 1
            if included_sources == MAX_SUPPORT_SOURCES:
                break

    return passages


def build_recent_selector_context(
    messages: list[dict],
    current_question: str,
) -> str:
    """Return at most four prior user/assistant messages for query context."""

    eligible: list[tuple[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        if content.strip():
            eligible.append((role, content.strip()))

    if (
        eligible
        and eligible[-1][0] == "user"
        and eligible[-1][1] == current_question.strip()
    ):
        eligible.pop()

    rendered = "\n\n".join(
        f"{role.upper()}: {content}"
        for role, content in eligible[-MAX_SUPPORT_CONTEXT_MESSAGES:]
    )
    return rendered[-MAX_SUPPORT_CONTEXT_CHARS:]


def _build_support_selector_input(
    *,
    question: str,
    provisional_answer: str,
    recent_context: str,
    passages: list[SupportSelectionPassage],
) -> str:
    """Serialize the bounded selector input without source display metadata."""

    payload = {
        "current_question": question[:MAX_SUPPORT_QUESTION_CHARS],
        "provisional_answer": provisional_answer[:MAX_SUPPORT_ANSWER_CHARS],
        "recent_conversation_context": recent_context[
            -MAX_SUPPORT_CONTEXT_CHARS:
        ],
        "retrieved_passages": [
            passage.model_dump(mode="json") for passage in passages
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


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


def select_quote_candidates(
    *,
    question: str,
    provisional_answer: str,
    recent_context: str,
    passages: list[SupportSelectionPassage],
) -> QuoteSelection | None:
    """Return a completed selection, or ``None`` on processing failure."""

    if not passages:
        return QuoteSelection()

    instructions = PROMPT_PATH.read_text(encoding="utf-8")
    selector_input = _build_support_selector_input(
        question=question,
        provisional_answer=provisional_answer,
        recent_context=recent_context,
        passages=passages,
    )
    client = get_openai_client()

    try:
        response = client.responses.parse(
            model=OPENAI_MODEL,
            input=selector_input,
            instructions=instructions,
            text_format=QuoteSelection,
            max_output_tokens=MAX_SUPPORT_OUTPUT_TOKENS,
        )
    except (
        APIError,
        ContentFilterFinishReasonError,
        LengthFinishReasonError,
        ValidationError,
    ) as error:
        LOGGER.warning(
            "Support selection failed after %s.",
            type(error).__name__,
        )
        return None

    if getattr(response, "status", None) != "completed":
        return None
    if _response_contains_refusal(response):
        return None

    selection = getattr(response, "output_parsed", None)
    if not isinstance(selection, QuoteSelection):
        return None
    return selection


# The support-oriented names remain as descriptive aliases for new callers.
def build_quote_evidence_scope(
    sources: list[SourceReference],
) -> list[SupportSelectionPassage]:
    return build_support_evidence_scope(sources)


def select_support_candidates(
    *,
    question: str,
    provisional_answer: str,
    recent_context: str,
    passages: list[SupportSelectionPassage],
) -> QuoteSelection | None:
    return select_quote_candidates(
        question=question,
        provisional_answer=provisional_answer,
        recent_context=recent_context,
        passages=passages,
    )
