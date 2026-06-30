"""Streamlit entry point for the VDR Assistant."""

import streamlit as st

from src.chains.qa_chain import run_qa_chain
from src.config.constants import APP_TITLE
from src.config.settings import (
    VECTOR_STORE_ID,
    validate_settings,
)
from src.ui.chat import (
    render_answer,
    render_chat_history,
)
from src.ui.sidebar import render_sidebar
from src.ui.source_panel import render_source_panel


st.set_page_config(
    page_title=APP_TITLE,
    layout="wide",
)

st.title(APP_TITLE)
st.caption("Ask questions against the active VDR vector store.")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "last_answer" not in st.session_state:
    st.session_state.last_answer = None


# The OpenAI API key must exist before the app can do anything useful.
# The vector store ID can come from .env or from the sidebar input.
missing_settings = validate_settings()
blocking_missing_settings = [
    setting
    for setting in missing_settings
    if setting != "VECTOR_STORE_ID"
]

if blocking_missing_settings:
    st.error(
        "Missing required environment variables:\n\n"
        + "\n".join(blocking_missing_settings)
    )
    st.stop()


mode, active_vector_store = render_sidebar(VECTOR_STORE_ID)

render_source_panel(st.session_state.last_answer)

if not active_vector_store:
    st.warning(
        "Please enter an OpenAI vector store ID in the sidebar "
        "or add VECTOR_STORE_ID to your local .env file."
    )
    st.stop()


if mode != "qa":
    st.info(
        "Only the Q&A workflow is implemented in this version. "
        "Compare and Summarize will be added later."
    )
    st.stop()


render_chat_history(st.session_state.messages)

question = st.chat_input("Ask a question about the VDR...")

if question:
    user_message = {
        "role": "user",
        "content": question,
    }

    st.session_state.messages.append(user_message)

    with st.chat_message("user"):
        st.markdown(question)

    with st.spinner("Searching VDR..."):
        answer = run_qa_chain(
            question=question,
            vector_store_id=active_vector_store,
            messages=st.session_state.messages,
        )

    assistant_message = {
        "role": "assistant",
        "content": answer.answer,
    }

    st.session_state.messages.append(assistant_message)
    st.session_state.last_answer = answer

    render_answer(answer)
