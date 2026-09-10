"""Small, per-pass failure classification; never an upload eligibility authority."""

from openai import APIConnectionError, APIStatusError, APIResponseValidationError
from src.ingestion.vector_store_manager import (
    VectorStoreAuthenticationError,
    VectorStorePermissionError,
    VectorStoreRateLimitError,
    VectorStoreNotAccessibleError,
    VectorStoreIdMismatchError,
    OpenAIFileIdMismatchError,
)


class RemoteIdentityError(ValueError):
    """The response identifies a different resource than the exact requested ID."""


class RemoteProtocolError(Exception):
    """A remote response lacks a usable ID or recognized status."""


class UnderlyingFileMissingError(Exception):
    """The persisted File is missing. Its ID must never be replaced by upload."""


def failure_scope(error: Exception, *, stage: str | None = None) -> str:
    """Return stop, pause, infrastructure, or target using structured causes."""
    if isinstance(
        error,
        (RemoteIdentityError, VectorStoreIdMismatchError, OpenAIFileIdMismatchError),
    ):
        return "stop"
    if isinstance(
        error,
        (
            VectorStoreAuthenticationError,
            VectorStorePermissionError,
            VectorStoreRateLimitError,
            VectorStoreNotAccessibleError,
        ),
    ):
        return "pause"
    if isinstance(error, UnderlyingFileMissingError):
        return "target"
    if isinstance(error, APIStatusError):
        if stage == "File creation" and error.status_code == 404:
            return "pause"
        if getattr(error, "code", None) in {
            "insufficient_quota",
            "billing_hard_limit_reached",
            "billing_not_active",
        } or getattr(error, "param", None) in {"purpose", "vector_store_id"}:
            return "pause"
        if error.status_code in {401, 403, 429}:
            return "pause"
        if error.status_code >= 500 or error.status_code in {408, 409}:
            return "infrastructure"
        if error.status_code in {400, 404, 413, 422}:
            return "target"
        return "pause"
    if isinstance(
        error,
        (
            APIConnectionError,
            APIResponseValidationError,
            TimeoutError,
            ConnectionError,
            RemoteProtocolError,
        ),
    ):
        return "infrastructure"
    if error.__cause__ is not None and isinstance(error.__cause__, Exception):
        return failure_scope(error.__cause__, stage=stage)
    # An unrecognized Python exception is an application failure, not a bad file.
    return "stop"


def remote_failure_message(stage: str, error: Exception) -> str:
    """Keep credentials and raw response bodies out of manifests and UI."""
    scope = failure_scope(error, stage=stage)
    detail = {
        "stop": "Application or resource identity check failed; ingestion stopped.",
        "pause": "Ingestion service access is unavailable; the pass is paused.",
        "infrastructure": "Remote request failed after its configured SDK retries.",
        "target": "The remote operation failed for this target.",
    }[scope]
    if isinstance(error, UnderlyingFileMissingError):
        detail = (
            "The persisted underlying File is missing; preserve its ID and investigate."
        )
    return f"{stage}: {detail}"
