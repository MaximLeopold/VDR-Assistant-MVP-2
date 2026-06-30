"""Streamlit entry point for the VDR Assistant MVP 2.

This file will later contain the main Streamlit layout and will call
the reusable modules from the src package.

For now, it only confirms that the app can start.
"""

import streamlit as st


st.set_page_config(
    page_title="VDR Assistant MVP 2",
    layout="wide",
)

st.title("VDR Assistant MVP 2")
st.caption("Local-first VDR assistant using OpenAI vector stores and File Search.")

st.info(
    "Repository structure is ready. "
    "The Q&A functionality will be added in the next development phase."
)
