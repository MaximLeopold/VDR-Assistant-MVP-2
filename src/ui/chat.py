"""Chat UI components for the VDR Assistant."""

from pydantic import ValidationError
import streamlit as st

from src.presentation.evidence_text import (
    MAX_VISIBLE_EVIDENCE_CHARS,
    MAX_VISIBLE_EVIDENCE_PASSAGES,
    clean_evidence_text,
    truncate_evidence_excerpt,
)
from src.schemas.answer import VDRAnswer
from src.schemas.evidence_presentation import VerifiedEvidencePresentation


def build_assistant_message(answer: VDRAnswer) -> dict:
    """Create the session-state representation of an assistant answer."""

    return {
        "role": "assistant",
        "content": answer.answer,
        "vdr_answer": answer.model_dump(mode="json"),
    }


def _has_structured_content(
    presentations: list[VerifiedEvidencePresentation],
) -> bool:
    """Return whether a source has verified content worth rendering."""

    return any(
        presentation.metrics or presentation.tables
        for presentation in presentations
    )


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


def _render_evidence_views(
    evidence: list[str],
    presentations: list[VerifiedEvidencePresentation],
) -> None:
    """Render structured, readable, and raw evidence views safely."""

    raw_excerpts = [
        truncate_evidence_excerpt(passage)
        for passage in evidence[:MAX_VISIBLE_EVIDENCE_PASSAGES]
    ]
    has_structured_content = _has_structured_content(presentations)
    tab_labels = ["Readable text", "Raw text"]
    if has_structured_content:
        tab_labels.insert(0, "Structured view")
    tabs = st.tabs(tab_labels, default=tab_labels[0])

    if has_structured_content:
        structured_tab, readable_tab, raw_tab = tabs
        with structured_tab:
            _render_structured_evidence(presentations)
    else:
        readable_tab, raw_tab = tabs

    with readable_tab:
        st.caption(
            "Formatting cleanup only; document wording and values are "
            "unchanged."
        )
        for index, raw_excerpt in enumerate(raw_excerpts, start=1):
            cleaned_excerpt = clean_evidence_text(raw_excerpt)
            if not cleaned_excerpt:
                continue
            st.caption(f"Retrieved passage {index}")
            st.text(cleaned_excerpt, width="stretch")

    with raw_tab:
        for index, raw_excerpt in enumerate(raw_excerpts, start=1):
            st.caption(f"Retrieved passage {index}")
            st.code(
                raw_excerpt,
                language=None,
                wrap_lines=False,
            )


def _render_answer_content(answer: VDRAnswer) -> None:
    """Render answer content without creating a chat-message container."""

    st.markdown(answer.answer)

    if answer.verified_quotes:
        st.markdown("**Verified quotations**")
        for quote in answer.verified_quotes:
            st.text(f"“{quote.text}”", width="stretch")
            st.caption(f"Source: {quote.source_display_name}")

    if answer.sources:
        st.markdown("**Sources**")
        for source in answer.sources:
            if not source.evidence and not _has_structured_content(
                source.presentations
            ):
                st.markdown(f"- {source.display_name}")
                continue

            with st.expander(
                f"Retrieved evidence — {source.display_name}"
            ):
                _render_evidence_views(
                    source.evidence,
                    source.presentations,
                )
    elif answer.source_files:
        st.markdown("**Sources**")
        for source in answer.source_files:
            st.markdown(f"- {source}")


def render_chat_history(messages: list[dict]) -> None:
    """Render structured and legacy conversation history."""

    for message in messages:
        with st.chat_message(message["role"]):
            payload = message.get("vdr_answer")
            if message.get("role") == "assistant" and payload is not None:
                try:
                    answer = VDRAnswer.model_validate(payload)
                except ValidationError:
                    st.markdown(message["content"])
                else:
                    _render_answer_content(answer)
            else:
                st.markdown(message["content"])


def render_answer(answer: VDRAnswer) -> None:
    """Render a validated assistant answer."""

    with st.chat_message("assistant"):
        _render_answer_content(answer)
