"""Streamlit UI for Phase 1 preparation of one unregistered VDR case."""

from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from pathlib import Path

import streamlit as st

from src.config.case_registry import PreparedCase
from src.config.settings import validate_settings
from src.ingestion.case_vector_store import (
    CaseVectorStoreAlreadyUsedError,
    CaseVectorStoreConflictError,
    CaseVectorStoreNotEmptyError,
    CaseVectorStorePersistenceError,
    associate_empty_case_vector_store,
    mask_vector_store_id,
)
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    derive_manifest_paths,
    load_manifest,
)
from src.ingestion.new_case_setup import (
    ExistingManifestError,
    NewCasePreview,
    NewCaseSetupError,
    NewCaseValidationError,
    StalePreviewError,
    build_new_case_preview,
    create_new_case_manifest,
)
from src.ingestion.vector_store_manager import (
    InvalidVectorStoreIdError,
    VectorStoreError,
    normalize_vector_store_id,
)
from src.retrieval.openai_file_search import get_openai_client


SETUP_ACTIVE_KEY = "setup_active"
SETUP_STEP_KEY = "setup_step"
SETUP_FOLDER_KEY = "setup_vdr_folder"
SETUP_CASE_ID_KEY = "setup_case_id"
SETUP_PREVIEW_KEY = "setup_scan_summary"
SETUP_FINGERPRINT_KEY = "setup_scan_fingerprint"
SETUP_ACTION_KEY = "setup_action_in_progress"
SETUP_MESSAGE_KEY = "setup_last_result"
SETUP_COMPLETED_KEY = "setup_completed"
FOLDER_INPUT_KEY = "setup_folder_input"
CASE_ID_INPUT_KEY = "setup_case_id_input"
VECTOR_STORE_INPUT_KEY = "setup_vector_store_input"

SETUP_KEYS = (
    SETUP_ACTIVE_KEY,
    SETUP_STEP_KEY,
    SETUP_FOLDER_KEY,
    SETUP_CASE_ID_KEY,
    SETUP_PREVIEW_KEY,
    SETUP_FINGERPRINT_KEY,
    SETUP_ACTION_KEY,
    SETUP_MESSAGE_KEY,
    SETUP_COMPLETED_KEY,
    FOLDER_INPUT_KEY,
    CASE_ID_INPUT_KEY,
    VECTOR_STORE_INPUT_KEY,
)


def initialize_new_case_setup_session(state: MutableMapping) -> None:
    """Initialize only the setup mode flag until the workflow is opened."""

    state.setdefault(SETUP_ACTIVE_KEY, False)


def is_new_case_setup_active(state: MutableMapping) -> bool:
    return state.get(SETUP_ACTIVE_KEY) is True


def clear_new_case_setup_session(state: MutableMapping) -> None:
    """Clear UI state without deleting any persisted Phase 1 work."""

    for key in SETUP_KEYS:
        state.pop(key, None)


def start_new_case_setup(state: MutableMapping) -> None:
    """Enter a fresh Phase 1 UI workflow without changing active-case state."""

    clear_new_case_setup_session(state)
    state[SETUP_ACTIVE_KEY] = True
    state[SETUP_STEP_KEY] = "details"
    state[SETUP_ACTION_KEY] = False
    state[SETUP_COMPLETED_KEY] = False


def _set_message(state: MutableMapping, kind: str, message: str) -> None:
    state[SETUP_MESSAGE_KEY] = {"kind": kind, "message": message}


def _render_pending_message(state: MutableMapping) -> None:
    result = state.pop(SETUP_MESSAGE_KEY, None)
    if not isinstance(result, dict):
        return
    kind = result.get("kind")
    message = result.get("message")
    if kind in {"success", "info", "warning", "error"} and isinstance(
        message, str
    ):
        getattr(st, kind)(message)


def _cancel_setup(state: MutableMapping) -> None:
    clear_new_case_setup_session(state)
    st.rerun()


def _render_details(
    state: MutableMapping,
    registered_cases: Sequence[PreparedCase],
    repository_root: Path,
) -> None:
    st.subheader("Step 1 — New case details")
    st.caption(
        "Enter an existing local VDR folder and a non-confidential technical "
        "case ID. Nothing is scanned until you continue."
    )

    folder_input = st.text_input(
        "Local VDR folder",
        key=FOLDER_INPUT_KEY,
        placeholder=r'C:\Projects\Case B\VDR',
    )
    case_id_input = st.text_input(
        "Technical case ID",
        key=CASE_ID_INPUT_KEY,
        placeholder="case-02",
        help="1-64 letters, numbers, hyphens, or underscores.",
    )

    primary, secondary = st.columns(2)
    with primary:
        validate_clicked = st.button(
            "Validate and scan",
            type="primary",
            key="validate_new_case",
            disabled=state.get(SETUP_ACTION_KEY, False),
        )
    with secondary:
        if st.button("Cancel", key="cancel_new_case_details"):
            _cancel_setup(state)

    if not validate_clicked:
        return

    state[SETUP_ACTION_KEY] = True
    try:
        preview = build_new_case_preview(
            folder_input,
            case_id_input,
            registered_cases=registered_cases,
            repository_root=repository_root,
        )
    except NewCaseValidationError as error:
        state[SETUP_ACTION_KEY] = False
        _set_message(state, "error", str(error))
        st.rerun()

    state[SETUP_FOLDER_KEY] = str(preview.vdr_folder)
    state[SETUP_CASE_ID_KEY] = preview.case_id
    state[SETUP_PREVIEW_KEY] = preview
    state[SETUP_FINGERPRINT_KEY] = preview.fingerprint
    state[SETUP_ACTION_KEY] = False

    if preview.state == "resume_association":
        state[SETUP_STEP_KEY] = "association"
        _set_message(
            state,
            "info",
            "A valid unregistered manifest already exists. It was not "
            "overwritten; continue with vector-store association.",
        )
    elif preview.state == "phase1_complete":
        state[SETUP_STEP_KEY] = "complete"
        state[SETUP_COMPLETED_KEY] = True
    else:
        state[SETUP_STEP_KEY] = "preview"
    st.rerun()


def _render_preview_summary(preview: NewCasePreview) -> None:
    st.write(f"**Derived case name:** {preview.case_name}")
    st.write("**Proposed manifest location:**")
    st.code(str(preview.manifest_path), language=None)

    metrics = st.columns(5)
    metrics[0].metric("Total", preview.total_files)
    metrics[1].metric("Supported", preview.supported_files)
    metrics[2].metric("Unsupported", preview.unsupported_files)
    metrics[3].metric("Ignored", preview.ignored_files)
    metrics[4].metric("Errors", preview.error_files)

    if preview.rows:
        st.dataframe(
            [row.as_display_dict() for row in preview.rows],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("The selected folder contains no files.")

    for blocker in preview.blockers:
        st.error(blocker)


def _render_preview(state: MutableMapping) -> None:
    preview = state.get(SETUP_PREVIEW_KEY)
    if not isinstance(preview, NewCasePreview):
        state[SETUP_STEP_KEY] = "details"
        _set_message(state, "error", "Scan the folder again before continuing.")
        st.rerun()

    st.subheader("Step 2 — Scan preview")
    st.caption(
        "Review the read-only scan. Document contents were not read, and no "
        "manifest or OpenAI resource has been changed."
    )
    _render_preview_summary(preview)

    create_column, scan_column, cancel_column = st.columns(3)
    with create_column:
        create_clicked = st.button(
            "Create manifest",
            type="primary",
            key="create_new_case_manifest",
            disabled=(
                not preview.can_create_manifest
                or state.get(SETUP_ACTION_KEY, False)
            ),
        )
    with scan_column:
        scan_again = st.button("Scan again", key="scan_new_case_again")
    with cancel_column:
        cancel = st.button("Cancel", key="cancel_new_case_preview")

    if cancel:
        _cancel_setup(state)
    if scan_again:
        state.pop(SETUP_PREVIEW_KEY, None)
        state.pop(SETUP_FINGERPRINT_KEY, None)
        state[SETUP_STEP_KEY] = "details"
        st.rerun()
    if not create_clicked:
        return

    state[SETUP_ACTION_KEY] = True
    try:
        result = create_new_case_manifest(
            preview.vdr_folder,
            state.get(SETUP_FINGERPRINT_KEY, ""),
        )
    except StalePreviewError as error:
        state.pop(SETUP_PREVIEW_KEY, None)
        state.pop(SETUP_FINGERPRINT_KEY, None)
        state[SETUP_STEP_KEY] = "details"
        state[SETUP_ACTION_KEY] = False
        _set_message(state, "error", str(error))
        st.rerun()
    except (ExistingManifestError, NewCaseSetupError) as error:
        state[SETUP_ACTION_KEY] = False
        _set_message(state, "error", str(error))
        st.rerun()

    state[SETUP_ACTION_KEY] = False
    state[SETUP_STEP_KEY] = "association"
    state.pop(SETUP_PREVIEW_KEY, None)
    state.pop(SETUP_FINGERPRINT_KEY, None)
    _set_message(
        state,
        "success",
        f"Manifest created for {result.manifest.case_name}.",
    )
    st.rerun()


def _render_association(
    state: MutableMapping,
    registered_cases: Sequence[PreparedCase],
) -> None:
    vdr_folder = state.get(SETUP_FOLDER_KEY)
    if not isinstance(vdr_folder, str):
        state[SETUP_STEP_KEY] = "details"
        _set_message(state, "error", "Select the VDR folder again.")
        st.rerun()

    try:
        manifest = load_manifest(vdr_folder)
        manifest_path = derive_manifest_paths(vdr_folder).manifest_path
        persisted_id = normalize_vector_store_id(manifest.vector_store_id)
    except InvalidVectorStoreIdError:
        persisted_id = None
    except (ManifestPersistenceError, OSError):
        st.error(
            "The existing manifest is invalid or unreadable. It was not changed."
        )
        if st.button("Cancel", key="cancel_invalid_setup_manifest"):
            _cancel_setup(state)
        return

    if persisted_id is not None:
        state[SETUP_STEP_KEY] = "complete"
        state[SETUP_COMPLETED_KEY] = True
        state.pop(VECTOR_STORE_INPUT_KEY, None)
        st.rerun()

    st.subheader("Step 3 — Associate an empty vector store")
    st.success("Manifest created")
    st.write(f"**Case name:** {manifest.case_name}")
    st.write("**Manifest:**")
    st.code(str(manifest_path), language=None)
    st.info(
        "Create a new empty vector store in the OpenAI Platform, copy its ID, "
        "and paste it below. This application will not create the store."
    )

    candidate_id = st.text_input(
        "OpenAI vector-store ID",
        key=VECTOR_STORE_INPUT_KEY,
        placeholder="vs_...",
    )

    associate_column, cancel_column = st.columns(2)
    with associate_column:
        associate_clicked = st.button(
            "Validate and associate",
            type="primary",
            key="associate_empty_vector_store",
            disabled=state.get(SETUP_ACTION_KEY, False),
        )
    with cancel_column:
        if st.button("Cancel", key="cancel_vector_association"):
            _cancel_setup(state)

    if not associate_clicked:
        return

    state[SETUP_ACTION_KEY] = True
    try:
        if validate_settings():
            raise VectorStoreError("OpenAI API access is not configured.")
        client = get_openai_client()
        associate_empty_case_vector_store(
            client,
            vdr_folder,
            candidate_id,
            registered_cases=registered_cases,
        )
    except InvalidVectorStoreIdError:
        message = "A vector-store ID is required."
    except CaseVectorStoreNotEmptyError as error:
        message = str(error)
    except CaseVectorStoreAlreadyUsedError as error:
        message = str(error)
    except CaseVectorStoreConflictError:
        message = "This case is already associated with another vector store."
    except CaseVectorStorePersistenceError:
        message = (
            "The vector-store association could not be saved. The same ID "
            "can be retried."
        )
    except VectorStoreError:
        message = (
            "The vector store could not be accessed. Verify the ID, the "
            "active OpenAI project, and API-key access."
        )
    except (ManifestPersistenceError, OSError):
        message = "The case manifest could not be loaded or saved safely."
    except Exception:
        message = "The vector store could not be validated safely."
    else:
        state[SETUP_ACTION_KEY] = False
        state[SETUP_STEP_KEY] = "complete"
        state[SETUP_COMPLETED_KEY] = True
        state.pop(VECTOR_STORE_INPUT_KEY, None)
        _set_message(state, "success", "The empty vector store was associated.")
        st.rerun()

    state[SETUP_ACTION_KEY] = False
    st.error(message)


def _render_complete(state: MutableMapping) -> None:
    vdr_folder = state.get(SETUP_FOLDER_KEY)
    if not isinstance(vdr_folder, str):
        state[SETUP_STEP_KEY] = "details"
        st.rerun()

    try:
        manifest = load_manifest(vdr_folder)
        vector_store_id = normalize_vector_store_id(manifest.vector_store_id)
    except (ManifestPersistenceError, InvalidVectorStoreIdError, OSError):
        st.error(
            "Phase 1 completion could not be confirmed from the persisted "
            "manifest."
        )
        if st.button("Cancel", key="cancel_unconfirmed_setup"):
            _cancel_setup(state)
        return

    st.subheader("Step 4 — Phase 1 complete")
    st.success("The new case foundation has been prepared.")
    st.write(f"**Case name:** {manifest.case_name}")
    st.write(f"**Technical case ID:** {state.get(SETUP_CASE_ID_KEY, '')}")
    st.write(
        f"**Associated vector store:** {mask_vector_store_id(vector_store_id)}"
    )
    st.markdown(
        "- Manifest created\n"
        "- Empty vector store validated\n"
        "- Vector-store association saved\n"
        "- Documents have not been uploaded\n"
        "- The case has not been registered\n"
        "- The case will not appear in normal case selection yet"
    )
    st.info("Phase 2 will add bulk document ingestion and case registration.")

    if st.button("Return to case selection", key="finish_new_case_setup"):
        _cancel_setup(state)


def render_new_case_setup(
    state: MutableMapping,
    registered_cases: Sequence[PreparedCase],
    *,
    repository_root: str | Path,
) -> None:
    """Render the staged Phase 1 flow without activating a Q&A case."""

    st.header("Prepare a new VDR case")
    st.caption(
        "Phase 1 creates a local manifest and associates a manually created "
        "empty vector store. It does not upload or register the case."
    )
    _render_pending_message(state)

    step = state.get(SETUP_STEP_KEY, "details")
    root = Path(repository_root).expanduser().resolve()
    if step == "preview":
        _render_preview(state)
    elif step == "association":
        _render_association(state, registered_cases)
    elif step == "complete":
        _render_complete(state)
    else:
        _render_details(state, registered_cases, root)
