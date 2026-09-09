"""Best-effort selection of the manifest for the active vector store."""

from pathlib import Path

from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    load_manifest,
)
from src.ingestion.vector_store_manager import (
    InvalidVectorStoreIdError,
    normalize_vector_store_id,
)


def load_active_manifest(
    vdr_folder: str | Path | None,
    vector_store_id: str | None,
) -> VDRManifest | None:
    """Load a manifest only when it belongs to the selected vector store."""

    if vdr_folder is None:
        return None
    if isinstance(vdr_folder, str) and not vdr_folder.strip():
        return None

    try:
        selected_id = normalize_vector_store_id(vector_store_id)
        manifest = load_manifest(vdr_folder)
        manifest_id = normalize_vector_store_id(manifest.vector_store_id)
    except (ManifestPersistenceError, InvalidVectorStoreIdError, OSError):
        return None

    if manifest_id != selected_id or manifest.snapshot_state != "sealed":
        return None

    return manifest
