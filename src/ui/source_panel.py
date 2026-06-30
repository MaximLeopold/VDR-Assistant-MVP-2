"""Source panel UI components.

This module should render citations, source files, and validation warnings.
"""

"""Source panel UI components for Streamlit."""

import streamlit as st

from src.schemas.answer import VDRAnswer


def render_source_panel(answer: VDRAnswer | None) -> None:
    """Render source files and warnings in the sidebar."""

    st.sidebar.subheader("Sources")

    if answer is None:
        st.sidebar.caption("Sources will appear after the first answer.")
        return

    if answer.source_files:
        for source_file in answer.source_files:
            st.sidebar.info(f"📄 {source_file}")
    else:
        st.sidebar.caption("No sources returned.")

    if answer.warnings:
        st.sidebar.subheader("Warnings")
        for warning in answer.warnings:
            st.sidebar.warning(warning)
