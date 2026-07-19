"""Upload new supported manifest files to the case vector store."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    load_manifest,
    save_manifest,
)
from src.ingestion.uploader import (
    attach_file_and_poll,
    upload_openai_file,
)
from src.ingestion.vector_store_manager import normalize_vector_store_id
from src.retrieval.openai_file_search import get_openai_client


def normalize_vdr_folder_input(raw_path: str) -> str:
    """Normalize a normally pasted local folder path."""

    normalized = raw_path.strip()
    if (
        len(normalized) >= 2
        and normalized.startswith('"')
        and normalized.endswith('"')
    ):
        normalized = normalized[1:-1].strip()
    return normalized


def select_eligible_records(manifest) -> list:
    """Select supported records that do not yet have an OpenAI file ID."""

    return [
        record
        for record in manifest.files
        if record.classification_status == "supported"
        and record.openai_file_id is None
    ]


def preflight_local_files(
    vdr_folder: str | Path,
    records: list,
) -> list[tuple[object, Path]]:
    """Resolve and validate every eligible local file without mutation."""

    root = Path(vdr_folder).expanduser().resolve()
    validated = []

    for record in records:
        relative_path = Path(record.relative_path)
        if relative_path.is_absolute() or relative_path.drive:
            raise ValueError(
                f"{record.relative_path}: absolute paths are not allowed"
            )

        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError(
                f"{record.relative_path}: path escapes the selected VDR folder"
            ) from error

        if not candidate.is_file():
            reason = "path is not a file" if candidate.exists() else "file is missing"
            raise ValueError(f"{record.relative_path}: {reason}")

        actual_size = candidate.stat().st_size
        if actual_size != record.size_bytes:
            raise ValueError(
                f"{record.relative_path}: size changed from "
                f"{record.size_bytes} to {actual_size} bytes"
            )

        validated.append((record, candidate))

    return validated


def _concise_error(error: Exception) -> str:
    message = " ".join(str(error).split())
    detail = f"{type(error).__name__}: {message}" if message else type(error).__name__
    return detail[:500]


def _remote_failure_message(remote_result) -> str:
    status = getattr(remote_result, "status", "unknown")
    remote_error = getattr(remote_result, "last_error", None)
    code = getattr(remote_error, "code", None)
    message = getattr(remote_error, "message", None)
    details = [f"Remote indexing status: {status}."]
    if code:
        details.append(f"Code: {code}.")
    if message:
        details.append(str(message))
    return " ".join(details)[:500]


def _save_or_report(manifest, vdr_folder, context: str) -> bool:
    try:
        save_manifest(manifest, vdr_folder)
        return True
    except ManifestPersistenceError as error:
        print(f"{context}: {error}", file=sys.stderr)
        return False


def main() -> int:
    raw_path = input("Enter the selected local VDR folder path: ")
    vdr_folder = normalize_vdr_folder_input(raw_path)
    if not vdr_folder:
        print("A local VDR folder path is required.", file=sys.stderr)
        return 1

    try:
        manifest = load_manifest(vdr_folder)
        vector_store_id = normalize_vector_store_id(
            manifest.vector_store_id
        )
    except Exception as error:
        print(f"Could not load a configured case manifest: {error}", file=sys.stderr)
        return 1

    eligible_records = select_eligible_records(manifest)
    if not eligible_records:
        print("No supported manifest files require upload.")
        return 0

    try:
        validated_files = preflight_local_files(
            vdr_folder,
            eligible_records,
        )
    except ValueError as error:
        print(f"Upload preflight failed: {error}", file=sys.stderr)
        return 1

    print(f"Case name: {manifest.case_name}")
    print(f"Selected VDR path: {Path(vdr_folder).expanduser().resolve()}")
    print(f"Files requiring upload: {len(validated_files)}")
    print("\nFILES TO UPLOAD")
    for record, _ in validated_files:
        print(
            f"- {record.relative_path} | {record.filename} | "
            f"{record.size_bytes} bytes | {record.upload_status} | "
            f"{record.indexing_status}"
        )

    confirmation = input(
        "\nType UPLOAD to upload and index these files: "
    ).strip()
    if confirmation != "UPLOAD":
        print("Upload aborted. No manifest or OpenAI resource was changed.")
        return 2

    try:
        client = get_openai_client()
    except Exception as error:
        print(f"Could not construct the OpenAI client: {_concise_error(error)}", file=sys.stderr)
        return 1

    completed = 0
    failed = 0

    for record, local_path in validated_files:
        record.upload_attempts += 1
        record.upload_status = "uploading"
        record.indexing_status = "not_started"
        record.last_error = None

        if not _save_or_report(
            manifest,
            vdr_folder,
            f"Could not persist the uploading state for {record.relative_path}",
        ):
            return 1

        try:
            uploaded = upload_openai_file(client, local_path)
            uploaded_id = getattr(uploaded, "id", None)
            if not isinstance(uploaded_id, str) or not uploaded_id.strip():
                raise ValueError("OpenAI returned an uploaded File without an ID")
            uploaded_id = uploaded_id.strip()
        except Exception as error:
            record.openai_file_id = None
            record.upload_status = "failed"
            record.indexing_status = "not_started"
            record.last_error = f"Upload failed: {_concise_error(error)}"
            if not _save_or_report(
                manifest,
                vdr_folder,
                f"Could not persist upload failure for {record.relative_path}",
            ):
                return 1
            print(f"Upload failed for {record.relative_path}: {record.last_error}")
            failed += 1
            continue

        record.openai_file_id = uploaded_id
        record.upload_status = "uploaded"
        record.indexing_status = "not_started"
        record.last_error = None

        if not _save_or_report(
            manifest,
            vdr_folder,
            f"Uploaded File ID {uploaded_id} was not persisted",
        ):
            print(
                f"Preserve OpenAI File ID {uploaded_id} and reconcile it "
                "manually before rerunning uploads.",
                file=sys.stderr,
            )
            return 1

        record.indexing_status = "in_progress"
        try:
            remote_result = attach_file_and_poll(
                client,
                vector_store_id,
                uploaded_id,
            )
            remote_status = getattr(remote_result, "status", None)
            if remote_status == "completed":
                record.upload_status = "uploaded"
                record.indexing_status = "completed"
                record.last_error = None
                completed += 1
            else:
                record.upload_status = "uploaded"
                record.indexing_status = "failed"
                record.last_error = _remote_failure_message(remote_result)
                failed += 1
        except Exception as error:
            record.upload_status = "uploaded"
            record.indexing_status = "failed"
            record.last_error = (
                "Attachment/indexing failed; final remote indexing state "
                f"could not be confirmed. {_concise_error(error)}"
            )[:500]
            failed += 1

        if not _save_or_report(
            manifest,
            vdr_folder,
            f"Could not persist terminal state for {record.relative_path}",
        ):
            return 1

    print(
        f"Upload workflow finished: {completed} completed, "
        f"{failed} failed."
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
