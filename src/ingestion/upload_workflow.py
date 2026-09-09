"""Reusable, conservative upload preparation and execution services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Literal, Protocol

from src.ingestion.case_readiness import manifest_belongs_to_folder
from src.ingestion.file_filter import SUPPORTED_EXTENSIONS
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    derive_manifest_paths,
    load_manifest,
    save_manifest,
)
from src.ingestion.uploader import (
    attach_file_and_poll,
    upload_openai_file,
    DefinitePreRemoteUploadError,
)
from src.ingestion.upload_targets import (
    UploadTargetKey,
    enumerate_upload_targets,
    target_for_key,
    preflight_target,
)
from src.ingestion.excel_preprocessing import require_mutable
from src.ingestion.vector_store_manager import (
    InvalidVectorStoreIdError,
    normalize_vector_store_id,
)


class UploadWorkflowError(Exception):
    """Base error for a safely reportable ingestion workflow failure."""


class UploadPreparationError(UploadWorkflowError):
    """Raised when a read-only upload plan cannot be constructed."""


class UploadDisposition(str, Enum):
    INITIAL_CANDIDATE = "initial_candidate"
    SAFE_RETRY = "safe_retry"
    COMPLETED = "completed"
    UNCERTAIN = "uncertain"
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

    def as_display_dict(self) -> dict[str, str | int]:
        return {
            "Source": self.display_label,
            "Extension": self.extension,
            "Size (bytes)": self.size_bytes,
            "Upload": self.upload_status,
            "Indexing": self.indexing_status,
            "Eligibility": self.disposition.value.replace("_", " "),
            "Preflight": (
                "passed"
                if self.preflight_ok is True
                else "blocked" if self.preflight_ok is False else "not applicable"
            ),
            "Reason": self.blocking_reason or "",
        }


@dataclass(frozen=True)
class UploadCandidate:
    key: UploadTargetKey
    display_label: str
    local_path: Path


@dataclass(frozen=True)
class RetryCandidateContext:
    vdr_folder: Path
    manifest_path: Path
    vector_store_id: str
    manifest_identity: str


@dataclass(frozen=True)
class SafeRetryAuthorization:
    """Session-only pre-remote proof bound to its originating snapshot."""

    context: RetryCandidateContext
    keys: tuple[UploadTargetKey, ...]


def retry_candidate_context(manifest: VDRManifest, root: Path) -> RetryCandidateContext:
    paths = derive_manifest_paths(root)
    # created_at and all frozen snapshot content identify this candidate.
    # Ordinary checkpoints change updated_at and target state, not this identity.
    identity = manifest.model_dump(mode="json")
    identity.pop("updated_at")
    identity.pop("snapshot_state")
    remote_fields = (
        "openai_file_id", "upload_status", "indexing_status",
        "upload_attempts", "last_error",
    )
    for source in identity["files"]:
        for owner in (source, *source["derived_artifacts"]):
            for field in remote_fields:
                owner.pop(field)
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest()
    return RetryCandidateContext(
        paths.vdr_folder,
        paths.manifest_path.resolve(),
        normalize_vector_store_id(manifest.vector_store_id),
        digest,
    )


def _authorized_retry_keys(authorization, context) -> tuple[UploadTargetKey, ...]:
    if isinstance(authorization, SafeRetryAuthorization) and authorization.context == context:
        return authorization.keys
    return ()


@dataclass(frozen=True)
class UploadPlan:
    vdr_folder: Path
    case_name: str
    vector_store_id: str
    retry_context: RetryCandidateContext
    rows: tuple[UploadPlanRow, ...]
    candidates: tuple[UploadCandidate, ...]
    blockers: tuple[str, ...]

    @property
    def can_execute(self) -> bool:
        return bool(self.candidates) and not self.blockers

    def count(self, disposition: UploadDisposition) -> int:
        return sum(row.disposition == disposition for row in self.rows)

    @property
    def supported_count(self) -> int:
        return sum(row.classification_status == "supported" for row in self.rows)


UploadEventKind = Literal[
    "batch_started",
    "file_started",
    "manifest_marked_uploading",
    "file_uploaded",
    "file_id_persisted",
    "attachment_started",
    "indexing_completed",
    "file_failed",
    "batch_stopped",
    "batch_completed",
]


@dataclass(frozen=True)
class UploadProgressEvent:
    kind: UploadEventKind
    key: UploadTargetKey | None = None
    display_label: str | None = None
    current_index: int = 0
    total_candidates: int = 0
    upload_status: str | None = None
    indexing_status: str | None = None
    outcome: str | None = None
    sanitized_message: str | None = None
    masked_file_id: str | None = None


BatchFileOutcome = Literal[
    "completed",
    "safe_retry",
    "needs_recovery",
    "indexing_failed",
]


@dataclass(frozen=True)
class BatchFileResult:
    key: UploadTargetKey
    display_label: str
    outcome: BatchFileOutcome
    message: str


@dataclass(frozen=True)
class UploadBatchResult:
    plan: UploadPlan
    files: tuple[BatchFileResult, ...]
    completed_count: int
    safely_retryable_count: int
    recovery_count: int
    skipped_completed_count: int
    critically_stopped: bool
    message: str
    safe_retry_authorization: SafeRetryAuthorization | None = None
    recovery_file_id: str | None = None
    recovery_details: dict | None = None

    @property
    def safe_retry_keys(self) -> tuple[UploadTargetKey, ...]:
        """Display/inspection only; keys alone cannot authorize a retry."""
        return self.safe_retry_authorization.keys if self.safe_retry_authorization else ()

    @property
    def succeeded(self) -> bool:
        blocking_dispositions = {
            UploadDisposition.UNCERTAIN,
            UploadDisposition.RECOVERY_ONLY,
            UploadDisposition.INCONSISTENT,
            UploadDisposition.CLASSIFICATION_ERROR,
        }
        return (
            not self.critically_stopped
            and self.safely_retryable_count == 0
            and self.recovery_count == 0
            and not any(
                row.disposition in blocking_dispositions for row in self.plan.rows
            )
        )


class ClientFactory(Protocol):
    def __call__(self) -> object: ...


ProgressCallback = Callable[[UploadProgressEvent], None]


def _has_file_id(record: VDRFileRecord) -> bool:
    return isinstance(record.openai_file_id, str) and bool(
        record.openai_file_id.strip()
    )


def classify_manifest_record(
    record: VDRFileRecord,
    *,
    known_safe_retry: bool = False,
) -> RecordClassification:
    """Classify one record without guessing about ambiguous remote outcomes."""

    if getattr(record, "classification_status", "supported") == "unsupported":
        return RecordClassification(
            UploadDisposition.UNSUPPORTED, False, "Unsupported file type."
        )
    if getattr(record, "classification_status", "supported") == "ignored":
        return RecordClassification(
            UploadDisposition.IGNORED, False, "Ignored during Phase 1."
        )
    if getattr(record, "classification_status", "supported") == "error":
        return RecordClassification(
            UploadDisposition.CLASSIFICATION_ERROR,
            False,
            "Phase 1 classification failed.",
        )

    if getattr(record, "classification_status", None) == "preprocess":
        return RecordClassification(
            UploadDisposition.RECOVERY_ONLY,
            False,
            "Workbook parents are never direct upload targets.",
        )
    has_id = _has_file_id(record)
    if record.openai_file_id is not None and not has_id:
        return RecordClassification(
            UploadDisposition.INCONSISTENT,
            False,
            "The persisted OpenAI file ID is unusable; do not re-upload.",
        )
    if (
        has_id
        and record.upload_status == "uploaded"
        and record.indexing_status == "completed"
    ):
        return RecordClassification(
            UploadDisposition.COMPLETED, False, "Upload and indexing completed."
        )
    if has_id:
        if record.upload_status != "uploaded":
            return RecordClassification(
                UploadDisposition.INCONSISTENT,
                False,
                "A file ID exists with an incompatible upload state.",
            )
        return RecordClassification(
            UploadDisposition.RECOVERY_ONLY,
            False,
            "A file ID exists but indexing is incomplete.",
        )
    if record.upload_status == "uploaded":
        return RecordClassification(
            UploadDisposition.INCONSISTENT,
            False,
            "The record is uploaded but has no persisted file ID.",
        )
    if record.upload_status == "uploading":
        return RecordClassification(
            UploadDisposition.UNCERTAIN,
            False,
            "The remote upload outcome is uncertain; do not re-upload.",
        )
    if (
        record.upload_status == "not_uploaded"
        and record.indexing_status == "not_started"
    ):
        return RecordClassification(
            UploadDisposition.INITIAL_CANDIDATE,
            True,
            "Ready for initial upload.",
        )
    if (
        known_safe_retry
        and record.upload_status == "failed"
        and record.indexing_status == "not_started"
    ):
        return RecordClassification(
            UploadDisposition.SAFE_RETRY,
            True,
            "A same-run result proves that no remote file was created.",
        )
    if record.upload_status == "failed":
        return RecordClassification(
            UploadDisposition.RECOVERY_ONLY,
            False,
            "A failed record without a file ID is not durably safe to retry.",
        )
    return RecordClassification(
        UploadDisposition.INCONSISTENT,
        False,
        "The upload and indexing states are incompatible.",
    )


def preflight_manifest_record(
    vdr_folder: str | Path,
    record: VDRFileRecord,
) -> tuple[Path | None, str | None]:
    """Validate one intended candidate and minimally probe readability."""

    root = Path(vdr_folder).expanduser().resolve()
    relative_path = Path(record.relative_path)
    if relative_path.is_absolute() or relative_path.drive:
        return None, "Absolute stored paths are not allowed."

    try:
        candidate = (root / relative_path).resolve()
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None, "The stored path escapes the selected VDR folder."

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


def prepare_manifest_upload(
    vdr_folder: str | Path,
    *,
    safe_retry_authorization: SafeRetryAuthorization | None = None,
) -> UploadPlan:
    """Build a deterministic, read-only upload plan from the persisted manifest."""

    try:
        root = Path(vdr_folder).expanduser().resolve()
        manifest = load_manifest(root)
    except (ManifestPersistenceError, OSError, RuntimeError, ValueError) as error:
        raise UploadPreparationError(
            "The selected case manifest is missing, inaccessible, or invalid."
        ) from error
    if not manifest_belongs_to_folder(manifest, root):
        raise UploadPreparationError(
            "The manifest does not belong to the selected VDR folder."
        )
    try:
        vector_store_id = normalize_vector_store_id(manifest.vector_store_id)
    except InvalidVectorStoreIdError as error:
        raise UploadPreparationError(
            "The manifest does not contain a vector-store ID."
        ) from error

    try:
        require_mutable(manifest)
    except ManifestPersistenceError as error:
        raise UploadPreparationError(str(error)) from error
    context = retry_candidate_context(manifest, root)
    known_safe = set(_authorized_retry_keys(safe_retry_authorization, context))
    rows, candidates, blockers = [], [], []
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
    for target in enumerate_upload_targets(manifest, root):
        record = target.state_owner
        classification = classify_manifest_record(
            record, known_safe_retry=target.key in known_safe
        )
        preflight_ok = None
        blocking_reason = None
        if classification.eligible:
            local_path, blocking_reason = preflight_target(root, target)
            preflight_ok = blocking_reason is None
            if blocking_reason:
                blockers.append(f"{target.display_label}: {blocking_reason}")
            else:
                candidates.append(
                    UploadCandidate(target.key, target.display_label, local_path)
                )
        elif classification.disposition in {
            UploadDisposition.UNCERTAIN,
            UploadDisposition.RECOVERY_ONLY,
            UploadDisposition.INCONSISTENT,
        }:
            blocking_reason = classification.message
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
                blocking_reason,
            )
        )

    return UploadPlan(
        vdr_folder=root,
        case_name=manifest.case_name,
        vector_store_id=vector_store_id,
        retry_context=context,
        rows=tuple(rows),
        candidates=tuple(candidates),
        blockers=tuple(blockers),
    )


def mask_openai_file_id(file_id: str) -> str:
    normalized = file_id.strip()
    if len(normalized) <= 9:
        return "*" * len(normalized)
    return f"{normalized[:6]}...{normalized[-3:]}"


def _emit(callback: ProgressCallback | None, event: UploadProgressEvent) -> None:
    if callback is not None:
        try:
            callback(event)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Upload progress callback failed", exc_info=True
            )


def _remote_failure_message(remote_result: object) -> str:
    status = getattr(remote_result, "status", None)
    if isinstance(status, str) and status:
        return f"Remote indexing ended with status {status}."[:500]
    return "Remote indexing did not report completion."


def _result(
    plan: UploadPlan,
    files: list[BatchFileResult],
    *,
    critically_stopped: bool,
    message: str,
    recovery_file_id: str | None = None,
) -> UploadBatchResult:
    diagnostics = []
    for item in files:
        if item.outcome not in {"needs_recovery", "indexing_failed"}:
            continue
        known_id = recovery_file_id if item is files[-1] else None
        try:
            persisted = target_for_key(
                load_manifest(plan.vdr_folder), plan.vdr_folder, item.key
            ).state_owner
            confirmed = persisted.model_dump(mode="json")
            known_id = known_id or persisted.openai_file_id
        except Exception:
            confirmed = {"state": "unavailable; preserve this diagnostic"}
        diagnostics.append(
            {
                "manifest": str(
                    plan.vdr_folder.parent / "VDR Assistant" / "manifest.json"
                ),
                "vector_store_id": plan.vector_store_id,
                "source_relative_path": item.key.source_relative_path,
                "artifact_id": item.key.artifact_id,
                "worksheet_label": item.display_label,
                "openai_file_id": known_id,
                "failed_checkpoint": item.message,
                "last_confirmed_persisted_state": confirmed,
            }
        )
    recovery_details = diagnostics[-1] if diagnostics else None
    if recovery_details:
        recovery_file_id = recovery_file_id or recovery_details["openai_file_id"]
        if len(diagnostics) > 1:
            recovery_details["other_targets"] = diagnostics[:-1]
    return UploadBatchResult(
        plan=plan,
        files=tuple(files),
        completed_count=sum(item.outcome == "completed" for item in files),
        safely_retryable_count=sum(item.outcome == "safe_retry" for item in files),
        recovery_count=sum(
            item.outcome in {"needs_recovery", "indexing_failed"} for item in files
        ),
        skipped_completed_count=plan.count(UploadDisposition.COMPLETED),
        critically_stopped=critically_stopped,
        message=message,
        safe_retry_authorization=(
            SafeRetryAuthorization(
                plan.retry_context,
                tuple(item.key for item in files if item.outcome == "safe_retry"),
            )
            if any(item.outcome == "safe_retry" for item in files) else None
        ),
        recovery_file_id=recovery_file_id,
        recovery_details=recovery_details,
    )


def run_manifest_upload(
    vdr_folder: str | Path,
    *,
    client_factory: ClientFactory,
    progress_callback: ProgressCallback | None = None,
    safe_retry_authorization: SafeRetryAuthorization | None = None,
    upload_file: Callable[[object, Path], object] = upload_openai_file,
    attach_file: Callable[[object, str, str], object] = attach_file_and_poll,
    manifest_saver: Callable[[VDRManifest, str | Path], Path] = save_manifest,
) -> UploadBatchResult:
    """Revalidate and sequentially upload all safe manifest candidates."""

    plan = prepare_manifest_upload(
        vdr_folder, safe_retry_authorization=safe_retry_authorization
    )
    if plan.blockers:
        return _result(
            plan,
            [],
            critically_stopped=True,
            message="Upload was blocked because local preflight failed.",
        )
    if not plan.candidates:
        return _result(
            plan,
            [],
            critically_stopped=False,
            message="No supported manifest files require upload.",
        )

    try:
        client = client_factory()
    except Exception:
        result = _result(
            plan,
            [],
            critically_stopped=True,
            message="The OpenAI client could not be created.",
        )
        _emit(
            progress_callback,
            UploadProgressEvent(
                "batch_stopped",
                total_candidates=len(plan.candidates),
                sanitized_message=result.message,
            ),
        )
        return result

    _emit(
        progress_callback,
        UploadProgressEvent("batch_started", total_candidates=len(plan.candidates)),
    )
    try:
        manifest = load_manifest(plan.vdr_folder)
        vector_store_id = normalize_vector_store_id(manifest.vector_store_id)
        current_context = retry_candidate_context(manifest, plan.vdr_folder)
    except (ManifestPersistenceError, InvalidVectorStoreIdError, OSError):
        result = _result(
            plan,
            [],
            critically_stopped=True,
            message="The manifest changed before upload could start.",
        )
        _emit(
            progress_callback,
            UploadProgressEvent(
                "batch_stopped",
                total_candidates=len(plan.candidates),
                sanitized_message=result.message,
            ),
        )
        return result
    if (
        not manifest_belongs_to_folder(manifest, plan.vdr_folder)
        or vector_store_id != plan.vector_store_id
        or current_context != plan.retry_context
    ):
        result = _result(
            plan,
            [],
            critically_stopped=True,
            message="The manifest association changed before upload could start.",
        )
        _emit(
            progress_callback,
            UploadProgressEvent(
                "batch_stopped",
                total_candidates=len(plan.candidates),
                sanitized_message=result.message,
            ),
        )
        return result

    retry_keys = _authorized_retry_keys(safe_retry_authorization, current_context)
    file_results: list[BatchFileResult] = []
    total = len(plan.candidates)
    for index, candidate in enumerate(plan.candidates, start=1):
        target = target_for_key(manifest, plan.vdr_folder, candidate.key)
        record = target.state_owner
        require_mutable(load_manifest(plan.vdr_folder))

        def checkpoint():
            try:
                manifest_saver(manifest, plan.vdr_folder)
                persisted = load_manifest(plan.vdr_folder)
                if (
                    persisted.vector_store_id != plan.vector_store_id
                    or retry_candidate_context(persisted, plan.vdr_folder) != plan.retry_context
                    or target_for_key(
                        persisted, plan.vdr_folder, candidate.key
                    ).state_owner.model_dump()
                    != record.model_dump()
                ):
                    raise ManifestPersistenceError(
                        "Upload target checkpoint verification failed."
                    )
            except ManifestPersistenceError:
                import logging

                logging.getLogger(__name__).exception(
                    "Upload checkpoint failed for %s", candidate.key
                )
                raise
            except Exception as error:
                raise ManifestPersistenceError(
                    "Upload target checkpoint failed."
                ) from error

        classification = classify_manifest_record(
            record,
            known_safe_retry=candidate.key in retry_keys,
        )
        if not classification.eligible:
            result = _result(
                plan,
                file_results,
                critically_stopped=True,
                message="The manifest state changed during upload.",
            )
            _emit(
                progress_callback,
                UploadProgressEvent(
                    "batch_stopped",
                    key=candidate.key,
                    display_label=target.display_label,
                    current_index=index,
                    total_candidates=total,
                    sanitized_message=result.message,
                ),
            )
            return result

        _emit(
            progress_callback,
            UploadProgressEvent(
                "file_started",
                key=candidate.key,
                display_label=target.display_label,
                current_index=index,
                total_candidates=total,
            ),
        )
        verified_path, preflight_error = preflight_target(plan.vdr_folder, target)
        if preflight_error:
            return _result(
                plan,
                file_results,
                critically_stopped=True,
                message=f"{target.display_label}: {preflight_error}",
            )
        record.upload_attempts += 1
        record.upload_status = "uploading"
        record.indexing_status = "not_started"
        record.last_error = None
        try:
            checkpoint()
        except ManifestPersistenceError:
            result = _result(
                plan,
                file_results,
                critically_stopped=True,
                message="The uploading checkpoint could not be saved.",
            )
            _emit(
                progress_callback,
                UploadProgressEvent(
                    "batch_stopped",
                    key=candidate.key,
                    display_label=target.display_label,
                    current_index=index,
                    total_candidates=total,
                    sanitized_message=result.message,
                ),
            )
            return result
        _emit(
            progress_callback,
            UploadProgressEvent(
                "manifest_marked_uploading",
                key=candidate.key,
                display_label=target.display_label,
                current_index=index,
                total_candidates=total,
                upload_status=record.upload_status,
                indexing_status=record.indexing_status,
            ),
        )

        try:
            uploaded = upload_file(client, verified_path)
        except DefinitePreRemoteUploadError:
            record.openai_file_id = None
            record.upload_status = "failed"
            record.indexing_status = "not_started"
            record.last_error = (
                "Upload did not start remotely; explicit same-session retry is safe."
            )
            try:
                checkpoint()
            except ManifestPersistenceError:
                result = _result(
                    plan,
                    file_results,
                    critically_stopped=True,
                    message="A safe upload failure could not be checkpointed.",
                )
                _emit(
                    progress_callback,
                    UploadProgressEvent(
                        "batch_stopped",
                        key=candidate.key,
                        display_label=target.display_label,
                        current_index=index,
                        total_candidates=total,
                        sanitized_message=result.message,
                    ),
                )
                return result
            item = BatchFileResult(
                candidate.key,
                target.display_label,
                "safe_retry",
                "Upload did not start remotely; explicit retry is safe in this session.",
            )
            file_results.append(item)
            _emit(
                progress_callback,
                UploadProgressEvent(
                    "file_failed",
                    key=candidate.key,
                    display_label=target.display_label,
                    current_index=index,
                    total_candidates=total,
                    outcome=item.outcome,
                    sanitized_message=item.message,
                ),
            )
            continue
        except Exception:
            record.openai_file_id = None
            record.upload_status = "uploading"
            record.indexing_status = "not_started"
            record.last_error = (
                "Upload outcome is uncertain; terminal-assisted recovery is required."
            )
            try:
                checkpoint()
            except ManifestPersistenceError:
                message = "The uncertain upload state could not be checkpointed."
            else:
                message = record.last_error
            item = BatchFileResult(
                candidate.key, target.display_label, "needs_recovery", message
            )
            file_results.append(item)
            result = _result(
                plan,
                file_results,
                critically_stopped=True,
                message=message,
            )
            _emit(
                progress_callback,
                UploadProgressEvent(
                    "batch_stopped",
                    key=candidate.key,
                    display_label=target.display_label,
                    current_index=index,
                    total_candidates=total,
                    outcome=item.outcome,
                    sanitized_message=message,
                ),
            )
            return result

        uploaded_id = getattr(uploaded, "id", None)
        if not isinstance(uploaded_id, str) or not uploaded_id.strip():
            record.openai_file_id = None
            record.upload_status = "uploading"
            record.indexing_status = "not_started"
            record.last_error = "OpenAI did not return a usable file ID; the upload outcome is uncertain."
            try:
                checkpoint()
            except ManifestPersistenceError:
                message = "The uncertain upload state could not be checkpointed."
            else:
                message = record.last_error
            item = BatchFileResult(
                candidate.key, target.display_label, "needs_recovery", message
            )
            file_results.append(item)
            result = _result(
                plan,
                file_results,
                critically_stopped=True,
                message=message,
            )
            _emit(
                progress_callback,
                UploadProgressEvent(
                    "batch_stopped",
                    key=candidate.key,
                    display_label=target.display_label,
                    current_index=index,
                    total_candidates=total,
                    outcome=item.outcome,
                    sanitized_message=message,
                ),
            )
            return result
        uploaded_id = uploaded_id.strip()
        record.openai_file_id = uploaded_id
        record.upload_status = "uploaded"
        record.indexing_status = "not_started"
        record.last_error = None
        try:
            checkpoint()
        except ManifestPersistenceError:
            item = BatchFileResult(
                candidate.key,
                target.display_label,
                "needs_recovery",
                "The returned file ID could not be persisted; do not re-upload.",
            )
            file_results.append(item)
            result = _result(
                plan,
                file_results,
                critically_stopped=True,
                message=item.message,
                recovery_file_id=uploaded_id,
            )
            _emit(
                progress_callback,
                UploadProgressEvent(
                    "batch_stopped",
                    key=candidate.key,
                    display_label=target.display_label,
                    current_index=index,
                    total_candidates=total,
                    outcome=item.outcome,
                    sanitized_message=item.message,
                    masked_file_id=mask_openai_file_id(uploaded_id),
                ),
            )
            return result
        _emit(
            progress_callback,
            UploadProgressEvent(
                "file_uploaded",
                key=candidate.key,
                display_label=target.display_label,
                current_index=index,
                total_candidates=total,
                masked_file_id=mask_openai_file_id(uploaded_id),
            ),
        )

        _emit(
            progress_callback,
            UploadProgressEvent(
                "file_id_persisted",
                key=candidate.key,
                display_label=target.display_label,
                current_index=index,
                total_candidates=total,
                upload_status=record.upload_status,
                indexing_status=record.indexing_status,
                masked_file_id=mask_openai_file_id(uploaded_id),
            ),
        )

        record.indexing_status = "in_progress"
        try:
            checkpoint()
        except ManifestPersistenceError:
            item = BatchFileResult(
                candidate.key,
                target.display_label,
                "needs_recovery",
                "The indexing checkpoint could not be saved; attachment did not start.",
            )
            file_results.append(item)
            result = _result(
                plan,
                file_results,
                critically_stopped=True,
                message=item.message,
            )
            _emit(
                progress_callback,
                UploadProgressEvent(
                    "batch_stopped",
                    key=candidate.key,
                    display_label=target.display_label,
                    current_index=index,
                    total_candidates=total,
                    outcome=item.outcome,
                    sanitized_message=item.message,
                ),
            )
            return result
        _emit(
            progress_callback,
            UploadProgressEvent(
                "attachment_started",
                key=candidate.key,
                display_label=target.display_label,
                current_index=index,
                total_candidates=total,
                upload_status=record.upload_status,
                indexing_status=record.indexing_status,
                masked_file_id=mask_openai_file_id(uploaded_id),
            ),
        )

        try:
            remote_result = attach_file(client, vector_store_id, uploaded_id)
            remote_status = getattr(remote_result, "status", None)
        except Exception:
            record.upload_status = "uploaded"
            record.indexing_status = "in_progress"
            record.last_error = "Attachment or polling was interrupted; remote status requires recovery."
            outcome: BatchFileOutcome = "needs_recovery"
            message = record.last_error
        else:
            if remote_status == "completed":
                record.upload_status = "uploaded"
                record.indexing_status = "completed"
                record.last_error = None
                outcome = "completed"
                message = "Upload and indexing completed."
            else:
                record.upload_status = "uploaded"
                record.indexing_status = "failed"
                record.last_error = _remote_failure_message(remote_result)
                outcome = "indexing_failed"
                message = record.last_error

        try:
            checkpoint()
        except ManifestPersistenceError:
            item = BatchFileResult(
                candidate.key,
                target.display_label,
                "needs_recovery",
                "The terminal indexing state could not be saved.",
            )
            file_results.append(item)
            result = _result(
                plan,
                file_results,
                critically_stopped=True,
                message=item.message,
            )
            _emit(
                progress_callback,
                UploadProgressEvent(
                    "batch_stopped",
                    key=candidate.key,
                    display_label=target.display_label,
                    current_index=index,
                    total_candidates=total,
                    outcome=item.outcome,
                    sanitized_message=item.message,
                ),
            )
            return result

        item = BatchFileResult(candidate.key, target.display_label, outcome, message)
        file_results.append(item)
        _emit(
            progress_callback,
            UploadProgressEvent(
                "indexing_completed" if outcome == "completed" else "file_failed",
                key=candidate.key,
                display_label=target.display_label,
                current_index=index,
                total_candidates=total,
                upload_status=record.upload_status,
                indexing_status=record.indexing_status,
                outcome=outcome,
                sanitized_message=message,
                masked_file_id=mask_openai_file_id(uploaded_id),
            ),
        )

    message = "Upload workflow completed."
    result = _result(
        plan,
        file_results,
        critically_stopped=False,
        message=message,
    )
    _emit(
        progress_callback,
        UploadProgressEvent(
            "batch_completed",
            total_candidates=total,
            outcome="completed" if result.succeeded else "completed_with_failures",
            sanitized_message=message,
        ),
    )
    return result
