"""Prepared-case selection and session isolation helpers."""

from __future__ import annotations

from collections.abc import MutableMapping

import streamlit as st

from src.config.case_registry import PreparedCase
from src.ingestion.manifest import VDRManifest


SELECTED_CASE_ID_KEY = "selected_case_id"
ACTIVE_CASE_KEY = "active_case"
MESSAGES_KEY = "messages"
LAST_ANSWER_KEY = "last_answer"
CASE_SELECTOR_KEY = "case_selector"
PREPARE_NEW_CASE_BUTTON_KEY = "prepare_new_case"


class ActiveCaseError(Exception):
    """Raised when an active case cannot safely enter Q&A."""


def initialize_case_session(state: MutableMapping) -> None:
    """Initialize only the session values owned by case selection and chat."""

    state.setdefault(MESSAGES_KEY, [])
    state.setdefault(LAST_ANSWER_KEY, None)
    state.setdefault(SELECTED_CASE_ID_KEY, None)
    state.setdefault(ACTIVE_CASE_KEY, None)


def _clear_case_history(state: MutableMapping) -> None:
    state[MESSAGES_KEY] = []
    state[LAST_ANSWER_KEY] = None


def activate_case(state: MutableMapping, prepared_case: PreparedCase) -> None:
    """Activate one fixed case after removing every previous-case answer."""

    _clear_case_history(state)
    state[SELECTED_CASE_ID_KEY] = prepared_case.case_id
    state[ACTIVE_CASE_KEY] = prepared_case


def close_active_case(state: MutableMapping) -> None:
    """Close the case and remove all case-specific session data."""

    _clear_case_history(state)
    state[SELECTED_CASE_ID_KEY] = None
    state[ACTIVE_CASE_KEY] = None
    state.pop(CASE_SELECTOR_KEY, None)


def get_active_case(state: MutableMapping) -> PreparedCase | None:
    """Return the internally consistent active case, if one exists."""

    prepared_case = state.get(ACTIVE_CASE_KEY)
    selected_case_id = state.get(SELECTED_CASE_ID_KEY)
    if prepared_case is None and selected_case_id is None:
        return None
    if not isinstance(prepared_case, PreparedCase):
        close_active_case(state)
        return None
    if prepared_case.case_id != selected_case_id:
        close_active_case(state)
        return None
    return prepared_case


def active_case_qa_inputs(
    prepared_case: PreparedCase,
) -> tuple[str, VDRManifest]:
    """Return validated Q&A inputs or block an incomplete selected case."""

    if (
        not prepared_case.is_ready
        or prepared_case.vector_store_id is None
        or prepared_case.manifest is None
    ):
        raise ActiveCaseError(
            prepared_case.error or "The selected case is not ready for Q&A."
        )
    return prepared_case.vector_store_id, prepared_case.manifest


def render_case_selection(cases: list[PreparedCase]) -> PreparedCase | None:
    """Render the application-entry case selector."""

    st.subheader("Select a prepared VDR case")
    st.caption("Choose one case to open the existing Q&A workspace.")

    cases_by_id = {prepared_case.case_id: prepared_case for prepared_case in cases}

    def format_case(case_id: str) -> str:
        prepared_case = cases_by_id[case_id]
        suffix = "" if prepared_case.is_ready else " — configuration issue"
        return f"{prepared_case.display_name}{suffix}"

    selected_case_id = st.selectbox(
        "Prepared case",
        options=list(cases_by_id),
        index=None,
        placeholder="Select a case",
        format_func=format_case,
        key=CASE_SELECTOR_KEY,
    )

    if selected_case_id is None:
        return None

    if st.button("Open case", type="primary", key="open_selected_case"):
        return cases_by_id[selected_case_id]

    return None


def render_prepare_new_case_action() -> bool:
    """Render the secondary startup action for an unregistered new case."""

    st.divider()
    st.caption(
        "Prepare a new local case before it is uploaded and added to the "
        "prepared-case list."
    )
    return st.button(
        "Prepare new case",
        key=PREPARE_NEW_CASE_BUTTON_KEY,
    )
