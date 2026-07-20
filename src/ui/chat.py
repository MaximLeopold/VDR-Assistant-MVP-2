"""Chat UI components for the VDR Assistant."""

from pydantic import ValidationError
import streamlit as st

from src.schemas.answer import VDRAnswer


MAX_VISIBLE_EVIDENCE_PASSAGES = 2
MAX_VISIBLE_EVIDENCE_CHARS = 1200


def truncate_evidence_excerpt(
    text: str,
    max_chars: int = MAX_VISIBLE_EVIDENCE_CHARS,
) -> str:
    """Return a bounded, presentation-only excerpt of retrieved text."""

    if max_chars < 0:
        raise ValueError("max_chars must not be negative")

    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized

    prefix = normalized[: max_chars + 1]
    boundary = max(
        (index for index, character in enumerate(prefix) if character.isspace()),
        default=-1,
    )

    if boundary > 0:
        excerpt = normalized[:boundary]
    else:
        excerpt = normalized[:max_chars]

    return excerpt.rstrip() + "…"


def build_assistant_message(answer: VDRAnswer) -> dict:
    """Create the session-state representation of an assistant answer."""

    return {
        "role": "assistant",
        "content": answer.answer,
        "vdr_answer": answer.model_dump(mode="json"),
    }


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
            if not source.evidence:
                st.markdown(f"- {source.display_name}")
                continue

            with st.expander(
                f"Retrieved evidence — {source.display_name}"
            ):
                for index, passage in enumerate(
                    source.evidence[:MAX_VISIBLE_EVIDENCE_PASSAGES],
                    start=1,
                ):
                    st.caption(f"Retrieved passage {index}")
                    st.text(
                        truncate_evidence_excerpt(passage),
                        width="stretch",
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
