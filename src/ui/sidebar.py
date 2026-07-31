"""Sidebar UI components for the VDR Assistant."""

import streamlit as st

from src.config.constants import SUPPORTED_MODES


def render_sidebar(active_case_name: str) -> tuple[str, bool, bool]:
    """Render controls for one fixed active case.

    Returns:
        A tuple containing:
        - selected workflow mode
        - whether the user clicked reset chat
        - whether the user clicked close case
    """

    st.sidebar.header("Active case")
    st.sidebar.success(active_case_name)

    mode = st.sidebar.selectbox(
        "Workflow",
        options=list(SUPPORTED_MODES.keys()),
        format_func=lambda key: SUPPORTED_MODES[key],
        key="active_case_workflow",
    )

    st.sidebar.divider()

    reset_chat = st.sidebar.button(
        "Reset chat",
        help="Clear the current conversation history.",
        key="reset_active_case_chat",
    )

    close_case = st.sidebar.button(
        "Close case",
        help="Clear this case's chat and return to case selection.",
        key="close_active_case",
    )

    return mode, reset_chat, close_case
