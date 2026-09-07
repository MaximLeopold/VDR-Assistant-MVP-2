"""Chat UI components for the VDR Assistant."""

import re

from pydantic import ValidationError
import streamlit as st

from src.presentation.evidence_text import (
    MAX_VISIBLE_EVIDENCE_CHARS,
    MAX_VISIBLE_EVIDENCE_PASSAGES,
    clean_evidence_text,
    truncate_evidence_excerpt,
)
from src.schemas.answer import VDRAnswer
from src.schemas.evidence import SourceReference
from src.schemas.evidence_presentation import VerifiedEvidencePresentation


SYNTHESIZED_ANSWER_CAPTION = "Synthesized from cited VDR evidence."
UNVERIFIED_TABLE_CAPTION = (
    "The table above was synthesized from retrieved evidence and was not "
    "independently verified cell by cell."
)
VERIFIED_TABLE_AVAILABLE_CAPTION = (
    "Independently verified source figures are available under Structured."
)
EVIDENCE_HARD_MAX_CHARS = 1800
ORIGINAL_PASSAGES_LABEL = "Original retrieved passages"
EVIDENCE_TRUNCATION_CAPTION = (
    f"Full extracted passage is available under {ORIGINAL_PASSAGES_LABEL}."
)
FRAGMENTED_LAYOUT_NOTICE = (
    "The original source layout was not preserved in this passage. "
    f"Review {ORIGINAL_PASSAGES_LABEL} for the exact extraction."
)
FORMATTED_SOURCE_EXCERPTS_HEADING = "**Formatted source excerpts**"
FORMATTED_SOURCE_EXCERPTS_CAPTION = (
    "Source text formatted for readability and sometimes shortened—"
    "not an AI-written summary."
)
FORMATTED_SOURCE_EXCERPTS_DISCLOSURE = (
    f"{FORMATTED_SOURCE_EXCERPTS_HEADING} &nbsp; "
    f":gray[ⓘ {FORMATTED_SOURCE_EXCERPTS_CAPTION}]\n\n---"
)
BEST_SUPPORT_LABEL = ":green[**Best supporting passage**]"
ADDITIONAL_CONTEXT_LABEL = ":orange[**Additional retrieved context**]"

# Keyed containers contain only the untouched synthesized-answer Markdown.
SYNTHESIZED_ANSWER_STYLES = """
<style>
[class*="st-key-vdr-answer-"] h1 { font-size: 1.5rem; }
[class*="st-key-vdr-answer-"] h2 { font-size: 1.35rem; }
[class*="st-key-vdr-answer-"] h3 { font-size: 1.2rem; }
[class*="st-key-vdr-answer-"] h4 { font-size: 1.1rem; }
[class*="st-key-vdr-answer-"] h5 { font-size: 1.05rem; }
[class*="st-key-vdr-answer-"] h6 { font-size: 1rem; }
[class*="st-key-vdr-answer-"] :is(h1, h2, h3, h4, h5, h6) {
    line-height: 1.3;
    padding: 0.5rem 0 0.35rem;
}
</style>
"""

_MARKDOWN_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_MARKDOWN_DELIMITER_CELL_RE = re.compile(r"^:?-{3,}:?$")
_LIST_LINE_RE = re.compile(
    r"^[ \t]*(?:[-*•◦–—]|\d+[.)]|[A-Za-z][.)])(?:[ \t]+|$)",
    re.MULTILINE,
)
_NUMERIC_TOKEN_RE = re.compile(
    r"(?<!\w)[+-]?(?:\d[\d.,]*)(?:\s?(?:%|x))?(?!\w)",
    re.IGNORECASE,
)
_PERIOD_MARKER_RE = re.compile(
    r"(?<!\w)(?:(?:FY|Q|H)\s*\d{2,4}|(?:19|20)\d{2}[ABEF]?|LTM|NTM)"
    r"(?!\w)",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?](?:[\"'”’\)\]]*)?(?=\s|$)")


def build_assistant_message(answer: VDRAnswer) -> dict:
    """Create the session-state representation of an assistant answer."""

    return {
        "role": "assistant",
        "content": answer.answer,
        "vdr_answer": answer.model_dump(mode="json"),
    }


def _markdown_row_cells(line: str) -> list[str] | None:
    """Return cells from one plausible pipe-delimited Markdown row."""

    stripped = line.strip()
    if "|" not in stripped or "<" in stripped or ">" in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = [cell.strip() for cell in stripped.split("|")]
    if len(cells) < 2 or any(not cell for cell in cells):
        return None
    return cells


def answer_contains_markdown_table(answer: str) -> bool:
    """Detect a Markdown table while ignoring fenced code and pipe prose."""

    if not isinstance(answer, str):
        raise TypeError("answer must be a string")

    visible_lines: list[str | None] = []
    fence_character: str | None = None
    fence_length = 0

    for line in answer.splitlines():
        fence_match = _MARKDOWN_FENCE_RE.match(line)
        if fence_character is None and fence_match is not None:
            marker = fence_match.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            visible_lines.append(None)
            continue
        if fence_character is not None:
            stripped = line.lstrip()
            if stripped.startswith(fence_character * fence_length):
                fence_character = None
                fence_length = 0
            visible_lines.append(None)
            continue
        visible_lines.append(line)

    for header_line, delimiter_line in zip(
        visible_lines,
        visible_lines[1:],
    ):
        if header_line is None or delimiter_line is None:
            continue
        header_cells = _markdown_row_cells(header_line)
        delimiter_cells = _markdown_row_cells(delimiter_line)
        if header_cells is None or delimiter_cells is None:
            continue
        if len(header_cells) != len(delimiter_cells):
            continue
        if all(
            _MARKDOWN_DELIMITER_CELL_RE.fullmatch(cell) is not None
            for cell in header_cells
        ):
            continue
        if all(
            _MARKDOWN_DELIMITER_CELL_RE.fullmatch(cell) is not None
            for cell in delimiter_cells
        ):
            return True

    return False


def has_verified_table(sources: list[SourceReference]) -> bool:
    """Return whether any source contains an independently verified table."""

    return any(
        presentation.tables
        for source in sources
        for presentation in source.presentations
    )


def render_answer_trust_caption(answer: VDRAnswer) -> None:
    """Render synthesis and table-verification disclosures when applicable."""

    if answer.status != "success" or not answer.source_files:
        return

    st.caption(SYNTHESIZED_ANSWER_CAPTION)
    if not answer_contains_markdown_table(answer.answer):
        return

    if has_verified_table(answer.sources):
        st.caption(VERIFIED_TABLE_AVAILABLE_CAPTION)
    else:
        st.caption(UNVERIFIED_TABLE_CAPTION)


def _has_structured_content(
    presentations: list[VerifiedEvidencePresentation],
) -> bool:
    """Return whether a source has verified content worth rendering."""

    return any(
        presentation.metrics or presentation.tables
        for presentation in presentations
    )


def _has_useful_evidence(source: SourceReference) -> bool:
    """Keep citation visibility separate from verified evidence visibility."""

    return any(
        excerpt.text.strip() for excerpt in source.selected_evidence
    ) or _has_structured_content(source.presentations)


def _metric_display_label(
    label: str,
    period: str | None,
    unit: str | None,
) -> str:
    """Assemble verified source fields without changing their text."""

    return " — ".join(
        part for part in (label, period, unit) if part is not None
    )


def _render_structured_evidence(
    presentations: list[VerifiedEvidencePresentation],
) -> None:
    """Render only locally verified metrics and row-oriented tables."""

    st.caption(
        "Structured from retrieved evidence; values are source-verified."
    )

    for presentation in presentations:
        metrics = presentation.metrics
        for start in range(0, len(metrics), 2):
            columns = st.columns(2)
            for column, metric in zip(columns, metrics[start : start + 2]):
                with column:
                    st.metric(
                        label=_metric_display_label(
                            metric.label,
                            metric.period,
                            metric.unit,
                        ),
                        value=metric.value,
                    )

        for table in presentation.tables:
            if table.title is not None:
                st.caption(table.title)
            table_data = {
                column: [row[index] for row in table.rows]
                for index, column in enumerate(table.columns)
            }
            st.table(table_data, hide_index=True)


def _nonempty_lines(text: str) -> list[str]:
    """Return nonblank lines without changing their content."""

    return [line for line in text.splitlines() if line.strip()]


def _is_numeric_dense(line: str) -> bool:
    """Return whether a line looks value-oriented rather than prose-like."""

    return (
        len(_NUMERIC_TOKEN_RE.findall(line)) >= 2
        or len(_PERIOD_MARKER_RE.findall(line)) >= 2
    )


def is_table_like_evidence(text: str) -> bool:
    """Conservatively identify repeated period/value extraction fragments."""

    lines = _nonempty_lines(text)
    if len(lines) < 3:
        return False

    list_line_count = sum(
        _LIST_LINE_RE.match(line) is not None for line in lines
    )
    if list_line_count:
        return False

    numeric_counts = [len(_NUMERIC_TOKEN_RE.findall(line)) for line in lines]
    numeric_line_count = sum(count > 0 for count in numeric_counts)
    period_count = sum(
        len(_PERIOD_MARKER_RE.findall(line)) for line in lines
    )
    short_line_count = sum(len(line.split()) <= 3 for line in lines)

    return (
        period_count >= 3
        or (
            numeric_line_count * 5 >= len(lines) * 2
            and short_line_count * 4 >= len(lines) * 3
        )
        or sum(count >= 2 for count in numeric_counts) >= 2
    )


def is_severely_fragmented(text: str) -> bool:
    """Identify ambiguous runs dominated by one- or two-word lines."""

    lines = _nonempty_lines(text)
    if len(lines) < 6:
        return False
    if any(_LIST_LINE_RE.match(line) is not None for line in lines):
        return False

    short_line_count = sum(len(line.split()) <= 2 for line in lines)
    return short_line_count * 4 >= len(lines) * 3


def _looks_like_heading(line: str) -> bool:
    """Return whether a short line is plausibly a standalone heading."""

    words = re.findall(r"[^\W\d_]+", line, flags=re.UNICODE)
    return bool(words) and len(words) <= 6 and all(
        word[0].isupper() for word in words
    )


def _can_join_soft_wrap(current: str, following: str) -> bool:
    """Return whether two adjacent lines are unmistakably wrapped prose."""

    current_stripped = current.strip()
    following_stripped = following.strip()
    following_letters = re.search(r"[^\W\d_]", following_stripped, re.UNICODE)
    if not current_stripped or not following_stripped:
        return False
    if _LIST_LINE_RE.match(current) or _LIST_LINE_RE.match(following):
        return False
    if _is_numeric_dense(current) or _is_numeric_dense(following):
        return False
    if _PERIOD_MARKER_RE.search(current) or _PERIOD_MARKER_RE.search(following):
        return False
    if (
        "\t" in current
        or "\t" in following
        or "|" in current
        or "|" in following
    ):
        return False
    if _SENTENCE_BOUNDARY_RE.search(current_stripped):
        return False
    if len(current_stripped.split()) < 4 or _looks_like_heading(
        current_stripped
    ):
        return False
    if following_letters is None or not following_letters.group(0).islower():
        return False
    return True


def reflow_clear_soft_wraps(text: str) -> str:
    """Join only clear lowercase prose continuations within a paragraph."""

    rendered_lines: list[str] = []
    in_list_block = False
    for line in text.split("\n"):
        if not line.strip():
            rendered_lines.append(line)
            in_list_block = False
            continue
        if _LIST_LINE_RE.match(line):
            in_list_block = True
        if (
            rendered_lines
            and not in_list_block
            and _can_join_soft_wrap(rendered_lines[-1], line)
        ):
            rendered_lines[-1] = (
                f"{rendered_lines[-1].rstrip()} {line.lstrip()}"
            )
        else:
            rendered_lines.append(line)
    return "\n".join(rendered_lines)


def _forward_boundary(
    text: str,
    *,
    target_chars: int,
    content_limit: int,
) -> int | None:
    """Find the preferred safe boundary after the readability target."""

    list_starts = [
        match.start()
        for match in _LIST_LINE_RE.finditer(text)
    ]
    paragraph_start = text.rfind("\n\n", 0, target_chars) + 2
    current_list_starts = [
        start
        for start in list_starts
        if paragraph_start <= start <= target_chars
    ]
    if current_list_starts:
        next_list_starts = [
            start
            for start in list_starts
            if target_chars < start <= content_limit
        ]
        if next_list_starts:
            return next_list_starts[0]

    search_region = text[target_chars:content_limit]
    paragraph_match = re.search(r"\n[ \t]*\n", search_region)
    if paragraph_match is not None:
        return target_chars + paragraph_match.start()

    sentence_match = _SENTENCE_BOUNDARY_RE.search(search_region)
    if sentence_match is not None:
        return target_chars + sentence_match.end()

    line_offset = search_region.find("\n")
    if line_offset >= 0:
        return target_chars + line_offset
    return None


def _preceding_boundary(text: str, *, target_chars: int) -> int | None:
    """Find the nearest useful boundary before the readability target."""

    candidates: list[int] = []
    candidates.extend(
        match.start()
        for match in _LIST_LINE_RE.finditer(text)
        if 0 < match.start() <= target_chars
    )
    candidates.extend(
        match.start()
        for match in re.finditer(r"\n[ \t]*\n", text[: target_chars + 1])
        if match.start() > 0
    )
    candidates.extend(
        match.end()
        for match in _SENTENCE_BOUNDARY_RE.finditer(text[:target_chars])
    )
    candidates.extend(
        match.start()
        for match in re.finditer("\n", text[:target_chars])
        if match.start() > 0
    )
    return max(candidates, default=None)


def truncate_evidence_at_boundary(
    text: str,
    target_chars: int = MAX_VISIBLE_EVIDENCE_CHARS,
    hard_max_chars: int = EVIDENCE_HARD_MAX_CHARS,
) -> tuple[str, bool]:
    """Return a bounded excerpt ending at a meaningful display boundary."""

    if target_chars < 0:
        raise ValueError("target_chars must be non-negative")
    if hard_max_chars <= 0 or hard_max_chars < target_chars:
        raise ValueError("hard_max_chars must be at least target_chars")
    if len(text) <= target_chars:
        return text, False

    content_limit = hard_max_chars - 1
    boundary = _forward_boundary(
        text,
        target_chars=target_chars,
        content_limit=min(content_limit, len(text)),
    )
    if boundary is None and len(text) <= hard_max_chars:
        return text, False
    if boundary is None:
        boundary = _preceding_boundary(text, target_chars=target_chars)
    if boundary is None:
        boundary = text.rfind(" ", 0, content_limit + 1)
    if boundary is None or boundary <= 0:
        boundary = content_limit

    excerpt = text[: min(boundary, content_limit)].rstrip()
    if not excerpt:
        excerpt = text[:content_limit]
    return f"{excerpt}…", True


def render_evidence_passage(
    passage: str,
    *,
    label: str | None,
) -> None:
    """Render one cleaned, bounded passage without semantic rewriting."""

    cleaned_passage = clean_evidence_text(passage)
    if not cleaned_passage:
        return

    is_fragmented = is_table_like_evidence(
        cleaned_passage
    ) or is_severely_fragmented(cleaned_passage)
    display_text = (
        cleaned_passage
        if is_fragmented
        else reflow_clear_soft_wraps(cleaned_passage)
    )
    excerpt, was_truncated = truncate_evidence_at_boundary(display_text)

    if label is not None:
        st.caption(label)
    if is_fragmented:
        st.caption(FRAGMENTED_LAYOUT_NOTICE)
        st.code(excerpt, language=None, wrap_lines=True)
    else:
        st.text(excerpt, width="stretch")
    if was_truncated:
        st.caption(EVIDENCE_TRUNCATION_CAPTION)


def render_evidence_tab(source: SourceReference) -> None:
    """Render persisted selections, or the legacy first-two fallback."""

    if source.evidence_selection_status == "completed":
        if not source.selected_evidence:
            if _has_structured_content(source.presentations):
                st.caption("Verified source figures are available under Structured.")
            return

        best_support = [
            excerpt
            for excerpt in source.selected_evidence
            if excerpt.role == "best_support"
        ]
        additional_context = [
            excerpt
            for excerpt in source.selected_evidence
            if excerpt.role == "additional_context"
        ]

        if best_support:
            st.markdown(BEST_SUPPORT_LABEL)
            for excerpt in best_support:
                render_evidence_passage(excerpt.text, label=None)

        if additional_context:
            st.markdown(ADDITIONAL_CONTEXT_LABEL)
            for index, excerpt in enumerate(additional_context, start=1):
                render_evidence_passage(
                    excerpt.text,
                    label=f"Additional context {index}",
                )
        return

    passages = source.evidence[:MAX_VISIBLE_EVIDENCE_PASSAGES]
    if not passages or not any(clean_evidence_text(item) for item in passages):
        return

    if len(passages) == 1:
        render_evidence_passage(
            passages[0],
            label=BEST_SUPPORT_LABEL,
        )
        return
    labels = ["Best supporting passage", "Additional retrieved context"]
    passage_tabs = st.tabs(labels, default=labels[0])
    for passage_tab, passage in zip(passage_tabs, passages):
        with passage_tab:
            render_evidence_passage(passage, label=None)


def render_raw_retrieval(source: SourceReference) -> None:
    """Render exact stored File Search strings for auditability."""

    if source.evidence_selection_status == "completed":
        associations_by_passage: dict[int, list[str]] = {}
        additional_number = 0
        for excerpt in source.selected_evidence:
            if excerpt.role == "best_support":
                label = "Best supporting passage"
            else:
                additional_number += 1
                label = f"Additional retrieved context {additional_number}"

            passage_index = excerpt.passage_index
            if not (0 <= passage_index < len(source.evidence)):
                continue
            associations_by_passage.setdefault(passage_index, []).append(label)

        if not associations_by_passage:
            st.caption("No selected raw passage is available for this source.")
            return

        for passage_index, associations in associations_by_passage.items():
            st.caption("; ".join(associations))
            st.code(
                source.evidence[passage_index],
                language=None,
                wrap_lines=False,
            )
        return

    for index, passage in enumerate(
        source.evidence[:MAX_VISIBLE_EVIDENCE_PASSAGES],
        start=1,
    ):
        st.caption(f"Raw passage {index}")
        st.code(passage, language=None, wrap_lines=False)


def _render_evidence_views(source: SourceReference) -> None:
    """Render evidence, optional structure, and raw retrieval safely."""

    has_structured_content = _has_structured_content(source.presentations)
    tab_labels = ["Evidence"]
    if has_structured_content:
        tab_labels.append("Structured")
    tab_labels.append(ORIGINAL_PASSAGES_LABEL)
    tabs = st.tabs(tab_labels, default=tab_labels[0])

    if has_structured_content:
        evidence_tab, structured_tab, raw_tab = tabs
    else:
        evidence_tab, raw_tab = tabs

    with evidence_tab:
        render_evidence_tab(source)

    if has_structured_content:
        with structured_tab:
            _render_structured_evidence(source.presentations)

    with raw_tab:
        render_raw_retrieval(source)


def _render_answer_content(
    answer: VDRAnswer, *, answer_key: str = "vdr-answer-current"
) -> None:
    """Render answer content without creating a chat-message container."""

    st.html(SYNTHESIZED_ANSWER_STYLES)
    with st.container(key=answer_key):
        st.markdown(answer.answer)
    render_answer_trust_caption(answer)

    if answer.verified_quotes:
        with st.expander("Verified quotations"):
            for quote in answer.verified_quotes:
                st.text(f"“{quote.text}”", width="stretch")
                st.caption(f"Source: {quote.source_display_name}")

    evidence_sources = [source for source in answer.sources if _has_useful_evidence(source)]
    if evidence_sources:
        st.markdown("**Evidence**")
        st.markdown(FORMATTED_SOURCE_EXCERPTS_DISCLOSURE)
        for source in evidence_sources:
            with st.expander(
                f"Retrieved evidence — {source.display_name}"
            ):
                _render_evidence_views(
                    source,
                )


def render_chat_history(messages: list[dict]) -> None:
    """Render structured and legacy conversation history."""

    for index, message in enumerate(messages):
        with st.chat_message(message["role"]):
            payload = message.get("vdr_answer")
            if message.get("role") == "assistant" and payload is not None:
                try:
                    answer = VDRAnswer.model_validate(payload)
                except ValidationError:
                    st.markdown(message["content"])
                else:
                    _render_answer_content(answer, answer_key=f"vdr-answer-history-{index}")
            else:
                st.markdown(message["content"])


def render_answer(answer: VDRAnswer) -> None:
    """Render a validated assistant answer."""

    with st.chat_message("assistant"):
        _render_answer_content(answer)
