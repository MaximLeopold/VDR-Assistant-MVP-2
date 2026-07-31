"""Streamlit UI for preparing and registering one new VDR case."""

from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from pathlib import Path

import streamlit as st

from src.config.case_registry import (
    CaseRegistryError,
    PreparedCase,
    register_prepared_case,
)
from src.config.settings import validate_settings
from src.ingestion.case_vector_store import (
    CaseVectorStoreAlreadyUsedError,
    CaseVectorStoreConflictError,
    CaseVectorStoreNotEmptyError,
    CaseVectorStorePersistenceError,
    associate_empty_case_vector_store,
    mask_vector_store_id,
)
from src.ingestion.case_readiness import assess_case_readiness
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
from src.ingestion.upload_workflow import (
    UploadBatchResult,
    UploadDisposition,
    UploadPreparationError,
    UploadProgressEvent,
    prepare_manifest_upload,
    run_manifest_upload,
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
SETUP_UPLOAD_RESULT_KEY = "setup_upload_result"
SETUP_SAFE_RETRY_KEY = "setup_safe_retry_paths"
SETUP_REGISTRATION_RESULT_KEY = "setup_registration_result"

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
    SETUP_UPLOAD_RESULT_KEY,
    SETUP_SAFE_RETRY_KEY,
    SETUP_REGISTRATION_RESULT_KEY,
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
    st.info(
        "Continue to review the fixed manifest plan, upload all safely eligible "
        "documents, and register the case."
    )

    continue_column, return_column = st.columns(2)
    with continue_column:
        if st.button(
            "Continue case preparation",
            type="primary",
            key="continue_case_preparation",
        ):
            state[SETUP_STEP_KEY] = "upload_preview"
            st.rerun()
    with return_column:
        if st.button("Return to case selection", key="finish_new_case_setup"):
            _cancel_setup(state)


def _upload_plan_counts(plan) -> dict[str, int]:
    return {
        "Eligible": len(plan.candidates),
        "Completed": plan.count(UploadDisposition.COMPLETED),
        "Safe retry": plan.count(UploadDisposition.SAFE_RETRY),
        "Uncertain": plan.count(UploadDisposition.UNCERTAIN),
        "Recovery": plan.count(UploadDisposition.RECOVERY_ONLY),
        "Inconsistent": plan.count(UploadDisposition.INCONSISTENT),
        "Unsupported": plan.count(UploadDisposition.UNSUPPORTED),
        "Ignored": plan.count(UploadDisposition.IGNORED),
    }


def _render_upload_plan_metrics(plan) -> None:
    counts = _upload_plan_counts(plan)
    first_row = st.columns(4)
    second_row = st.columns(4)
    for column, (label, value) in zip(
        [*first_row, *second_row], counts.items(), strict=True
    ):
        column.metric(label, value)


def _phase2_progress_callback(progress, status):
    def callback(event: UploadProgressEvent) -> None:
        if event.total_candidates:
            completed_fraction = max(event.current_index - 1, 0)
            if event.kind in {"indexing_completed", "file_failed"}:
                completed_fraction = event.current_index
            progress.progress(
                min(completed_fraction / event.total_candidates, 1.0)
            )
        if event.relative_path:
            status.info(
                f"{event.kind.replace('_', ' ').title()}: "
                f"{event.relative_path}"
            )
        elif event.sanitized_message:
            status.info(event.sanitized_message)

    return callback


def _render_upload_preview(state: MutableMapping) -> None:
    vdr_folder = state.get(SETUP_FOLDER_KEY)
    if not isinstance(vdr_folder, str):
        state[SETUP_STEP_KEY] = "details"
        _set_message(state, "error", "Select the VDR folder again.")
        st.rerun()

    safe_retry_paths = state.get(SETUP_SAFE_RETRY_KEY, ())
    if not isinstance(safe_retry_paths, (tuple, list, set, frozenset)):
        safe_retry_paths = ()
    try:
        plan = prepare_manifest_upload(
            vdr_folder,
            safe_retry_paths=safe_retry_paths,
        )
    except UploadPreparationError as error:
        st.error(str(error))
        if st.button("Return to case selection", key="cancel_upload_preparation"):
            _cancel_setup(state)
        return

    st.subheader("Step 5 — Upload preview")
    st.caption(
        "This preview reloads the fixed Phase 1 manifest and performs only "
        "local, read-only checks. It does not contact OpenAI or change files."
    )
    st.write(f"**Case name:** {plan.case_name}")
    st.write(
        f"**Associated vector store:** {mask_vector_store_id(plan.vector_store_id)}"
    )
    _render_upload_plan_metrics(plan)
    if plan.rows:
        st.dataframe(
            [row.as_display_dict() for row in plan.rows],
            hide_index=True,
            width="stretch",
        )

    st.info(
        "Ensure the complete VDR folder is locally available. For OneDrive-"
        "backed folders, use ‘Always keep on this device’. Preflight may "
        "download cloud-placeholder files so their local readability can be checked."
    )
    for blocker in plan.blockers:
        st.error(blocker)

    recovery_count = sum(
        plan.count(disposition)
        for disposition in (
            UploadDisposition.UNCERTAIN,
            UploadDisposition.RECOVERY_ONLY,
            UploadDisposition.INCONSISTENT,
            UploadDisposition.CLASSIFICATION_ERROR,
        )
    )
    if recovery_count:
        st.warning(
            "Some records require terminal-assisted recovery. Safe candidates "
            "may still be uploaded, but readiness and registration remain blocked."
        )

    readiness = assess_case_readiness(vdr_folder)
    if not plan.candidates:
        if readiness.is_ready:
            if st.button(
                "Continue to registration",
                type="primary",
                key="ready_without_upload",
            ):
                state[SETUP_STEP_KEY] = "registration_ready"
                st.rerun()
        else:
            st.warning("No files are safely eligible for automatic upload.")
        if st.button("Return to case selection", key="leave_empty_upload_plan"):
            _cancel_setup(state)
        return

    upload_clicked = st.button(
        "Upload and index all eligible files",
        type="primary",
        key="confirm_manifest_ingestion",
        disabled=bool(plan.blockers) or state.get(SETUP_ACTION_KEY, False),
        help="This is the explicit ingestion confirmation.",
    )
    if not upload_clicked:
        return

    state[SETUP_ACTION_KEY] = True
    missing_settings = validate_settings()
    if missing_settings:
        state[SETUP_ACTION_KEY] = False
        st.error("OpenAI API access is not configured.")
        return

    progress = st.progress(0.0)
    status = st.empty()
    try:
        result = run_manifest_upload(
            vdr_folder,
            client_factory=get_openai_client,
            progress_callback=_phase2_progress_callback(progress, status),
            safe_retry_paths=safe_retry_paths,
        )
    except Exception:
        state[SETUP_ACTION_KEY] = False
        st.error("The upload workflow stopped unexpectedly before completion.")
        st.info("Reload the persisted manifest status before trying another action.")
        return
    state[SETUP_UPLOAD_RESULT_KEY] = result
    state[SETUP_SAFE_RETRY_KEY] = result.safe_retry_paths
    state[SETUP_ACTION_KEY] = False
    state[SETUP_STEP_KEY] = "upload_result"
    st.rerun()


def _render_upload_result(state: MutableMapping) -> None:
    result = state.get(SETUP_UPLOAD_RESULT_KEY)
    vdr_folder = state.get(SETUP_FOLDER_KEY)
    if not isinstance(result, UploadBatchResult) or not isinstance(vdr_folder, str):
        state[SETUP_STEP_KEY] = "upload_preview"
        st.rerun()

    st.subheader("Step 6 — Upload result")
    if result.critically_stopped:
        st.error(result.message)
    elif result.succeeded:
        st.success(result.message)
    else:
        st.warning("The safe candidates finished, but the case needs attention.")

    metrics = st.columns(4)
    metrics[0].metric("Completed", result.completed_count)
    metrics[1].metric("Safe retry", result.safely_retryable_count)
    metrics[2].metric("Needs recovery", result.recovery_count)
    metrics[3].metric("Already complete", result.skipped_completed_count)

    if result.files:
        st.dataframe(
            [
                {
                    "Relative path": item.relative_path,
                    "Outcome": item.outcome.replace("_", " "),
                    "Message": item.message,
                }
                for item in result.files
            ],
            hide_index=True,
            width="stretch",
        )

    if result.recovery_file_id is not None:
        with st.expander("Critical file-ID recovery information"):
            st.error(
                "OpenAI returned a file ID, but it could not be saved. Do not "
                "re-upload this file. Preserve this ID for terminal-assisted recovery."
            )
            st.code(result.recovery_file_id, language=None)

    readiness = assess_case_readiness(vdr_folder)
    if readiness.is_ready:
        st.success(
            f"Strict readiness passed for all {readiness.supported_count} "
            "supported documents."
        )
        if st.button(
            "Continue to registration",
            type="primary",
            key="continue_to_registration",
        ):
            state[SETUP_STEP_KEY] = "registration_ready"
            st.rerun()
    else:
        st.warning("The case is not ready for registration.")
        for reason in readiness.blocking_reasons:
            st.write(f"- {reason}")
        label = (
            "Review safe retry"
            if result.safe_retry_paths
            else "Reload upload status"
        )
        if st.button(label, key="review_upload_again"):
            state[SETUP_STEP_KEY] = "upload_preview"
            st.rerun()

    if st.button("Return to case selection", key="leave_upload_result"):
        _cancel_setup(state)


def _render_registration(
    state: MutableMapping,
    *,
    registry_path: str | Path | None,
    repository_root: Path,
) -> None:
    vdr_folder = state.get(SETUP_FOLDER_KEY)
    case_id = state.get(SETUP_CASE_ID_KEY)
    if not isinstance(vdr_folder, str) or not isinstance(case_id, str):
        state[SETUP_STEP_KEY] = "details"
        _set_message(state, "error", "Re-enter the case details.")
        st.rerun()

    readiness = assess_case_readiness(vdr_folder)
    if not readiness.is_ready:
        st.error("The case is no longer ready for registration.")
        if st.button("Return to upload status", key="registration_not_ready"):
            state[SETUP_STEP_KEY] = "upload_preview"
            st.rerun()
        return

    st.subheader("Step 7 — Register prepared case")
    st.success(
        f"All {readiness.supported_count} supported documents are uploaded "
        "and indexed."
    )
    st.write(f"**Technical case ID:** {case_id}")
    st.caption(
        "Registration writes only the technical case ID and normalized local "
        "VDR folder path to the ignored local registry."
    )

    register_clicked = st.button(
        "Register prepared case",
        type="primary",
        key="confirm_case_registration",
        disabled=state.get(SETUP_ACTION_KEY, False),
        help="This is a separate explicit local registration action.",
    )
    if not register_clicked:
        return

    state[SETUP_ACTION_KEY] = True
    try:
        result = register_prepared_case(
            registry_path,
            case_id,
            vdr_folder,
            base_dir=repository_root,
        )
    except CaseRegistryError as error:
        state[SETUP_ACTION_KEY] = False
        st.error(str(error))
        st.info("Ingestion is unchanged. Registration can be retried safely.")
        return

    state[SETUP_ACTION_KEY] = False
    state[SETUP_REGISTRATION_RESULT_KEY] = result
    state[SETUP_STEP_KEY] = "registered_complete"
    st.rerun()


def _render_registered_complete(state: MutableMapping) -> None:
    result = state.get(SETUP_REGISTRATION_RESULT_KEY)
    case_id = getattr(result, "case_id", state.get(SETUP_CASE_ID_KEY, ""))
    st.subheader("Step 8 — Case preparation complete")
    st.success(f"Case {case_id} is registered and ready for selection.")
    st.info(
        "Return to the startup selector or restart Streamlit. The new case "
        "will not be activated automatically in this session."
    )
    if st.button("Return to case selection", key="finish_registered_case"):
        _cancel_setup(state)


def render_new_case_setup(
    state: MutableMapping,
    registered_cases: Sequence[PreparedCase],
    *,
    repository_root: str | Path,
    registry_path: str | Path | None,
) -> None:
    """Render the staged preparation flow without activating a Q&A case."""

    st.header("Prepare a new VDR case")
    st.caption(
        "Prepare a reviewed local manifest, associate a manually created empty "
        "vector store, upload sequentially, and register the ready case."
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
    elif step == "upload_preview":
        _render_upload_preview(state)
    elif step == "upload_result":
        _render_upload_result(state)
    elif step == "registration_ready":
        _render_registration(
            state,
            registry_path=registry_path,
            repository_root=root,
        )
    elif step == "registered_complete":
        _render_registered_complete(state)
    else:
        _render_details(state, registered_cases, root)
