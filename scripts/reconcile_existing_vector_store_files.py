"""Reconcile historical OpenAI files with supported manifest records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    load_manifest,
    save_manifest,
)
from src.ingestion.vector_store_manager import (
    list_vector_store_files,
    normalize_vector_store_id,
    retrieve_openai_file,
)
from src.retrieval.openai_file_search import get_openai_client


@dataclass(frozen=True)
class RemoteFileMetadata:
    """Remote metadata used for exact reconciliation."""

    file_id: str
    filename: str
    size_bytes: int


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


def build_reconciliation_plan(
    manifest: VDRManifest,
    remote_files: list[RemoteFileMetadata],
) -> dict[str, list]:
    """Build a reconciliation preview without mutating the manifest."""

    local_by_key: dict[tuple[str, int], list[tuple[int, object]]] = {}
    for index, file_record in enumerate(manifest.files):
        if file_record.classification_status != "supported":
            continue
        key = (file_record.filename, file_record.size_bytes)
        local_by_key.setdefault(key, []).append((index, file_record))

    remote_by_key: dict[tuple[str, int], list[RemoteFileMetadata]] = {}
    for remote_file in remote_files:
        key = (remote_file.filename, remote_file.size_bytes)
        remote_by_key.setdefault(key, []).append(remote_file)

    plan: dict[str, list] = {
        "matched": [],
        "local_only": [],
        "remote_only": [],
        "ambiguous": [],
    }

    for key in sorted(set(local_by_key) | set(remote_by_key)):
        local_candidates = local_by_key.get(key, [])
        remote_candidates = remote_by_key.get(key, [])

        if len(local_candidates) == 1 and len(remote_candidates) == 1:
            local_index, local_file = local_candidates[0]
            remote_file = remote_candidates[0]

            if (
                local_file.openai_file_id is not None
                and local_file.openai_file_id != remote_file.file_id
            ):
                plan["ambiguous"].append(
                    {
                        "key": key,
                        "local": local_candidates,
                        "remote": remote_candidates,
                        "reason": "existing OpenAI file ID conflict",
                    }
                )
                continue

            state = (
                "already reconciled"
                if local_file.openai_file_id == remote_file.file_id
                else "will write"
            )
            plan["matched"].append(
                {
                    "local_index": local_index,
                    "local": local_file,
                    "remote": remote_file,
                    "state": state,
                }
            )
        elif local_candidates and not remote_candidates:
            plan["local_only"].extend(local_candidates)
        elif remote_candidates and not local_candidates:
            plan["remote_only"].extend(remote_candidates)
        else:
            plan["ambiguous"].append(
                {
                    "key": key,
                    "local": local_candidates,
                    "remote": remote_candidates,
                    "reason": "multiple matching candidates",
                }
            )

    return plan


def _print_preview(plan: dict[str, list]) -> None:
    print("\nMATCHED")
    for match in plan["matched"]:
        local_file = match["local"]
        remote_file = match["remote"]
        print(
            f"- {local_file.relative_path} | {remote_file.filename} | "
            f"{remote_file.size_bytes} bytes | {remote_file.file_id} | "
            f"{match['state']}"
        )

    print("\nLOCAL ONLY")
    for _, local_file in plan["local_only"]:
        print(
            f"- {local_file.relative_path} | {local_file.filename} | "
            f"{local_file.size_bytes} bytes"
        )

    print("\nREMOTE ONLY")
    for remote_file in plan["remote_only"]:
        print(
            f"- {remote_file.filename} | {remote_file.size_bytes} bytes | "
            f"{remote_file.file_id}"
        )

    print("\nAMBIGUOUS")
    for group in plan["ambiguous"]:
        filename, size_bytes = group["key"]
        local_paths = [
            file_record.relative_path
            for _, file_record in group["local"]
        ]
        remote_ids = [
            remote_file.file_id
            for remote_file in group["remote"]
        ]
        print(
            f"- {filename} | {size_bytes} bytes | {group['reason']} | "
            f"local={local_paths} | remote={remote_ids}"
        )


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

    try:
        client = get_openai_client()
        attachments = list_vector_store_files(client, vector_store_id)
        remote_files = []
        for attachment in attachments:
            openai_file = retrieve_openai_file(client, attachment.id)
            remote_files.append(
                RemoteFileMetadata(
                    file_id=openai_file.id,
                    filename=openai_file.filename,
                    size_bytes=openai_file.bytes,
                )
            )
    except Exception as error:
        print(f"Could not read vector-store files: {error}", file=sys.stderr)
        return 1

    plan = build_reconciliation_plan(manifest, remote_files)
    planned_matches = [
        match
        for match in plan["matched"]
        if match["state"] == "will write"
    ]

    print(f"Case name: {manifest.case_name}")
    print(f"Selected VDR path: {Path(vdr_folder).expanduser().resolve()}")
    print(f"Vector-store ID: {vector_store_id}")
    print(f"Remote vector-store file count: {len(remote_files)}")
    print(f"Manifest IDs that would be written: {len(planned_matches)}")
    _print_preview(plan)

    if not planned_matches:
        print("\nThe manifest is already reconciled; no save is required.")
        return 0

    confirmation = input(
        "\nType RECONCILE to save these manifest file IDs: "
    ).strip()
    if confirmation != "RECONCILE":
        print("Reconciliation aborted. The manifest was not saved.")
        return 2

    for match in planned_matches:
        manifest.files[match["local_index"]].openai_file_id = (
            match["remote"].file_id
        )

    try:
        manifest_path = save_manifest(manifest, vdr_folder)
    except ManifestPersistenceError as error:
        print(
            f"Reconciliation was not persisted: {error}\n"
            "No OpenAI resources were modified.",
            file=sys.stderr,
        )
        return 1

    print(f"Reconciled manifest: {manifest_path}")
    print("No OpenAI resources were modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
