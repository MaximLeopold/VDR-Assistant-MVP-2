"""Resolve OpenAI file citations to safe VDR display breadcrumbs."""

from pathlib import PurePosixPath, PureWindowsPath

from src.ingestion.manifest import VDRManifest
from src.schemas.citation import Citation
from src.schemas.evidence import (
    RetrievedSearchResult,
    SourceReference,
    ExcelSourceProvenance,
)

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
    if any(not part.strip() or part.strip() in {".", ".."} for part in parts):
        return None

    return "VDR → " + " → ".join(parts)


def _usable_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def resolve_citations(
    citations: list[Citation], manifest: VDRManifest | None
) -> list[SourceReference]:
    """Resolve exact IDs through an ambiguity-aware direct/worksheet multimap."""
    by_id = {}
    if manifest is not None:
        for record in manifest.files:
            if record.openai_file_id:
                by_id.setdefault(record.openai_file_id.strip(), []).append(
                    (record, None)
                )
            for artifact in record.derived_artifacts:
                if artifact.openai_file_id:
                    by_id.setdefault(artifact.openai_file_id.strip(), []).append(
                        (record, artifact)
                    )
    resolved = []
    for citation in citations:
        file_id = _usable_text(citation.file_id)
        source = SourceReference(file_id=file_id, display_name=UNKNOWN_SOURCE)
        matches = by_id.get(file_id, [])
        if len(matches) == 1:
            record, artifact = matches[0]
            breadcrumb = format_vdr_breadcrumb(record.relative_path)
            if breadcrumb is not None:
                source.display_name = breadcrumb
                if artifact is not None:
                    source.display_name += " \u2192 " + artifact.worksheet_name
                    source.excel_provenance = ExcelSourceProvenance(
                        original_relative_path=record.relative_path,
                        worksheet_name=artifact.worksheet_name,
                    )
        resolved.append(source)
    return resolved


def build_source_references(
    citations: list[Citation],
    resolved_sources: list[SourceReference],
    search_results: list[RetrievedSearchResult],
) -> list[SourceReference]:
    """Associate retrieved passages with cited sources by file ID only."""

    if len(citations) != len(resolved_sources):
        raise ValueError(
            "citations and resolved_sources must contain the same number of items"
        )

    candidates_by_file_id: dict[
        str,
        list[tuple[int, RetrievedSearchResult, str, str]],
    ] = {}

    for original_index, result in enumerate(search_results):
        file_id = _usable_text(result.file_id)
        raw_text = result.text
        deduplication_key = _usable_text(raw_text)
        if file_id is None or deduplication_key is None:
            continue

        candidates_by_file_id.setdefault(file_id, []).append(
            (original_index, result, raw_text, deduplication_key)
        )

    evidence_by_file_id: dict[str, list[str]] = {}

    for file_id, candidates in candidates_by_file_id.items():
        ranked_candidates = sorted(
            candidates,
            key=lambda item: (
                item[1].score is None,
                -item[1].score if item[1].score is not None else 0.0,
                item[0],
            ),
        )

        seen: set[str] = set()
        evidence = []
        for _, _, raw_text, deduplication_key in ranked_candidates:
            if deduplication_key in seen:
                continue

            seen.add(deduplication_key)
            evidence.append(raw_text)

        evidence_by_file_id[file_id] = evidence

    sources = []
    for citation, source in zip(citations, resolved_sources):
        file_id = _usable_text(citation.file_id)
        if source.file_id != file_id:
            raise ValueError("Resolved source identity does not match citation.")
        source.evidence = (
            list(evidence_by_file_id.get(file_id, [])) if file_id is not None else []
        )
        sources.append(source)
    return sources
