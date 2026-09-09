"""Upload new supported manifest files to the case vector store."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.manifest_persistence import save_manifest
from src.ingestion.uploader import attach_file_and_poll, upload_openai_file
from src.ingestion.upload_workflow import (
    UploadDisposition,
    UploadPreparationError,
    UploadProgressEvent,
    classify_manifest_record,
    preflight_manifest_record,
    prepare_manifest_upload,
    run_manifest_upload,
)
from src.retrieval.openai_file_search import get_openai_client


def normalize_vdr_folder_input(raw_path: str) -> str:
    """Normalize a normally pasted local folder path."""

    normalized = raw_path.strip()
    if len(normalized) >= 2 and normalized.startswith('"') and normalized.endswith('"'):
        normalized = normalized[1:-1].strip()
    return normalized


def _terminal_progress(event: UploadProgressEvent) -> None:
    if event.kind == "file_started":
        print(
            f"[{event.current_index}/{event.total_candidates}] "
            f"Processing {event.display_label}"
        )
    elif event.kind == "indexing_completed":
        print(f"Completed: {event.display_label}")
    elif event.kind == "file_failed":
        print(f"Needs attention: {event.display_label}: " f"{event.sanitized_message}")
    elif event.kind == "batch_stopped":
        print(
            event.sanitized_message or "Upload workflow stopped.",
            file=sys.stderr,
        )


def main() -> int:
    raw_path = input("Enter the selected local VDR folder path: ")
    vdr_folder = normalize_vdr_folder_input(raw_path)
    if not vdr_folder:
        print("A local VDR folder path is required.", file=sys.stderr)
        return 1

    try:
        plan = prepare_manifest_upload(vdr_folder)
    except UploadPreparationError as error:
        print(f"Could not prepare the case upload: {error}", file=sys.stderr)
        return 1

    if plan.blockers:
        print("Upload preflight failed:", file=sys.stderr)
        for blocker in plan.blockers:
            print(f"- {blocker}", file=sys.stderr)
        return 1

    if not plan.candidates:
        blocked_states = sum(
            plan.count(disposition)
            for disposition in (
                UploadDisposition.UNCERTAIN,
                UploadDisposition.RECOVERY_ONLY,
                UploadDisposition.INCONSISTENT,
                UploadDisposition.CLASSIFICATION_ERROR,
            )
        )
        if blocked_states:
            print(
                "No files are safely eligible. One or more records require "
                "terminal-assisted recovery.",
                file=sys.stderr,
            )
            return 1
        print("No supported manifest files require upload.")
        return 0

    print(f"Case name: {plan.case_name}")
    print(f"Files requiring upload: {len(plan.candidates)}")
    print("\nFILES TO UPLOAD")
    candidate_keys = {candidate.key for candidate in plan.candidates}
    for row in plan.rows:
        if row.key in candidate_keys:
            print(
                f"- {row.display_label} | {row.size_bytes} bytes | "
                f"{row.upload_status} | {row.indexing_status}"
            )

    confirmation = input("\nType UPLOAD to upload and index these files: ").strip()
    if confirmation != "UPLOAD":
        print("Upload aborted. No manifest or OpenAI resource was changed.")
        return 2

    result = run_manifest_upload(
        vdr_folder,
        client_factory=get_openai_client,
        progress_callback=_terminal_progress,
        upload_file=upload_openai_file,
        attach_file=attach_file_and_poll,
        manifest_saver=save_manifest,
    )
    if result.recovery_details:
        import json

        print(
            json.dumps(result.recovery_details, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
    if result.recovery_file_id is not None:
        print(
            "Preserve OpenAI File ID "
            f"{result.recovery_file_id} and inspect the candidate before "
            "rerunning uploads.",
            file=sys.stderr,
        )
    print(
        "Upload workflow finished: "
        f"{result.completed_count} completed, "
        f"{result.safely_retryable_count} safely retryable, "
        f"{result.recovery_count} requiring recovery."
    )
    return 0 if result.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
