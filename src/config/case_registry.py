"""Load and validate prepared VDR cases from a local JSON registry."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from src.ingestion.local_io import atomic_replace

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.ingestion.manifest import VDRManifest
from src.ingestion.case_readiness import assess_case_readiness
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    derive_manifest_paths,
    load_manifest,
    save_manifest,
)
from src.ingestion.vector_store_manager import (
    InvalidVectorStoreIdError,
    normalize_vector_store_id,
)


class CaseRegistryError(Exception):
    """Raised when the local case registry cannot be used safely."""


CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def normalize_case_id(raw_case_id: str) -> str:
    """Normalize and validate one non-confidential technical case ID."""

    normalized = raw_case_id.strip().lower() if isinstance(raw_case_id, str) else ""
    if not normalized:
        raise CaseRegistryError("A technical case ID is required.")
    if not CASE_ID_PATTERN.fullmatch(normalized):
        raise CaseRegistryError(
            "Use 1-64 lower-case letters, numbers, hyphens, or underscores; "
            "the first character must be a letter or number."
        )
    return normalized


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


@dataclass(frozen=True)
class CaseRegistrationResult:
    """Result of an atomic, readiness-gated registry registration."""

    case_id: str
    vdr_folder: Path
    status: str


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
        raise CaseRegistryError("The local case registry could not be read.") from error

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

    case_ids = [entry.case_id.casefold() for entry in registry.cases]
    duplicate_ids = {case_id for case_id in case_ids if case_ids.count(case_id) > 1}
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


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve()))


def _serialize_registry(registry: CaseRegistryDocument) -> str:
    data = registry.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _write_registry_temporary(path: Path, content: str | bytes) -> Path:
    binary = isinstance(content, bytes)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb" if binary else "w",
            encoding=None if binary else "utf-8",
            dir=path.parent,
            prefix=".case-registry-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        return temporary_path
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise CaseRegistryError(
            "The local case registry could not be written safely."
        ) from error


def _atomic_replace_registry(path: Path, registry: CaseRegistryDocument) -> None:
    try:
        original_content = path.read_bytes()
    except OSError as error:
        raise CaseRegistryError(
            "The local case registry could not be read before registration."
        ) from error

    temporary_path: Path | None = None
    try:
        temporary_path = _write_registry_temporary(
            path,
            _serialize_registry(registry),
        )
        atomic_replace(temporary_path, path)
        temporary_path = None
    except OSError as error:
        raise CaseRegistryError(
            "The local case registry could not be replaced safely."
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    try:
        reloaded = _read_registry(path)
        if reloaded.model_dump(mode="json") != registry.model_dump(mode="json"):
            raise CaseRegistryError("The updated case registry could not be verified.")
    except Exception as verification_error:
        recovery_path: Path | None = None
        try:
            recovery_path = _write_registry_temporary(path, original_content)
            atomic_replace(recovery_path, path)
            recovery_path = None
        except Exception as recovery_error:
            raise CaseRegistryError(
                "Registry verification failed and the original registry "
                "could not be restored automatically."
            ) from recovery_error
        finally:
            if recovery_path is not None:
                recovery_path.unlink(missing_ok=True)
        if isinstance(verification_error, CaseRegistryError):
            raise verification_error
        raise CaseRegistryError(
            "The updated case registry could not be verified."
        ) from verification_error


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

    if manifest.snapshot_state != "sealed":
        return PreparedCase(
            case_id=entry.case_id,
            vdr_folder=vdr_folder,
            manifest=manifest,
            error="The case snapshot is not sealed.",
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


def register_prepared_case(
    registry_path: str | Path | None,
    case_id: str,
    vdr_folder: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> CaseRegistrationResult:
    """Readiness-gate and atomically register one prepared local VDR case."""

    normalized_id = normalize_case_id(case_id)
    try:
        canonical_folder = Path(vdr_folder).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise CaseRegistryError("The selected VDR folder is invalid.") from error

    readiness = assess_case_readiness(canonical_folder)
    if not readiness.is_ready:
        detail = (
            readiness.blocking_reasons[0]
            if readiness.blocking_reasons
            else ("The case is not ready for registration.")
        )
        raise CaseRegistryError(f"The case is not ready for registration. {detail}")

    manifest = load_manifest(canonical_folder)
    if manifest.snapshot_state != "sealed":
        manifest.snapshot_state = "sealed"
        try:
            save_manifest(manifest, canonical_folder)
        except ManifestPersistenceError as error:
            raise CaseRegistryError(
                "The ready snapshot could not be sealed; retry registration."
            ) from error
    if load_manifest(canonical_folder).snapshot_state != "sealed":
        raise CaseRegistryError("Snapshot seal verification failed.")

    path = _resolve_registry_path(registry_path, base_dir=base_dir)
    if path.is_relative_to(canonical_folder) or path.parent.is_relative_to(
        canonical_folder
    ):
        raise CaseRegistryError("The registry must not be written inside the raw VDR.")
    registry = _read_registry(path)
    candidate_key = _path_key(canonical_folder)

    for entry in registry.cases:
        existing_folder = _resolve_vdr_folder(entry, path)
        same_id = entry.case_id.casefold() == normalized_id.casefold()
        same_folder = _path_key(existing_folder) == candidate_key
        if same_id and same_folder:
            return CaseRegistrationResult(
                case_id=normalized_id,
                vdr_folder=canonical_folder,
                status="already_registered",
            )
        if same_id:
            raise CaseRegistryError("This technical case ID is already registered.")
        if same_folder:
            raise CaseRegistryError("This VDR folder is already registered.")

    new_entry = CaseRegistryEntry(
        case_id=normalized_id,
        vdr_folder=canonical_folder.as_posix(),
    )
    try:
        updated = CaseRegistryDocument(cases=[*registry.cases, new_entry])
    except ValidationError as error:
        raise CaseRegistryError(
            "The updated local case registry failed validation."
        ) from error

    _atomic_replace_registry(path, updated)
    verified = _read_registry(path)
    matching = [
        entry
        for entry in verified.cases
        if entry.case_id.casefold() == normalized_id.casefold()
        and _path_key(_resolve_vdr_folder(entry, path)) == candidate_key
    ]
    if len(matching) != 1:
        raise CaseRegistryError(
            "The registered case could not be verified after persistence."
        )

    return CaseRegistrationResult(
        case_id=normalized_id,
        vdr_folder=canonical_folder,
        status="registered",
    )
