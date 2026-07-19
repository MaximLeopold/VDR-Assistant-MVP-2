"""Explicitly adopt the configured vector store into one case manifest.

This script never creates a vector store or changes remote content.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import VECTOR_STORE_ID
from src.ingestion.case_vector_store import adopt_case_vector_store
from src.ingestion.manifest_persistence import load_manifest
from src.retrieval.openai_file_search import get_openai_client


def redact_vector_store_id(vector_store_id: str) -> str:
    """Redact an ID while retaining enough shape for operator recognition."""

    value = vector_store_id.strip()
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _selected_vdr_folder(argument: str | None) -> Path:
    supplied = argument or input("Selected VDR folder: ").strip()
    if not supplied:
        raise ValueError("A selected VDR folder is required.")
    return Path(supplied).expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Adopt the configured OpenAI vector store into a case."
    )
    parser.add_argument(
        "vdr_folder",
        nargs="?",
        help="Path to the selected VDR/data-room folder.",
    )
    args = parser.parse_args(argv)

    try:
        vdr_folder = _selected_vdr_folder(args.vdr_folder)
        manifest = load_manifest(vdr_folder)
    except Exception as error:
        print(f"Could not load the case manifest: {error}", file=sys.stderr)
        return 1

    candidate = (VECTOR_STORE_ID or "").strip()
    if not candidate:
        print(
            "VECTOR_STORE_ID is not configured; there is no adoption "
            "candidate.",
            file=sys.stderr,
        )
        return 1

    print(f"Case name: {manifest.case_name}")
    print(f"Selected VDR path: {vdr_folder.resolve()}")
    print(f"Proposed vector-store ID: {redact_vector_store_id(candidate)}")
    confirmation = input(
        "Type ADOPT to validate and persist this association: "
    ).strip()

    if confirmation != "ADOPT":
        print("Adoption aborted. No OpenAI request or manifest save was made.")
        return 2

    try:
        result = adopt_case_vector_store(
            get_openai_client(),
            vdr_folder,
            candidate,
        )
    except Exception as error:
        # Report remote validation, conflict, and persistence errors uniformly.
        print(f"Adoption failed: {error}", file=sys.stderr)
        return 1

    print(f"Result: {result.action}")
    if result.remote_name:
        print(f"Remote vector-store name: {result.remote_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
