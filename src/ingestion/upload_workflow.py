"""Reusable, conservative upload preparation and execution services."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol

from src.ingestion.case_readiness import manifest_belongs_to_folder
from src.ingestion.file_filter import SUPPORTED_EXTENSIONS
from src.ingestion.manifest import VDRFileRecord, VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    load_manifest,
    save_manifest,
)
from src.ingestion.uploader import attach_file_and_poll, upload_openai_file
from src.ingestion.vector_store_manager import (
    InvalidVectorStoreIdError,
    normalize_vector_store_id,
)


class UploadWorkflowError(Exception):
    """Base error for a safely reportable ingestion workflow failure."""


class UploadPreparationError(UploadWorkflowError):
    """Raised when a read-only upload plan cannot be constructed."""


class DefinitePreRemoteUploadError(UploadWorkflowError):
    """Signals that an upload failed before a remote file could exist.

    The normal OpenAI adapter deliberately does not manufacture this signal.
    It is available only to adapters that can prove the pre-remote boundary.
    """


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
    relative_path: str
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
            "Relative path": self.relative_path,
            "Extension": self.extension,
            "Size (bytes)": self.size_bytes,
            "Upload": self.upload_status,
            "Indexing": self.indexing_status,
            "Eligibility": self.disposition.value.replace("_", " "),
            "Preflight": (
                "passed"
                if self.preflight_ok is True
                else "blocked"
                if self.preflight_ok is False
                else "not applicable"
            ),
            "Reason": self.blocking_reason or "",
        }


@dataclass(frozen=True)
class UploadCandidate:
    relative_path: str
    local_path: Path


@dataclass(frozen=True)
class UploadPlan:
    vdr_folder: Path
    case_name: str
    vector_store_id: str
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
    relative_path: str | None = None
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
    relative_path: str
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
    safe_retry_paths: tuple[str, ...] = ()
    recovery_file_id: str | None = None

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

    if record.classification_status == "unsupported":
        return RecordClassification(
            UploadDisposition.UNSUPPORTED, False, "Unsupported file type."
        )
    if record.classification_status == "ignored":
        return RecordClassification(
            UploadDisposition.IGNORED, False, "Ignored during Phase 1."
        )
    if record.classification_status == "error":
        return RecordClassification(
            UploadDisposition.CLASSIFICATION_ERROR,
            False,
            "Phase 1 classification failed.",
        )

    has_id = _has_file_id(record)
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


def _path_sort_key(relative_path: str) -> tuple[str, str]:
    normalized = relative_path.replace("\\", "/")
    return normalized.casefold(), normalized


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
    safe_retry_paths: Iterable[str] = (),
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

    known_safe = set(safe_retry_paths)
    classified = [
        (
            record,
            classify_manifest_record(
                record,
                known_safe_retry=record.relative_path in known_safe,
            ),
        )
        for record in manifest.files
    ]
    classified.sort(key=lambda item: _path_sort_key(item[0].relative_path))

    rows: list[UploadPlanRow] = []
    candidates: list[UploadCandidate] = []
    blockers: list[str] = []
    path_keys = [
        record.relative_path.replace("\\", "/").casefold()
        for record, _classification in classified
    ]
    if len(path_keys) != len(set(path_keys)):
        blockers.append(
            "The manifest contains duplicate relative file paths."
        )
    for record, classification in classified:
        preflight_ok: bool | None = None
        blocking_reason: str | None = None
        if classification.eligible:
            local_path, blocking_reason = preflight_manifest_record(root, record)
            preflight_ok = blocking_reason is None
            if blocking_reason is not None:
                blockers.append(f"{record.relative_path}: {blocking_reason}")
            elif local_path is not None:
                candidates.append(
                    UploadCandidate(
                        relative_path=record.relative_path,
                        local_path=local_path,
                    )
                )
        elif classification.disposition in {
            UploadDisposition.UNCERTAIN,
            UploadDisposition.RECOVERY_ONLY,
            UploadDisposition.INCONSISTENT,
            UploadDisposition.CLASSIFICATION_ERROR,
        }:
            blocking_reason = classification.message

        rows.append(
            UploadPlanRow(
                relative_path=record.relative_path,
                extension=record.extension,
                size_bytes=record.size_bytes,
                classification_status=record.classification_status,
                upload_status=record.upload_status,
                indexing_status=record.indexing_status,
                disposition=classification.disposition,
                eligible=classification.eligible,
                preflight_ok=preflight_ok,
                blocking_reason=blocking_reason,
            )
        )

    return UploadPlan(
        vdr_folder=root,
        case_name=manifest.case_name,
        vector_store_id=vector_store_id,
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
        callback(event)


def _remote_failure_message(remote_result: object) -> str:
    status = getattr(remote_result, "status", None)
    if isinstance(status, str) and status:
        return f"Remote indexing ended with status {status}."[:500]
    return "Remote indexing did not report completion."


def _record_for_path(
    manifest: VDRManifest,
    relative_path: str,
) -> VDRFileRecord:
    matches = [
        record
        for record in manifest.files
        if record.relative_path == relative_path
    ]
    if len(matches) != 1:
        raise UploadWorkflowError(
            "The manifest contains an ambiguous relative file path."
        )
    return matches[0]


def _result(
    plan: UploadPlan,
    files: list[BatchFileResult],
    *,
    critically_stopped: bool,
    message: str,
    recovery_file_id: str | None = None,
) -> UploadBatchResult:
    return UploadBatchResult(
        plan=plan,
        files=tuple(files),
        completed_count=sum(item.outcome == "completed" for item in files),
        safely_retryable_count=sum(
            item.outcome == "safe_retry" for item in files
        ),
        recovery_count=sum(
            item.outcome in {"needs_recovery", "indexing_failed"}
            for item in files
        ),
        skipped_completed_count=plan.count(UploadDisposition.COMPLETED),
        critically_stopped=critically_stopped,
        message=message,
        safe_retry_paths=tuple(
            item.relative_path for item in files if item.outcome == "safe_retry"
        ),
        recovery_file_id=recovery_file_id,
    )


def run_manifest_upload(
    vdr_folder: str | Path,
    *,
    client_factory: ClientFactory,
    progress_callback: ProgressCallback | None = None,
    safe_retry_paths: Iterable[str] = (),
    upload_file: Callable[[object, Path], object] = upload_openai_file,
    attach_file: Callable[[object, str, str], object] = attach_file_and_poll,
    manifest_saver: Callable[[VDRManifest, str | Path], Path] = save_manifest,
) -> UploadBatchResult:
    """Revalidate and sequentially upload all safe manifest candidates."""

    retry_paths = tuple(safe_retry_paths)
    plan = prepare_manifest_upload(vdr_folder, safe_retry_paths=retry_paths)
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
        UploadProgressEvent(
            "batch_started", total_candidates=len(plan.candidates)
        ),
    )
    try:
        manifest = load_manifest(plan.vdr_folder)
        vector_store_id = normalize_vector_store_id(manifest.vector_store_id)
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

    file_results: list[BatchFileResult] = []
    total = len(plan.candidates)
    for index, candidate in enumerate(plan.candidates, start=1):
        record = _record_for_path(manifest, candidate.relative_path)
        classification = classify_manifest_record(
            record,
            known_safe_retry=record.relative_path in retry_paths,
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
                    relative_path=record.relative_path,
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
                relative_path=record.relative_path,
                current_index=index,
                total_candidates=total,
            ),
        )
        record.upload_attempts += 1
        record.upload_status = "uploading"
        record.indexing_status = "not_started"
        record.last_error = None
        try:
            manifest_saver(manifest, plan.vdr_folder)
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
                    relative_path=record.relative_path,
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
                relative_path=record.relative_path,
                current_index=index,
                total_candidates=total,
                upload_status=record.upload_status,
                indexing_status=record.indexing_status,
            ),
        )

        try:
            uploaded = upload_file(client, candidate.local_path)
        except DefinitePreRemoteUploadError:
            record.openai_file_id = None
            record.upload_status = "failed"
            record.indexing_status = "not_started"
            record.last_error = (
                "Upload did not start remotely; explicit same-session retry is safe."
            )
            try:
                manifest_saver(manifest, plan.vdr_folder)
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
                        relative_path=record.relative_path,
                        current_index=index,
                        total_candidates=total,
                        sanitized_message=result.message,
                    ),
                )
                return result
            item = BatchFileResult(
                record.relative_path,
                "safe_retry",
                "Upload did not start remotely; explicit retry is safe in this session.",
            )
            file_results.append(item)
            _emit(
                progress_callback,
                UploadProgressEvent(
                    "file_failed",
                    relative_path=record.relative_path,
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
                manifest_saver(manifest, plan.vdr_folder)
            except ManifestPersistenceError:
                message = "The uncertain upload state could not be checkpointed."
            else:
                message = record.last_error
            item = BatchFileResult(
                record.relative_path, "needs_recovery", message
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
                    relative_path=record.relative_path,
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
            record.last_error = (
                "OpenAI did not return a usable file ID; the upload outcome is uncertain."
            )
            try:
                manifest_saver(manifest, plan.vdr_folder)
            except ManifestPersistenceError:
                message = "The uncertain upload state could not be checkpointed."
            else:
                message = record.last_error
            item = BatchFileResult(
                record.relative_path, "needs_recovery", message
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
                    relative_path=record.relative_path,
                    current_index=index,
                    total_candidates=total,
                    outcome=item.outcome,
                    sanitized_message=message,
                ),
            )
            return result
        uploaded_id = uploaded_id.strip()
        _emit(
            progress_callback,
            UploadProgressEvent(
                "file_uploaded",
                relative_path=record.relative_path,
                current_index=index,
                total_candidates=total,
                masked_file_id=mask_openai_file_id(uploaded_id),
            ),
        )

        record.openai_file_id = uploaded_id
        record.upload_status = "uploaded"
        record.indexing_status = "not_started"
        record.last_error = None
        try:
            manifest_saver(manifest, plan.vdr_folder)
        except ManifestPersistenceError:
            item = BatchFileResult(
                record.relative_path,
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
                    relative_path=record.relative_path,
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
                "file_id_persisted",
                relative_path=record.relative_path,
                current_index=index,
                total_candidates=total,
                upload_status=record.upload_status,
                indexing_status=record.indexing_status,
                masked_file_id=mask_openai_file_id(uploaded_id),
            ),
        )

        record.indexing_status = "in_progress"
        try:
            manifest_saver(manifest, plan.vdr_folder)
        except ManifestPersistenceError:
            item = BatchFileResult(
                record.relative_path,
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
                    relative_path=record.relative_path,
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
                relative_path=record.relative_path,
                current_index=index,
                total_candidates=total,
                upload_status=record.upload_status,
                indexing_status=record.indexing_status,
                masked_file_id=mask_openai_file_id(uploaded_id),
            ),
        )

        try:
            remote_result = attach_file(
                client, vector_store_id, uploaded_id
            )
            remote_status = getattr(remote_result, "status", None)
        except Exception:
            record.upload_status = "uploaded"
            record.indexing_status = "in_progress"
            record.last_error = (
                "Attachment or polling was interrupted; remote status requires recovery."
            )
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
            manifest_saver(manifest, plan.vdr_folder)
        except ManifestPersistenceError:
            item = BatchFileResult(
                record.relative_path,
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
                    relative_path=record.relative_path,
                    current_index=index,
                    total_candidates=total,
                    outcome=item.outcome,
                    sanitized_message=item.message,
                ),
            )
            return result

        item = BatchFileResult(record.relative_path, outcome, message)
        file_results.append(item)
        _emit(
            progress_callback,
            UploadProgressEvent(
                "indexing_completed" if outcome == "completed" else "file_failed",
                relative_path=record.relative_path,
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
