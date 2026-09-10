"""Exact-ID recovery reads. No file discovery, creation, or deletion lives here."""

from dataclasses import dataclass
from openai import NotFoundError
from src.ingestion.openai_policy import read_client
from src.ingestion.remote_errors import RemoteIdentityError, UnderlyingFileMissingError
from src.ingestion.uploader import validate_attachment
from src.ingestion.vector_store_manager import retrieve_vector_store


@dataclass(frozen=True)
class KnownFileInspection:
    remote: object | None
    attachment_absent: bool = False
    requires_operator: bool = False


def verify_known_resources(client, vector_store_id: str, file_id: str) -> None:
    retrieve_vector_store(client, vector_store_id)
    try:
        remote_file = read_client(client).files.retrieve(file_id)
    except NotFoundError as error:
        raise UnderlyingFileMissingError() from error
    if getattr(remote_file, "id", None) != file_id:
        raise RemoteIdentityError("Underlying File ID does not match the persisted ID.")


def _attachment(client, vector_store_id, file_id):
    try:
        remote = read_client(client).vector_stores.files.retrieve(
            file_id, vector_store_id=vector_store_id
        )
    except NotFoundError:
        return None
    return validate_attachment(remote, vector_store_id, file_id)


def inspect_known_file(client, vector_store_id, file_id, indexing_status):
    """One status read when present; two fresh absence checks before attach eligibility.

    These are separate observations around resource validation, not an extra
    retry loop around a failed SDK request. Each GET has the SDK's two retries.
    A missing attachment can also mean a missing store; verify both resources.
    """
    remote = _attachment(client, vector_store_id, file_id)
    if remote is not None:
        return KnownFileInspection(remote)
    verify_known_resources(client, vector_store_id, file_id)
    remote = _attachment(client, vector_store_id, file_id)
    if remote is not None:
        return KnownFileInspection(remote)
    return KnownFileInspection(None, True, indexing_status != "not_started")
