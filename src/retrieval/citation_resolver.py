"""Resolve OpenAI file citations to safe VDR display breadcrumbs."""

from pathlib import PurePosixPath, PureWindowsPath

from src.ingestion.manifest import VDRManifest
from src.schemas.citation import Citation


UNKNOWN_SOURCE = "Unknown source"


def format_vdr_breadcrumb(relative_path: str | None) -> str | None:
    """Format a safe relative VDR path without accessing the filesystem."""

    if not isinstance(relative_path, str):
        return None

    candidate = relative_path.strip()
    if not candidate:
        return None

    windows_path = PureWindowsPath(candidate)
    normalized = candidate.replace("\\", "/")
    posix_path = PurePosixPath(normalized)

    if windows_path.drive or windows_path.root or posix_path.is_absolute():
        return None

    parts = normalized.split("/")
    if any(
        not part.strip() or part.strip() in {".", ".."}
        for part in parts
    ):
        return None

    return "VDR → " + " → ".join(parts)


def _usable_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _fallback_label(citation: Citation) -> str:
    return _usable_text(citation.filename) or UNKNOWN_SOURCE


def resolve_citations(
    citations: list[Citation],
    manifest: VDRManifest | None,
) -> list[str]:
    """Resolve citations by OpenAI file ID while preserving their order."""

    records_by_file_id: dict[str, list[object]] = {}
    if manifest is not None:
        for record in manifest.files:
            file_id = _usable_text(record.openai_file_id)
            if file_id is not None:
                records_by_file_id.setdefault(file_id, []).append(record)

    resolved = []
    for citation in citations:
        file_id = _usable_text(citation.file_id)
        matches = records_by_file_id.get(file_id, []) if file_id else []

        if len(matches) == 1:
            breadcrumb = format_vdr_breadcrumb(matches[0].relative_path)
            if breadcrumb is not None:
                resolved.append(breadcrumb)
                continue

        resolved.append(_fallback_label(citation))

    return resolved
