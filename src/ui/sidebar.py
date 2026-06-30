"""Sidebar UI components.

This module should render the vector store ID input, mode selector,
standard due diligence questions, and reset controls.
"""

"""Sidebar UI components for the VDR Assistant."""

import streamlit as st

from src.config.constants import SUPPORTED_MODES


def render_sidebar(default_vector_store_id: str | None) -> tuple[str, str]:
    """Render sidebar controls.

    Returns:
        A tuple containing:
        - selected workflow mode
        - active vector store ID
    """

    st.sidebar.header("VDR Settings")

    vector_store_id = st.sidebar.text_input(
        "OpenAI Vector Store ID",
        value=default_vector_store_id or "",
        help="Enter the vector store ID for the active VDR project.",
    )

    mode = st.sidebar.selectbox(
        "Workflow",
        options=list(SUPPORTED_MODES.keys()),
        format_func=lambda key: SUPPORTED_MODES[key],
    )

    st.sidebar.divider()

    if vector_store_id:
        st.sidebar.success("Vector store configured.")
    else:
        st.sidebar.error("Vector store ID missing.")

    return mode, vector_store_id
