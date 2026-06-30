"""Chat UI components.

This module should render previous chat messages and current responses.
"""

"""Chat UI components for the VDR Assistant."""

import streamlit as st

from src.schemas.answer import VDRAnswer


def render_chat_history(messages: list[dict]) -> None:
    """Render the conversation history."""

    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def render_answer(answer: VDRAnswer) -> None:
    """Render a validated assistant answer."""

    with st.chat_message("assistant"):
        st.markdown(answer.answer)

        if answer.source_files:
            with st.expander("Sources"):
                for source in answer.source_files:
                    st.markdown(f"- {source}")

        if answer.quotes:
            with st.expander("Quotes"):
                for quote in answer.quotes:
                    st.markdown(f"> {quote}")
