"""Case-level OpenAI vector-store lifecycle orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openai import OpenAI

from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    load_manifest,
    save_manifest,
)
from src.ingestion.vector_store_manager import (
    create_vector_store,
    normalize_vector_store_id,
    retrieve_vector_store,
)


class CaseVectorStoreError(Exception):
    """Base error for case-level vector-store lifecycle operations."""


class CaseVectorStoreConflictError(CaseVectorStoreError):
    """Raised when a supplied ID conflicts with the manifest ID."""


class NoCaseVectorStoreError(CaseVectorStoreError):
    """Raised when a case has no ID and creation was not permitted."""


class CaseVectorStorePersistenceError(CaseVectorStoreError):
    """Raised when an adopted vector-store ID cannot be persisted."""

    def __init__(
        self,
        vector_store_id: str,
        original_save_error: Exception,
    ) -> None:
        self.vector_store_id = vector_store_id
        self.original_save_error = original_save_error
        super().__init__(
            "The vector store was validated, but its ID could not be saved "
            "to the case manifest. Adoption did not complete."
        )


class VectorStoreCreatedButNotPersistedError(CaseVectorStoreError):
    """Recoverable failure after remote creation but before local persistence."""

    def __init__(
        self,
        *,
        manifest: VDRManifest,
        vector_store_id: str,
        vector_store_name: str | None,
        original_save_error: Exception,
    ) -> None:
        self.manifest = manifest
        self.vector_store_id = vector_store_id
        self.vector_store_name = vector_store_name
        self.original_save_error = original_save_error
        super().__init__(
            "OpenAI created the vector store, but its ID could not be saved "
            "to the case manifest. Preserve the newly created vector-store "
            "ID and explicitly adopt it on a later run. The remote vector "
            "store was not deleted and creation was not retried."
        )


@dataclass(frozen=True)
class CaseVectorStoreResult:
    """Result of validating, adopting, or creating a case vector store."""

    manifest: VDRManifest
    vector_store_id: str
    action: Literal["reused", "adopted", "created"]
    remote_name: str | None


def _remote_name(vector_store: object) -> str | None:
    name = getattr(vector_store, "name", None)
    return name if isinstance(name, str) and name else None


def _normalized_manifest_id(manifest: VDRManifest) -> str | None:
    if manifest.vector_store_id is None:
        return None
    return normalize_vector_store_id(manifest.vector_store_id)


def _reject_conflict(
    manifest_id: str | None,
    candidate_id: str | None,
) -> None:
    if (
        manifest_id is not None
        and candidate_id is not None
        and manifest_id != candidate_id
    ):
        raise CaseVectorStoreConflictError(
            "The supplied vector-store ID differs from the ID already stored "
            "in the case manifest. The manifest was not changed."
        )


def adopt_case_vector_store(
    client: OpenAI,
    vdr_folder: str | Path,
    vector_store_id: str,
) -> CaseVectorStoreResult:
    """Explicitly validate and adopt an existing vector store for a case."""

    manifest = load_manifest(vdr_folder)
    candidate_id = normalize_vector_store_id(vector_store_id)
    manifest_id = _normalized_manifest_id(manifest)
    _reject_conflict(manifest_id, candidate_id)

    remote = retrieve_vector_store(client, candidate_id)

    if manifest_id == candidate_id:
        return CaseVectorStoreResult(
            manifest=manifest,
            vector_store_id=candidate_id,
            action="reused",
            remote_name=_remote_name(remote),
        )

    manifest.vector_store_id = candidate_id
    try:
        save_manifest(manifest, vdr_folder)
    except ManifestPersistenceError as error:
        raise CaseVectorStorePersistenceError(
            vector_store_id=candidate_id,
            original_save_error=error,
        ) from error

    return CaseVectorStoreResult(
        manifest=manifest,
        vector_store_id=candidate_id,
        action="adopted",
        remote_name=_remote_name(remote),
    )


def ensure_case_vector_store(
    client: OpenAI,
    vdr_folder: str | Path,
    *,
    adoption_candidate: str | None = None,
    allow_create: bool = False,
) -> CaseVectorStoreResult:
    """Ensure a case reuses, adopts, or explicitly creates one vector store."""

    manifest = load_manifest(vdr_folder)
    manifest_id = _normalized_manifest_id(manifest)
    candidate_id = (
        normalize_vector_store_id(adoption_candidate)
        if adoption_candidate is not None
        else None
    )
    _reject_conflict(manifest_id, candidate_id)

    if manifest_id is not None:
        remote = retrieve_vector_store(client, manifest_id)
        return CaseVectorStoreResult(
            manifest=manifest,
            vector_store_id=manifest_id,
            action="reused",
            remote_name=_remote_name(remote),
        )

    if candidate_id is not None:
        remote = retrieve_vector_store(client, candidate_id)
        manifest.vector_store_id = candidate_id
        try:
            save_manifest(manifest, vdr_folder)
        except ManifestPersistenceError as error:
            raise CaseVectorStorePersistenceError(
                vector_store_id=candidate_id,
                original_save_error=error,
            ) from error
        return CaseVectorStoreResult(
            manifest=manifest,
            vector_store_id=candidate_id,
            action="adopted",
            remote_name=_remote_name(remote),
        )

    if not allow_create:
        raise NoCaseVectorStoreError(
            "No vector store is configured for this case, and creation was "
            "not permitted."
        )

    remote = create_vector_store(client, manifest.case_name)
    created_id = normalize_vector_store_id(getattr(remote, "id", None))
    created_name = _remote_name(remote)
    manifest.vector_store_id = created_id

    try:
        save_manifest(manifest, vdr_folder)
    except ManifestPersistenceError as error:
        raise VectorStoreCreatedButNotPersistedError(
            manifest=manifest,
            vector_store_id=created_id,
            vector_store_name=created_name,
            original_save_error=error,
        ) from error

    return CaseVectorStoreResult(
        manifest=manifest,
        vector_store_id=created_id,
        action="created",
        remote_name=created_name,
    )
