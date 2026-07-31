"""Load and validate prepared VDR cases from a local JSON registry."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    derive_manifest_paths,
    load_manifest,
)
from src.ingestion.vector_store_manager import (
    InvalidVectorStoreIdError,
    normalize_vector_store_id,
)


class CaseRegistryError(Exception):
    """Raised when the local case registry cannot be used safely."""


class CaseRegistryEntry(BaseModel):
    """Minimal registry-owned locator for one prepared case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    vdr_folder: str

    @field_validator("case_id", "vdr_folder")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class CaseRegistryDocument(BaseModel):
    """Validated top-level registry structure."""

    model_config = ConfigDict(extra="forbid")

    cases: list[CaseRegistryEntry] = Field(min_length=1)


@dataclass(frozen=True)
class PreparedCase:
    """One registry case with manifest-owned runtime metadata."""

    case_id: str
    vdr_folder: Path
    case_name: str | None = None
    manifest: VDRManifest | None = None
    vector_store_id: str | None = None
    error: str | None = None

    @property
    def is_ready(self) -> bool:
        return (
            self.error is None
            and self.case_name is not None
            and self.manifest is not None
            and self.vector_store_id is not None
        )

    @property
    def display_name(self) -> str:
        return self.case_name or self.case_id


def _resolve_registry_path(
    registry_path: str | Path | None,
    *,
    base_dir: str | Path | None = None,
) -> Path:
    if registry_path is None:
        raise CaseRegistryError("The local case registry is not configured.")
    if isinstance(registry_path, str) and not registry_path.strip():
        raise CaseRegistryError("The local case registry is not configured.")

    path = Path(registry_path).expanduser()
    if not path.is_absolute():
        root = Path(base_dir).expanduser() if base_dir is not None else Path.cwd()
        path = root / path
    return path.resolve()


def _read_registry(path: Path) -> CaseRegistryDocument:
    if not path.is_file():
        raise CaseRegistryError(
            "The local case registry could not be found. Configure "
            "CASE_REGISTRY_PATH with an available JSON registry."
        )

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CaseRegistryError(
            "The local case registry could not be read."
        ) from error

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise CaseRegistryError(
            "The local case registry contains malformed JSON."
        ) from error

    try:
        registry = CaseRegistryDocument.model_validate(data)
    except ValidationError as error:
        raise CaseRegistryError(
            "The local case registry does not match the required schema. "
            "Each case must contain only a nonblank case_id and vdr_folder."
        ) from error

    case_ids = [entry.case_id for entry in registry.cases]
    duplicate_ids = {
        case_id for case_id in case_ids if case_ids.count(case_id) > 1
    }
    if duplicate_ids:
        raise CaseRegistryError(
            "The local case registry contains duplicate case_id values."
        )

    return registry


def _resolve_vdr_folder(entry: CaseRegistryEntry, registry_path: Path) -> Path:
    vdr_folder = Path(entry.vdr_folder).expanduser()
    if not vdr_folder.is_absolute():
        vdr_folder = registry_path.parent / vdr_folder
    return vdr_folder.resolve()


def _prepare_case(
    entry: CaseRegistryEntry,
    registry_path: Path,
) -> PreparedCase:
    vdr_folder = _resolve_vdr_folder(entry, registry_path)

    if not vdr_folder.is_dir():
        return PreparedCase(
            case_id=entry.case_id,
            vdr_folder=vdr_folder,
            error="The configured VDR folder is unavailable.",
        )

    try:
        derive_manifest_paths(vdr_folder)
        manifest = load_manifest(vdr_folder)
    except ManifestPersistenceError:
        return PreparedCase(
            case_id=entry.case_id,
            vdr_folder=vdr_folder,
            error="The case manifest is missing, inaccessible, or invalid.",
        )
    except OSError:
        return PreparedCase(
            case_id=entry.case_id,
            vdr_folder=vdr_folder,
            error="The case manifest could not be accessed.",
        )

    case_name = manifest.case_name.strip()
    if not case_name:
        return PreparedCase(
            case_id=entry.case_id,
            vdr_folder=vdr_folder,
            manifest=manifest,
            error="The case manifest does not contain a usable case name.",
        )

    try:
        vector_store_id = normalize_vector_store_id(manifest.vector_store_id)
    except InvalidVectorStoreIdError:
        return PreparedCase(
            case_id=entry.case_id,
            vdr_folder=vdr_folder,
            case_name=case_name,
            manifest=manifest,
            error="The case manifest does not contain a vector-store ID.",
        )

    return PreparedCase(
        case_id=entry.case_id,
        vdr_folder=vdr_folder,
        case_name=case_name,
        manifest=manifest,
        vector_store_id=vector_store_id,
    )


def load_case_registry(
    registry_path: str | Path | None,
    *,
    base_dir: str | Path | None = None,
) -> list[PreparedCase]:
    """Load registry entries and compute readiness for every prepared case."""

    path = _resolve_registry_path(registry_path, base_dir=base_dir)
    registry = _read_registry(path)
    return [_prepare_case(entry, path) for entry in registry.cases]
