"""Sequential, manifest-driven ingestion and exact-ID recovery.

Operational precondition: one writer per candidate. Checkpoints detect stale state;
there is deliberately no distributed lock or exactly-once File creation promise.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path

from openai import NotFoundError
from src.ingestion.case_readiness import (
    manifest_belongs_to_folder,
    assess_manifest_readiness,
)
from src.ingestion.file_filter import SUPPORTED_EXTENSIONS
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    derive_manifest_paths,
    load_manifest,
    save_manifest,
)
from src.ingestion.excel_preprocessing import require_mutable
from src.ingestion.uploader import (
    attach_file_and_poll,
    upload_openai_file,
    DefinitePreRemoteUploadError,
    validate_attachment,
)
from src.ingestion.upload_targets import (
    UploadTargetKey,
    UploadTargetIntegrityError,
    enumerate_upload_targets,
    target_for_key,
    preflight_target,
)
from src.ingestion.vector_store_manager import (
    normalize_vector_store_id,
    InvalidVectorStoreIdError,
)
from src.ingestion.known_file_recovery import inspect_known_file, verify_known_resources
from src.ingestion.remote_errors import (
    RemoteProtocolError,
    UnderlyingFileMissingError,
    failure_scope,
    remote_failure_message,
)


class UploadWorkflowError(Exception):
    """A safely reportable ingestion workflow failure."""


class UploadPreparationError(UploadWorkflowError):
    """A valid, mutable candidate could not be loaded."""


class UploadDisposition(str, Enum):
    INITIAL_CANDIDATE = "initial_candidate"
    RETRY_CANDIDATE = "retry_candidate"
    COMPLETED = "completed"
    RECOVERY_ONLY = "recovery_only"
    INCONSISTENT = "inconsistent"
    UNSUPPORTED = "unsupported"
    IGNORED = "ignored"
    CLASSIFICATION_ERROR = "classification_error"


@dataclass(frozen=True)
class RecordClassification:
    disposition: UploadDisposition
    eligible: bool
    message: str


@dataclass(frozen=True)
class UploadPlanRow:
    key: UploadTargetKey
    display_label: str
    extension: str
    size_bytes: int
    classification_status: str
    upload_status: str
    indexing_status: str
    disposition: UploadDisposition
    eligible: bool
    preflight_ok: bool | None
    blocking_reason: str | None

    def as_display_dict(self):
        return {
            "Source": self.display_label,
            "Extension": self.extension,
            "Size (bytes)": self.size_bytes,
            "Upload": self.upload_status,
            "Indexing": self.indexing_status,
            "Eligibility": self.disposition.value.replace("_", " "),
            "Preflight": (
                "passed"
                if self.preflight_ok
                else (
                    "target issue" if self.preflight_ok is False else "not applicable"
                )
            ),
            "Reason": self.blocking_reason or "",
        }


@dataclass(frozen=True)
class UploadCandidate:
    key: UploadTargetKey
    display_label: str
    local_path: Path | None
    expected_state: dict


@dataclass(frozen=True)
class CandidateContext:
    vdr_folder: Path
    manifest_path: Path
    vector_store_id: str
    manifest_identity: str


def candidate_context(manifest: VDRManifest, root: Path) -> CandidateContext:
    paths = derive_manifest_paths(root)
    # created_at and all frozen snapshot content identify this candidate.
    # Ordinary checkpoints change updated_at and target state, not this identity.
    identity = manifest.model_dump(mode="json")
    identity.pop("updated_at")
    identity.pop("snapshot_state")
    remote_fields = (
        "openai_file_id",
        "upload_status",
        "indexing_status",
        "upload_attempts",
        "last_error",
    )
    for source in identity["files"]:
        for owner in (source, *source["derived_artifacts"]):
            for field in remote_fields:
                owner.pop(field)
    digest = hashlib.sha256(
        json.dumps(
            identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    return CandidateContext(
        paths.vdr_folder,
        paths.manifest_path.resolve(),
        normalize_vector_store_id(manifest.vector_store_id),
        digest,
    )


@dataclass(frozen=True)
class UploadPlan:
    vdr_folder: Path
    case_name: str
    vector_store_id: str
    context: CandidateContext
    rows: tuple[UploadPlanRow, ...]
    candidates: tuple[UploadCandidate, ...]
    recovery_candidates: tuple[UploadCandidate, ...]
    blockers: tuple[str, ...]

    @property
    def can_execute(self):
        return bool(self.candidates or self.recovery_candidates) and not self.blockers

    def count(self, disposition):
        return sum(row.disposition == disposition for row in self.rows)

    @property
    def supported_count(self):
        return sum(row.classification_status == "supported" for row in self.rows)


@dataclass(frozen=True)
class UploadProgressEvent:
    kind: str
    key: UploadTargetKey | None = None
    display_label: str | None = None
    current_index: int = 0
    total_candidates: int = 0
    upload_status: str | None = None
    indexing_status: str | None = None
    outcome: str | None = None
    sanitized_message: str | None = None
    masked_file_id: str | None = None


@dataclass(frozen=True)
class BatchFileResult:
    key: UploadTargetKey
    display_label: str
    outcome: str
    message: str
    can_attach_existing: bool = False


@dataclass(frozen=True)
class UploadBatchResult:
    plan: UploadPlan
    files: tuple[BatchFileResult, ...]
    pass_outcome: str
    message: str
    completed_count: int
    total_completed_count: int
    no_id_retryable_count: int
    new_eligible_count: int
    known_pending_count: int
    known_failed_count: int
    skipped_completed_count: int
    ready: bool
    recovery_file_id: str | None = None
    recovery_details: dict | None = None

    @property
    def critically_stopped(self):
        return self.pass_outcome == "stopped"

    @property
    def recovery_count(self):
        return self.known_pending_count + self.known_failed_count

    @property
    def succeeded(self):
        return self.pass_outcome == "finished" and self.ready


ProgressCallback = Callable[[UploadProgressEvent], None]


def classify_manifest_record(record) -> RecordClassification:
    category = getattr(record, "classification_status", "supported")
    excluded = {
        "unsupported": UploadDisposition.UNSUPPORTED,
        "ignored": UploadDisposition.IGNORED,
        "error": UploadDisposition.CLASSIFICATION_ERROR,
        "preprocess": UploadDisposition.RECOVERY_ONLY,
    }
    if category in excluded:
        return RecordClassification(
            excluded[category], False, "Not a direct upload target."
        )
    file_id = record.openai_file_id
    if file_id is not None:
        if (
            not isinstance(file_id, str)
            or not file_id.strip()
            or file_id != file_id.strip()
        ):
            return RecordClassification(
                UploadDisposition.INCONSISTENT,
                False,
                "Unusable persisted File ID; do not upload.",
            )
        if record.upload_status != "uploaded":
            return RecordClassification(
                UploadDisposition.INCONSISTENT,
                False,
                "Known ID has an incompatible upload state; do not upload.",
            )
        if record.indexing_status == "completed":
            return RecordClassification(
                UploadDisposition.COMPLETED, False, "Upload and indexing completed."
            )
        return RecordClassification(
            UploadDisposition.RECOVERY_ONLY,
            False,
            "Recover using the exact persisted File ID.",
        )
    if record.indexing_status == "not_started" and record.upload_status in {
        "not_uploaded",
        "uploading",
        "failed",
    }:
        if record.upload_status == "not_uploaded" and record.upload_attempts == 0:
            return RecordClassification(
                UploadDisposition.INITIAL_CANDIDATE, True, "Ready for initial upload."
            )
        return RecordClassification(
            UploadDisposition.RETRY_CANDIDATE,
            True,
            "No persisted ID: eligible in this operator-started pass; an earlier File may remain orphaned.",
        )
    return RecordClassification(
        UploadDisposition.INCONSISTENT,
        False,
        "Upload, indexing and File ID states are incompatible.",
    )


def preflight_manifest_record(
    vdr_folder: str | Path,
    record: VDRFileRecord,
) -> tuple[Path | None, str | None]:
    """Validate one intended candidate and minimally probe readability."""

    root = Path(vdr_folder).expanduser().resolve()
    relative_path = Path(record.relative_path)
    if relative_path.is_absolute() or relative_path.drive:
        raise UploadTargetIntegrityError("Absolute stored paths are not allowed.")

    try:
        candidate = (root / relative_path).resolve()
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise UploadTargetIntegrityError(
            "The stored path escapes the selected VDR folder."
        )

    try:
        if not candidate.exists():
            return None, "The reviewed file is missing."
        if not candidate.is_file():
            return None, "The reviewed path is not a file."
        if candidate.stat().st_size != record.size_bytes:
            return None, "The reviewed file size changed."
        stored_extension = getattr(record, "extension", candidate.suffix)
        if stored_extension.lower() not in SUPPORTED_EXTENSIONS:
            return None, "The stored extension is no longer supported."
        if candidate.suffix.lower() != stored_extension.lower():
            return None, "The reviewed file extension has changed."
        with candidate.open("rb") as file_stream:
            probe = file_stream.read(1)
        if record.size_bytes > 0 and not probe:
            return None, "The reviewed file could not be read locally."
    except (OSError, PermissionError):
        return None, "The reviewed file is not locally readable."

    return candidate, None


def prepare_manifest_upload(vdr_folder: str | Path) -> UploadPlan:
    """Read-only plan: candidate-wide blockers and local target issues are distinct."""
    try:
        root = Path(vdr_folder).expanduser().resolve()
        manifest = load_manifest(root)
        if not manifest_belongs_to_folder(manifest, root):
            raise UploadPreparationError(
                "The manifest does not belong to the selected VDR folder."
            )
        try:
            require_mutable(manifest)
        except ManifestPersistenceError as error:
            raise UploadPreparationError(str(error)) from error
        context = candidate_context(manifest, root)
        targets = enumerate_upload_targets(manifest, root)
    except (
        ManifestPersistenceError,
        InvalidVectorStoreIdError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        raise UploadPreparationError(
            "The candidate manifest, source root or vector-store association is invalid or immutable."
        ) from error
    rows, candidates, recovery, blockers = [], [], [], []
    for source in manifest.files:
        if source.classification_status == "preprocess" and (
            source.excel_preprocessing is None
            or source.excel_preprocessing.status not in {"completed", "excluded"}
        ):
            blockers.append(f"{source.relative_path}: Excel preparation is incomplete.")
        if source.classification_status in {"ignored", "unsupported", "error"}:
            classification = classify_manifest_record(source)
            rows.append(
                UploadPlanRow(
                    UploadTargetKey(source.relative_path),
                    source.relative_path,
                    source.extension,
                    source.size_bytes,
                    source.classification_status,
                    source.upload_status,
                    source.indexing_status,
                    classification.disposition,
                    False,
                    None,
                    classification.message,
                )
            )
    for target in targets:
        record = target.state_owner
        classification = classify_manifest_record(record)
        local_path, issue, preflight_ok = None, None, None
        if classification.eligible:
            try:
                local_path, issue = preflight_target(root, target)
            except UploadTargetIntegrityError as error:
                issue = str(error)
                blockers.append(f"{target.display_label}: {issue}")
            preflight_ok = issue is None
            candidates.append(
                UploadCandidate(
                    target.key, target.display_label, local_path, record.model_dump()
                )
            )
        elif classification.disposition == UploadDisposition.RECOVERY_ONLY:
            issue = classification.message
            recovery.append(
                UploadCandidate(
                    target.key, target.display_label, None, record.model_dump()
                )
            )
        elif classification.disposition == UploadDisposition.INCONSISTENT:
            issue = classification.message
            blockers.append(f"{target.display_label}: {issue}")
        rows.append(
            UploadPlanRow(
                target.key,
                target.display_label,
                ".md" if target.artifact else target.source.extension,
                record.size_bytes,
                "supported",
                record.upload_status,
                record.indexing_status,
                classification.disposition,
                classification.eligible,
                preflight_ok,
                issue,
            )
        )
    return UploadPlan(
        root,
        manifest.case_name,
        context.vector_store_id,
        context,
        tuple(rows),
        tuple(candidates),
        tuple(recovery),
        tuple(blockers),
    )


def mask_openai_file_id(file_id: str) -> str:
    normalized = file_id.strip()
    return (
        "*" * len(normalized)
        if len(normalized) <= 9
        else f"{normalized[:6]}...{normalized[-3:]}"
    )


def _emit(callback, event):
    if callback is not None:
        try:
            callback(event)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Upload progress callback failed", exc_info=True
            )


def _result(plan, files, outcome, message, recovery_file_id=None):
    diagnostics = []
    completed = retryable = new = pending = failed = 0
    ready = False
    try:
        manifest = load_manifest(plan.vdr_folder)
        if candidate_context(manifest, plan.vdr_folder) != plan.context:
            raise ManifestPersistenceError(
                "Candidate changed while assessing the result."
            )
        ready = assess_manifest_readiness(manifest, plan.vdr_folder).is_ready
        for target in enumerate_upload_targets(manifest, plan.vdr_folder):
            state = target.state_owner
            classification = classify_manifest_record(state).disposition
            completed += classification == UploadDisposition.COMPLETED
            retryable += classification == UploadDisposition.RETRY_CANDIDATE
            new += classification == UploadDisposition.INITIAL_CANDIDATE
            pending += (
                classification == UploadDisposition.RECOVERY_ONLY
                and state.indexing_status != "failed"
            )
            failed += (
                classification == UploadDisposition.RECOVERY_ONLY
                and state.indexing_status == "failed"
            )
    except Exception:
        outcome, message = (
            "stopped",
            "Manifest result reload or candidate verification failed; ingestion stopped.",
        )
    for item in files:
        if item.outcome == "completed":
            continue
        known_id = recovery_file_id if item is files[-1] else None
        try:
            state = target_for_key(
                load_manifest(plan.vdr_folder), plan.vdr_folder, item.key
            ).state_owner
            confirmed = state.model_dump(mode="json")
            known_id = known_id or state.openai_file_id
        except Exception:
            confirmed = {"state": "unavailable; preserve this diagnostic"}
        diagnostics.append(
            {
                "manifest": str(plan.context.manifest_path),
                "vector_store_id": plan.vector_store_id,
                "source_relative_path": item.key.source_relative_path,
                "artifact_id": item.key.artifact_id,
                "worksheet_label": item.display_label,
                "openai_file_id": known_id,
                "failed_checkpoint": item.message,
                "last_confirmed_persisted_state": confirmed,
            }
        )
    details = diagnostics[-1] if diagnostics else None
    if details:
        recovery_file_id = recovery_file_id or details["openai_file_id"]
        if len(diagnostics) > 1:
            details["other_targets"] = diagnostics[:-1]
    return UploadBatchResult(
        plan,
        tuple(files),
        outcome,
        message,
        sum(f.outcome == "completed" for f in files),
        completed,
        retryable,
        new,
        pending,
        failed,
        plan.count(UploadDisposition.COMPLETED),
        ready,
        recovery_file_id,
        details,
    )


def run_manifest_upload(
    vdr_folder: str | Path,
    *,
    client_factory: Callable[[], object],
    progress_callback: ProgressCallback | None = None,
    expected_context: CandidateContext | None = None,
    recover_only: bool = False,
    reattach_keys: tuple[UploadTargetKey, ...] = (),
    upload_file=upload_openai_file,
    attach_file=attach_file_and_poll,
    manifest_saver=save_manifest,
) -> UploadBatchResult:
    """Recover known IDs first, then attempt each eligible no-ID target once.

    reattach_keys is an explicit action request, never a persisted authorization.
    Fresh exact absence/resource/state checks are repeated during every such call.
    """
    plan = prepare_manifest_upload(vdr_folder)
    files = []
    if plan.blockers or (
        expected_context is not None and expected_context != plan.context
    ):
        return _result(
            plan,
            files,
            "stopped",
            "Candidate integrity or association checks blocked ingestion.",
        )
    if reattach_keys and (
        not recover_only
        or not set(reattach_keys) <= {c.key for c in plan.recovery_candidates}
    ):
        return _result(
            plan,
            files,
            "stopped",
            "Attach existing file requires exact current known-ID incomplete targets.",
        )
    known = tuple(
        c
        for c in plan.recovery_candidates
        if not reattach_keys or c.key in reattach_keys
    )
    work = known + (() if recover_only else plan.candidates)
    total = len(work)
    client = None
    streak = 0
    _emit(
        progress_callback, UploadProgressEvent("batch_started", total_candidates=total)
    )

    def finish(outcome="finished", message="Finished ingestion pass.", file_id=None):
        result = _result(plan, files, outcome, message, file_id)
        _emit(
            progress_callback,
            UploadProgressEvent(
                (
                    "batch_completed"
                    if result.pass_outcome == "finished"
                    else "batch_stopped"
                ),
                total_candidates=total,
                outcome=result.pass_outcome,
                sanitized_message=result.message,
            ),
        )
        return result

    for index, candidate in enumerate(work, 1):
        stage = "Target validation"
        returned_id = None
        record = None
        try:
            manifest = load_manifest(plan.vdr_folder)
            require_mutable(manifest)
            if candidate_context(manifest, plan.vdr_folder) != plan.context:
                raise ManifestPersistenceError("Candidate identity changed.")
            target = target_for_key(manifest, plan.vdr_folder, candidate.key)
            record = target.state_owner
            if record.model_dump() != candidate.expected_state:
                raise ManifestPersistenceError(
                    "Upload target state changed after planning."
                )
            confirmed_state = manifest.model_dump()

            def verify_current():
                current = load_manifest(plan.vdr_folder)
                require_mutable(current)
                if (
                    current.model_dump() != confirmed_state
                    or candidate_context(current, plan.vdr_folder) != plan.context
                ):
                    raise ManifestPersistenceError(
                        "Candidate or target changed between checkpoints."
                    )

            def checkpoint():
                nonlocal confirmed_state
                try:
                    verify_current()
                    manifest_saver(manifest, plan.vdr_folder)
                    persisted = load_manifest(plan.vdr_folder)
                    if (
                        persisted.model_dump() != manifest.model_dump()
                        or candidate_context(persisted, plan.vdr_folder) != plan.context
                    ):
                        raise ManifestPersistenceError(
                            "Manifest checkpoint readback did not match the exact saved state."
                        )
                    require_mutable(persisted)
                    confirmed_state = persisted.model_dump()
                except ManifestPersistenceError:
                    raise
                except Exception as error:
                    raise ManifestPersistenceError(
                        "Manifest checkpoint could not be saved and verified."
                    ) from error

            def event(kind, **kwargs):
                _emit(
                    progress_callback,
                    UploadProgressEvent(
                        kind,
                        candidate.key,
                        target.display_label,
                        index,
                        total,
                        record.upload_status,
                        record.indexing_status,
                        **kwargs,
                    ),
                )

            event("file_started")
            known_id = record.openai_file_id
            if known_id is None:
                stage = "Final local preflight"
                verified_path, local_error = preflight_target(plan.vdr_folder, target)
                if local_error:
                    record.upload_status = "failed"
                    record.last_error = local_error
                    checkpoint()
                    files.append(
                        BatchFileResult(
                            candidate.key,
                            target.display_label,
                            "no_id_retryable",
                            local_error,
                        )
                    )
                    event(
                        "file_failed",
                        outcome="no_id_retryable",
                        sanitized_message=local_error,
                    )
                    continue  # Local failures neither increment nor reset the infrastructure streak.
            stage = "Client setup"
            if client is None:
                try:
                    client = client_factory()
                except Exception as error:
                    if failure_scope(error) not in {"pause", "infrastructure"}:
                        raise
                    record.last_error = (
                        "Ingestion client access is unavailable; the pass is paused."
                    )
                    checkpoint()
                    files.append(
                        BatchFileResult(
                            candidate.key,
                            target.display_label,
                            "needs_recovery" if known_id else "no_id_retryable",
                            record.last_error,
                        )
                    )
                    return finish("paused", record.last_error)
            verify_current()
            if known_id is not None:
                stage = "Known-ID reconciliation"
                try:
                    inspection = inspect_known_file(
                        client, plan.vector_store_id, known_id, record.indexing_status
                    )
                except Exception as error:
                    remote_error = error
                else:
                    remote_error = None
                    if inspection.attachment_absent:
                        if (
                            inspection.requires_operator
                            and candidate.key not in reattach_keys
                        ):
                            record.last_error = "Exact attachment absent after two reads; Attach existing file is available after fresh revalidation."
                            checkpoint()
                            files.append(
                                BatchFileResult(
                                    candidate.key,
                                    target.display_label,
                                    "needs_recovery",
                                    record.last_error,
                                    True,
                                )
                            )
                            event(
                                "file_failed",
                                outcome="needs_recovery",
                                sanitized_message=record.last_error,
                            )
                            continue
                        remote = None  # First attachment, or the explicitly requested same-ID reattachment.
                    else:
                        remote = inspection.remote
            else:
                stage = "Uploading checkpoint"
                record.upload_attempts += 1
                record.upload_status = "uploading"
                record.indexing_status = "not_started"
                record.last_error = None
                checkpoint()
                event("manifest_marked_uploading")
                verify_current()
                stage = "File creation"
                try:
                    uploaded = upload_file(client, verified_path)
                    uploaded_id = getattr(uploaded, "id", None)
                    if not isinstance(uploaded_id, str) or not uploaded_id.strip():
                        raise RemoteProtocolError(
                            "File creation returned no usable ID."
                        )
                    returned_id = uploaded_id.strip()
                except DefinitePreRemoteUploadError:
                    record.upload_status = "failed"
                    record.last_error = "File could not be opened locally; retry in a later ingestion pass."
                    checkpoint()
                    files.append(
                        BatchFileResult(
                            candidate.key,
                            target.display_label,
                            "no_id_retryable",
                            record.last_error,
                        )
                    )
                    event(
                        "file_failed",
                        outcome="no_id_retryable",
                        sanitized_message=record.last_error,
                    )
                    continue
                except Exception as error:
                    remote_error = error
                else:
                    remote_error = None
                    stage = "File-ID checkpoint"
                    record.openai_file_id = returned_id
                    record.upload_status = "uploaded"
                    checkpoint()  # Mandatory durable ID readback BEFORE any attachment intent or POST.
                    known_id = returned_id
                    event("file_uploaded", masked_file_id=mask_openai_file_id(known_id))
                    event(
                        "file_id_persisted",
                        masked_file_id=mask_openai_file_id(known_id),
                    )
                    remote = None

            if remote_error is None and remote is None:
                stage = "Attachment intent checkpoint"
                record.indexing_status = "in_progress"
                record.last_error = None
                checkpoint()
                event(
                    "attachment_started", masked_file_id=mask_openai_file_id(known_id)
                )
                verify_current()
                stage = "Attachment / initial polling"
                try:
                    remote = attach_file(client, plan.vector_store_id, known_id)
                    validate_attachment(remote, plan.vector_store_id, known_id)
                except NotFoundError as error:
                    # Distinguish a missing attachment/File from an inaccessible store.
                    try:
                        verify_known_resources(client, plan.vector_store_id, known_id)
                    except Exception as resource_error:
                        remote_error = resource_error
                    else:
                        remote_error = error
                except Exception as error:
                    remote_error = error

            if remote_error is not None:
                scope = failure_scope(remote_error, stage=stage)
                if isinstance(remote_error, UnderlyingFileMissingError):
                    record.indexing_status = "failed"
                record.last_error = remote_failure_message(stage, remote_error)
                message = record.last_error
                stage = "Remote failure checkpoint"
                checkpoint()
                outcome = (
                    "needs_recovery" if record.openai_file_id else "no_id_retryable"
                )
                files.append(
                    BatchFileResult(
                        candidate.key, target.display_label, outcome, message
                    )
                )
                event("file_failed", outcome=outcome, sanitized_message=message)
                if scope in {"stop", "pause"}:
                    return finish("stopped" if scope == "stop" else "paused", message)
                if scope == "infrastructure":
                    streak += 1
                    if streak >= 3:
                        return finish(
                            "paused",
                            "Paused after 3 consecutive infrastructure-related target failures.",
                        )
                continue

            stage = "Indexing status checkpoint"
            status = remote.status
            record.upload_status = "uploaded"
            record.indexing_status = (
                status if status in {"completed", "in_progress"} else "failed"
            )
            record.last_error = (
                None
                if status in {"completed", "in_progress"}
                else f"Remote indexing ended with status {status}."
            )
            checkpoint()
            outcome = (
                "completed"
                if status == "completed"
                else "pending" if status == "in_progress" else "indexing_failed"
            )
            message = record.last_error or (
                "Upload and indexing completed."
                if status == "completed"
                else "Indexing is pending; recover it in a later pass."
            )
            files.append(
                BatchFileResult(candidate.key, target.display_label, outcome, message)
            )
            event(
                "indexing_completed" if status == "completed" else "file_failed",
                outcome=outcome,
                sanitized_message=message,
            )
            if status in {"completed", "in_progress"}:
                streak = 0
        except Exception as error:
            # All remote failures were handled above. Persistence, identity, local
            # integrity and unexpected application failures must stop immediately.
            import logging

            logging.getLogger(__name__).error(
                "Ingestion stopped at %s (%s)", stage, type(error).__name__
            )
            message = (
                f"{stage} failed; ingestion stopped before further remote mutation."
            )
            files.append(
                BatchFileResult(
                    candidate.key, candidate.display_label, "needs_recovery", message
                )
            )
            return finish(
                "stopped",
                message,
                returned_id or (record.openai_file_id if record else None),
            )
    return finish()
