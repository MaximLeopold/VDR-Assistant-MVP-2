"""Shared containment checks for read-only sources and managed outputs."""

from pathlib import Path, PureWindowsPath


def safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    windows = PureWindowsPath(value)
    if (
        not normalized
        or windows.drive
        or windows.root
        or any(part in {"", ".", ".."} or ":" in part for part in normalized.split("/"))
    ):
        raise ValueError(f"Unsafe relative path: {value!r}")
    return normalized


def resolve_relative(root: Path, value: str) -> Path:
    root = root.resolve()
    candidate = (root / safe_relative_path(value)).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Relative path escapes its root: {value!r}")
    return candidate


def validate_disjoint_roots(raw: Path, managed: Path) -> None:
    raw, managed = raw.resolve(), managed.resolve()
    if raw.is_relative_to(managed) or managed.is_relative_to(raw):
        raise ValueError("Raw VDR and VDR Assistant roots must be disjoint.")


def managed_path(raw: Path, managed: Path, relative: str) -> Path:
    validate_disjoint_roots(raw, managed)
    candidate = resolve_relative(managed, relative)
    if candidate.is_relative_to(raw.resolve()):
        raise ValueError("Application output must not resolve inside the raw VDR.")
    return candidate
