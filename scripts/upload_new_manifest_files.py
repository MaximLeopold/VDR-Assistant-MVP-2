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

    if not plan.can_execute:
        from src.ingestion.case_readiness import assess_case_readiness

        print("No eligible ingestion or recovery work remains.")
        return 0 if assess_case_readiness(vdr_folder).is_ready else 1

    print(f"Case name: {plan.case_name}")
    print(f"Files requiring upload: {len(plan.candidates)}")
    print(f"Known files to recover: {len(plan.recovery_candidates)}")
    print("One operator may ingest this candidate at a time.")
    for row in plan.rows:
        print(
            f"- {row.display_label} | {row.disposition.value} | {row.blocking_reason or ''}"
        )
    for number, candidate in enumerate(plan.recovery_candidates, 1):
        print(f"Known target {number}: {candidate.display_label}")
    confirmation = input(
        "Type UPLOAD to continue ingestion, RECOVER to refresh / recover known files, "
        "or ATTACH <known target number> to attach an existing file after fresh absence checks: "
    ).strip()
    recover_only = confirmation == "RECOVER"
    reattach_keys = ()
    if confirmation.startswith("ATTACH "):
        try:
            number = int(confirmation.split()[1])
            if number < 1:
                raise ValueError()
            reattach_keys = (plan.recovery_candidates[number - 1].key,)
        except (ValueError, IndexError):
            print("Invalid known target number. No resources changed.", file=sys.stderr)
            return 2
        recover_only = True
    elif confirmation not in {"UPLOAD", "RECOVER"}:
        print("Upload aborted. No manifest or OpenAI resource was changed.")
        return 2

    result = run_manifest_upload(
        vdr_folder,
        client_factory=get_openai_client,
        progress_callback=_terminal_progress,
        upload_file=upload_openai_file,
        attach_file=attach_file_and_poll,
        manifest_saver=save_manifest,
        expected_context=plan.context,
        recover_only=recover_only,
        reattach_keys=reattach_keys,
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
    print(f"Ingestion pass: {result.pass_outcome.title()}. {result.message}")
    print(
        f"{result.total_completed_count} completed, "
        f"{result.no_id_retryable_count} no-ID retryable, "
        f"{result.new_eligible_count} new eligible, "
        f"{result.known_pending_count} known-ID pending, "
        f"{result.known_failed_count} known-ID failed."
    )
    for item in result.files:
        if item.can_attach_existing:
            print(
                f"Attach existing file is available for: {item.display_label}. The next action repeats all checks."
            )
    return 0 if result.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
