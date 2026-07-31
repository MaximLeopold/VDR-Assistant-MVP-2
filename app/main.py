"""Streamlit entry point for the VDR Assistant."""

from pathlib import Path
import sys

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.chains.qa_chain import run_qa_chain
from src.config.case_registry import CaseRegistryError, load_case_registry
from src.config.constants import APP_TITLE
from src.config.settings import (
    CASE_REGISTRY_PATH,
    validate_settings,
)
from src.ui.chat import (
    build_assistant_message,
    render_answer,
    render_chat_history,
)
from src.ui.case_selection import (
    ActiveCaseError,
    activate_case,
    active_case_qa_inputs,
    close_active_case,
    get_active_case,
    initialize_case_session,
    render_case_selection,
)
from src.ui.sidebar import render_sidebar
from src.ui.source_panel import render_source_panel


st.set_page_config(
    page_title=APP_TITLE,
    layout="wide",
)

st.title(APP_TITLE)
st.caption("Ask questions against one prepared VDR case at a time.")

initialize_case_session(st.session_state)
active_case = get_active_case(st.session_state)


if active_case is None:
    try:
        prepared_cases = load_case_registry(
            CASE_REGISTRY_PATH,
            base_dir=PROJECT_ROOT,
        )
    except CaseRegistryError as error:
        st.error(str(error))
        st.stop()

    selected_case = render_case_selection(prepared_cases)
    if selected_case is not None:
        activate_case(st.session_state, selected_case)
        st.rerun()
    st.stop()


# The OpenAI API key must exist before the app can do anything useful.
missing_settings = validate_settings()

mode, reset_chat, close_case = render_sidebar(active_case.display_name)

if close_case:
    close_active_case(st.session_state)
    st.rerun()

if not active_case.is_ready:
    st.error(
        f"{active_case.display_name} cannot be opened: "
        f"{active_case.error or 'The case configuration is incomplete.'}"
    )
    st.stop()

if missing_settings:
    st.error(
        "Missing required environment variables:\n\n"
        + "\n".join(missing_settings)
    )
    st.stop()

if reset_chat:
    st.session_state.messages = []
    st.session_state.last_answer = None
    st.rerun()

if mode != "qa":
    st.info(
        "Only the Q&A workflow is implemented in this version. "
        "Compare and Summarize will be added later."
    )
    render_source_panel(st.session_state.last_answer)
    st.stop()


try:
    active_vector_store, active_manifest = active_case_qa_inputs(active_case)
except ActiveCaseError as error:
    st.error(f"{active_case.display_name} cannot be opened: {error}")
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
            manifest=active_manifest,
        )

    assistant_message = build_assistant_message(answer)

    st.session_state.messages.append(assistant_message)
    st.session_state.last_answer = answer

    render_answer(answer)


render_source_panel(st.session_state.last_answer)
