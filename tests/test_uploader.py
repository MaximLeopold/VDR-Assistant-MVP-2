from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.ingestion.uploader import (
    attach_file_and_poll,
    upload_openai_file,
)


def test_upload_opens_binary_and_uses_assistants_purpose(
    tmp_path: Path,
) -> None:
    local_path = tmp_path / "document.pdf"
    local_path.write_bytes(b"document bytes")
    client = Mock()
    uploaded = SimpleNamespace(id="file_uploaded")
    observed = {}

    def create(*, file, purpose):
        observed["mode"] = file.mode
        observed["content"] = file.read()
        observed["purpose"] = purpose
        return uploaded

    client.files.create.side_effect = create

    assert upload_openai_file(client, local_path) is uploaded
    assert observed == {
        "mode": "rb",
        "content": b"document bytes",
        "purpose": "assistants",
    }
    client.files.delete.assert_not_called()


def test_attach_and_poll_uses_exact_file_and_vector_store_ids() -> None:
    client = Mock()
    result = SimpleNamespace(status="completed")
    client.vector_stores.files.create_and_poll.return_value = result

    assert (
        attach_file_and_poll(client, "vs_manifest", "file_uploaded")
        is result
    )
    client.vector_stores.files.create_and_poll.assert_called_once_with(
        "file_uploaded",
        vector_store_id="vs_manifest",
    )
    client.vector_stores.files.delete.assert_not_called()
