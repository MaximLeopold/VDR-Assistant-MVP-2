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
from src.ingestion.excel_preprocessing import preprocess_workbook, exclude_workbook
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
    if kind in {"success", "info", "warning", "error"} and isinstance(message, str):
        getattr(st, kind)(message)


def _cancel_setup(state: MutableMapping) -> None:
    clear_new_case_setup_session(state)
    st.rerun()


def _set_setup_candidate(state: MutableMapping, folder: Path, case_id: str) -> None:
    canonical_folder = str(folder.expanduser().resolve())
    if (
        state.get(SETUP_FOLDER_KEY) != canonical_folder
        or state.get(SETUP_CASE_ID_KEY) != case_id
    ):
        state.pop(SETUP_UPLOAD_RESULT_KEY, None)
    state[SETUP_FOLDER_KEY] = canonical_folder
    state[SETUP_CASE_ID_KEY] = case_id


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
        placeholder=r"C:\Projects\Case B\VDR",
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

    _set_setup_candidate(state, preview.vdr_folder, preview.case_id)
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

    st.caption(f"Excel workbooks to prepare: {preview.preprocess_files}")
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
                not preview.can_create_manifest or state.get(SETUP_ACTION_KEY, False)
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


def _render_excel_preparation(manifest, vdr_folder):
    workbooks = [f for f in manifest.files if f.classification_status == "preprocess"]
    if not workbooks:
        return True
    st.subheader("Prepare Excel knowledge")
    st.caption(
        "Visible worksheet content becomes searchable. Formulas use stored results and are not recalculated."
    )
    complete = True
    for index, record in enumerate(workbooks):
        prep = record.excel_preprocessing
        status = prep.status if prep else "pending"
        if status not in {"completed", "excluded"}:
            complete = False
        with st.expander(f"{record.relative_path} - {status}"):
            if status == "processing":
                st.warning(
                    "Preprocessing was interrupted. Retry creates a fresh attempt."
                )
            if prep and prep.last_error:
                st.error(prep.last_error)
            if prep and prep.exclusion_reason:
                st.info(prep.exclusion_reason)
            if prep and prep.worksheets:
                st.dataframe(
                    [
                        {
                            "Worksheet": w.worksheet_name,
                            "Tab": w.worksheet_index,
                            "Outcome": w.outcome,
                            "Reason": w.reason,
                        }
                        for w in prep.worksheets
                    ],
                    hide_index=True,
                )
            if st.button(
                "Prepare workbook" if status == "pending" else "Retry preprocessing",
                key=f"excel_prepare_{index}",
            ):
                try:
                    preprocess_workbook(vdr_folder, record.relative_path)
                except Exception as error:
                    st.error(str(error))
                else:
                    st.rerun()
            reason = st.text_input(
                "Workbook exclusion reason", key=f"excel_exclusion_reason_{index}"
            )
            if st.button(
                "Exclude workbook",
                key=f"excel_exclude_{index}",
                disabled=not reason.strip(),
            ):
                try:
                    exclude_workbook(vdr_folder, record.relative_path, reason)
                except Exception as error:
                    st.error(str(error))
                else:
                    st.rerun()
    if not complete:
        st.info(
            "Complete or explicitly exclude every workbook before associating an empty vector store."
        )
    return complete


def _render_excel_stage(state):
    root = state.get(SETUP_FOLDER_KEY)
    try:
        manifest = load_manifest(root)
        if manifest.vector_store_id or manifest.snapshot_state == "sealed":
            state[SETUP_STEP_KEY] = "complete"
            st.rerun()
        complete = _render_excel_preparation(manifest, root)
    except (ManifestPersistenceError, OSError) as error:
        st.error(str(error))
        return
    if complete and st.button(
        "Continue to vector-store association",
        key="excel_coverage_reviewed",
        type="primary",
    ):
        state[SETUP_STEP_KEY] = "association"
        st.rerun()
    if st.button("Cancel", key="cancel_excel_preparation"):
        _cancel_setup(state)


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
        st.error("The existing manifest is invalid or unreadable. It was not changed.")
        if st.button("Cancel", key="cancel_invalid_setup_manifest"):
            _cancel_setup(state)
        return

    if persisted_id is not None:
        state[SETUP_STEP_KEY] = "complete"
        state[SETUP_COMPLETED_KEY] = True
        st.rerun()

    workbooks = [f for f in manifest.files if f.classification_status == "preprocess"]
    if any(
        f.excel_preprocessing is None
        or f.excel_preprocessing.status not in {"completed", "excluded"}
        for f in workbooks
    ):
        state[SETUP_STEP_KEY] = "excel_preparation"
        st.rerun()
    if workbooks and st.button(
        "Review Excel coverage", key="review_excel_before_association"
    ):
        state[SETUP_STEP_KEY] = "excel_preparation"
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
    except CaseVectorStorePersistenceError as error:
        message = f"Association persistence failed. Preserve exact vector-store ID {error.vector_store_id}. Retry this same ID; do not create another store."
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
            "Phase 1 completion could not be confirmed from the persisted " "manifest."
        )
        if st.button("Cancel", key="cancel_unconfirmed_setup"):
            _cancel_setup(state)
        return

    if manifest.snapshot_state == "sealed":
        state[SETUP_STEP_KEY] = "registration_ready"
        st.rerun()

    st.subheader("Step 4 — Phase 1 complete")
    st.success("The new case foundation has been prepared.")
    st.write(f"**Case name:** {manifest.case_name}")
    st.write(f"**Technical case ID:** {state.get(SETUP_CASE_ID_KEY, '')}")
    st.write(f"**Associated vector store:** {mask_vector_store_id(vector_store_id)}")
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
        "Completed": plan.count(UploadDisposition.COMPLETED),
        "New eligible": plan.count(UploadDisposition.INITIAL_CANDIDATE),
        "No-ID retryable": plan.count(UploadDisposition.RETRY_CANDIDATE),
        "Known-ID pending": sum(
            r.disposition == UploadDisposition.RECOVERY_ONLY
            and r.indexing_status != "failed"
            for r in plan.rows
        ),
        "Known-ID failed": sum(
            r.disposition == UploadDisposition.RECOVERY_ONLY
            and r.indexing_status == "failed"
            for r in plan.rows
        ),
        "Local target issues": sum(r.preflight_ok is False for r in plan.rows),
        "Inconsistent": plan.count(UploadDisposition.INCONSISTENT),
        "Ignored / unsupported": plan.count(UploadDisposition.IGNORED)
        + plan.count(UploadDisposition.UNSUPPORTED),
    }


def _render_upload_plan_metrics(plan) -> None:
    columns = [*st.columns(4), *st.columns(4)]
    for column, (label, value) in zip(
        columns, _upload_plan_counts(plan).items(), strict=True
    ):
        column.metric(label, value)


def _phase2_progress_callback(progress, status):
    def callback(event: UploadProgressEvent) -> None:
        if event.total_candidates:
            completed_fraction = max(event.current_index - 1, 0)
            if event.kind in {"indexing_completed", "file_failed"}:
                completed_fraction = event.current_index
            progress.progress(min(completed_fraction / event.total_candidates, 1.0))
        if event.display_label:
            status.info(
                f"{event.kind.replace('_', ' ').title()}: " f"{event.display_label}"
            )
        elif event.sanitized_message:
            status.info(event.sanitized_message)

    return callback


def _run_ingestion_action(state, plan, *, recover_only=False, reattach_keys=()):
    state[SETUP_ACTION_KEY] = True
    if validate_settings():
        state[SETUP_ACTION_KEY] = False
        st.error("OpenAI API access is not configured.")
        return
    progress, status = st.progress(0.0), st.empty()
    try:
        result = run_manifest_upload(
            str(plan.vdr_folder),
            client_factory=get_openai_client,
            progress_callback=_phase2_progress_callback(progress, status),
            expected_context=plan.context,
            recover_only=recover_only,
            reattach_keys=reattach_keys,
        )
    except Exception:
        st.error(
            "Ingestion stopped unexpectedly. Reload the manifest before another action."
        )
        return
    finally:
        state[SETUP_ACTION_KEY] = False
    state[SETUP_UPLOAD_RESULT_KEY] = result
    state[SETUP_STEP_KEY] = "upload_result"
    st.rerun()


def _render_ingestion_actions(state, plan):
    disabled = bool(plan.blockers) or state.get(SETUP_ACTION_KEY, False)
    st.caption(
        "One operator may ingest this candidate at a time. Each action starts one sequential pass."
    )
    if plan.candidates or plan.recovery_candidates:
        if st.button(
            "Continue ingestion",
            type="primary",
            key="confirm_manifest_ingestion",
            disabled=disabled,
        ):
            _run_ingestion_action(state, plan)
    if plan.recovery_candidates:
        if st.button(
            "Refresh / recover known files",
            key="recover_known_files",
            disabled=disabled,
        ):
            _run_ingestion_action(state, plan, recover_only=True)
    previous = state.get(SETUP_UPLOAD_RESULT_KEY)
    if (
        isinstance(previous, UploadBatchResult)
        and previous.plan.context == plan.context
    ):
        keys = {c.key for c in plan.recovery_candidates}
        for index, item in enumerate(previous.files):
            if item.can_attach_existing and item.key in keys:
                st.write(f"Attachment was absent: {item.display_label}")
                if st.button(
                    "Attach existing file",
                    key=f"attach_existing_{index}",
                    disabled=disabled,
                    help="Recheck exact File and store, then attach the persisted File ID once if still absent.",
                ):
                    _run_ingestion_action(
                        state, plan, recover_only=True, reattach_keys=(item.key,)
                    )


def _render_upload_preview(state: MutableMapping) -> None:
    vdr_folder = state.get(SETUP_FOLDER_KEY)
    if not isinstance(vdr_folder, str):
        state[SETUP_STEP_KEY] = "details"
        _set_message(state, "error", "Select the VDR folder again.")
        st.rerun()
    try:
        plan = prepare_manifest_upload(vdr_folder)
    except UploadPreparationError as error:
        st.error(str(error))
        if st.button("Return to case selection", key="cancel_upload_preparation"):
            _cancel_setup(state)
        return
    st.subheader("Step 5 ? Ingestion preview")
    st.caption(
        "This preview reloads the manifest and performs local read-only checks. Remote status is checked only when you start ingestion or recovery."
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
        "Ensure the VDR folder is locally available. For OneDrive folders, use ?Always keep on this device?. Preflight may download cloud placeholders."
    )
    for blocker in plan.blockers:
        st.error(blocker)
    if any(row.preflight_ok is False for row in plan.rows):
        st.warning(
            "Local target issues will be recorded individually; ingestion can continue for other targets."
        )
    if plan.count(UploadDisposition.RETRY_CANDIDATE):
        st.info(
            "Targets without a saved File ID can be tried again in this pass. An earlier upload may remain as an unused remote File."
        )
    _render_ingestion_actions(state, plan)
    readiness = assess_case_readiness(vdr_folder)
    if readiness.is_ready:
        if st.button(
            "Continue to registration", type="primary", key="ready_without_upload"
        ):
            state[SETUP_STEP_KEY] = "registration_ready"
            st.rerun()
    elif not plan.can_execute:
        st.warning(
            "The case is not ready for registration. Resolve candidate issues before continuing."
        )
    if st.button("Return to case selection", key="leave_empty_upload_plan"):
        _cancel_setup(state)


def _file_id_recovery_message(result: UploadBatchResult) -> str:
    persisted = (result.recovery_details or {}).get(
        "last_confirmed_persisted_state", {}
    )
    if persisted.get("openai_file_id") == result.recovery_file_id:
        if persisted.get("indexing_status") == "in_progress" and not persisted.get(
            "last_error"
        ):
            return (
                "The OpenAI file ID is persisted. Indexing is pending; use Refresh / "
                "recover known files to check it later. Preserve this ID and do not re-upload."
            )
        return (
            "The OpenAI file ID is persisted, but indexing or its checkpoint needs "
            "inspection. Preserve this ID and do not re-upload the file."
        )
    return (
        "OpenAI returned a file ID, but persistence could not be confirmed. "
        "Preserve this diagnostic and resolve the checkpoint failure before another pass. If the manifest still has no ID, a later pass may create an orphan File."
    )


def _render_upload_result(state: MutableMapping) -> None:
    result = state.get(SETUP_UPLOAD_RESULT_KEY)
    vdr_folder = state.get(SETUP_FOLDER_KEY)
    if not isinstance(result, UploadBatchResult) or not isinstance(vdr_folder, str):
        state[SETUP_STEP_KEY] = "upload_preview"
        st.rerun()

    st.subheader("Step 6 — Upload result")
    st.write(f"**Pass: {result.pass_outcome.title()}**")
    if result.critically_stopped:
        st.error(result.message)
    elif result.pass_outcome == "paused":
        st.warning(result.message)
    else:
        st.success(result.message)
    metrics = st.columns(5)
    for column, (label, value) in zip(
        metrics,
        {
            "Completed": result.total_completed_count,
            "No-ID retryable": result.no_id_retryable_count,
            "New eligible": result.new_eligible_count,
            "Known-ID pending": result.known_pending_count,
            "Known-ID failed": result.known_failed_count,
        }.items(),
        strict=True,
    ):
        column.metric(label, value)

    if result.files:
        st.dataframe(
            [
                {
                    "Source": item.display_label,
                    "Outcome": item.outcome.replace("_", " "),
                    "Message": item.message,
                }
                for item in result.files
            ],
            hide_index=True,
            width="stretch",
        )

    if result.recovery_details:
        with st.expander("Candidate recovery diagnostics"):
            st.json(result.recovery_details)
            st.info(
                "Known IDs are recovered without re-upload. No-ID targets may be tried in a later pass. Preserve diagnostics for stopped checkpoints."
            )

    if result.recovery_file_id is not None:
        with st.expander("OpenAI file-ID recovery information"):
            if result.critically_stopped:
                st.error(_file_id_recovery_message(result))
            else:
                st.info(_file_id_recovery_message(result))
            st.code(result.recovery_file_id, language=None)

    readiness = assess_case_readiness(vdr_folder)
    if readiness.is_ready:
        st.success(
            f"Strict readiness passed for all {readiness.supported_count} "
            "searchable targets."
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
        try:
            plan = prepare_manifest_upload(vdr_folder)
        except UploadPreparationError as error:
            st.error(str(error))
        else:
            for blocker in plan.blockers:
                st.error(blocker)
            _render_ingestion_actions(state, plan)
        if st.button("Review local manifest", key="review_upload_again"):
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
        st.info(
            "If sealing completed, the snapshot remains sealed. Registration can be retried safely."
        )
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
    elif step == "excel_preparation":
        _render_excel_stage(state)
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
