from datetime import datetime, timezone
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config.case_registry import PreparedCase
from src.ingestion import case_vector_store, new_case_setup
from src.ingestion.case_vector_store import (
    CaseVectorStoreAlreadyUsedError,
    CaseVectorStoreConflictError,
    CaseVectorStoreNotEmptyError,
    CaseVectorStorePersistenceError,
    associate_empty_case_vector_store,
    mask_vector_store_id,
)
from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_builder import build_manifest
from src.ingestion.manifest_persistence import (
    ManifestPersistenceError,
    create_manifest,
    derive_manifest_paths,
    load_manifest,
)
from src.ingestion.new_case_setup import (
    NewCaseValidationError,
    StalePreviewError,
    build_new_case_preview,
    create_new_case_manifest,
    normalize_folder_input,
    normalize_new_case_id,
)
from src.ingestion.vector_store_manager import (
    InvalidVectorStoreIdError,
    VectorStoreIdMismatchError,
)


def make_external_vdr(tmp_path: Path) -> tuple[Path, Path]:
    repository_root = tmp_path / "repository"
    repository_root.mkdir(parents=True)
    vdr_folder = tmp_path / "external" / "Project B" / "VDR"
    vdr_folder.mkdir(parents=True)
    return repository_root, vdr_folder


def make_blank_manifest(vdr_folder: Path) -> VDRManifest:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return VDRManifest(
        schema_version=2,
        case_name=vdr_folder.parent.name,
        root_path=str(vdr_folder.resolve()),
        vector_store_id=None,
        created_at=now,
        updated_at=now,
        total_files=0,
        supported_files=0,
        unsupported_files=0,
        ignored_files=0,
        error_files=0,
        files=[],
    )


def registered_case(
    case_id: str,
    vdr_folder: Path,
    vector_store_id: str | None = None,
) -> PreparedCase:
    return PreparedCase(
        case_id=case_id,
        vdr_folder=vdr_folder.resolve(),
        vector_store_id=vector_store_id,
    )


class FakeVectorStoreFiles:
    def __init__(self, attachments=None):
        self.attachments = list(attachments or [])
        self.calls = []

    def list(self, vector_store_id):
        self.calls.append(vector_store_id)
        return self.attachments


class FakeVectorStores:
    def __init__(self, returned_id: str, attachments=None):
        self.returned_id = returned_id
        self.retrieve_calls = []
        self.files = FakeVectorStoreFiles(attachments)

    def retrieve(self, vector_store_id):
        self.retrieve_calls.append(vector_store_id)
        return SimpleNamespace(id=self.returned_id, name="Empty Case Store")


class FakeClient:
    def __init__(self, returned_id: str, attachments=None):
        self.vector_stores = FakeVectorStores(returned_id, attachments)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("case-02", "case-02"),
        ("  DEAL_2026_02  ", "deal_2026_02"),
        ("test-vdr-b", "test-vdr-b"),
    ],
)
def test_new_case_id_is_normalized(raw: str, expected: str) -> None:
    assert normalize_new_case_id(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", " ", "case id", "case.id", "-case", "_case", "a" * 65],
)
def test_invalid_new_case_ids_are_rejected(raw: str) -> None:
    with pytest.raises(NewCaseValidationError):
        normalize_new_case_id(raw)


def test_quoted_folder_input_is_normalized() -> None:
    assert normalize_folder_input('  "C:\\Cases\\Project B\\VDR"  ') == (
        "C:\\Cases\\Project B\\VDR"
    )


def test_scan_preview_is_sorted_read_only_and_fingerprinted(
    tmp_path: Path,
) -> None:
    repository_root, vdr_folder = make_external_vdr(tmp_path)
    nested = vdr_folder / "Nested"
    nested.mkdir()
    (vdr_folder / "z.docx").write_bytes(b"docx")
    (nested / "A.pdf").write_bytes(b"pdf")
    (vdr_folder / "table.xlsx").write_bytes(b"excel")
    (vdr_folder / "~$draft.docx").write_bytes(b"temporary")
    (vdr_folder / "empty.txt").write_bytes(b"")

    preview = build_new_case_preview(
        f'  "{vdr_folder}"  ',
        "CASE-02",
        registered_cases=[],
        repository_root=repository_root,
    )
    repeated = build_new_case_preview(
        str(vdr_folder),
        "case-02",
        registered_cases=[],
        repository_root=repository_root,
    )

    assert preview.case_id == "case-02"
    assert preview.state == "scan_preview"
    assert preview.total_files == 5
    assert preview.supported_files == 2
    assert preview.unsupported_files == 0
    assert preview.preprocess_files == 1
    assert preview.ignored_files == 2
    assert [row.relative_path for row in preview.rows] == [
        "empty.txt",
        "Nested/A.pdf",
        "table.xlsx",
        "z.docx",
        "~$draft.docx",
    ]
    assert preview.fingerprint == repeated.fingerprint
    assert preview.can_create_manifest
    assert not preview.manifest_path.exists()
    assert not preview.manifest_path.parent.exists()


def test_changed_file_metadata_changes_preview_fingerprint(tmp_path: Path) -> None:
    repository_root, vdr_folder = make_external_vdr(tmp_path)
    document = vdr_folder / "document.pdf"
    document.write_bytes(b"first")
    first = build_new_case_preview(
        str(vdr_folder),
        "case-b",
        registered_cases=[],
        repository_root=repository_root,
    )

    document.write_bytes(b"changed-size")
    second = build_new_case_preview(
        str(vdr_folder),
        "case-b",
        registered_cases=[],
        repository_root=repository_root,
    )

    assert first.fingerprint != second.fingerprint


def test_zero_supported_files_show_preview_but_block_creation(
    tmp_path: Path,
) -> None:
    repository_root, vdr_folder = make_external_vdr(tmp_path)
    (vdr_folder / "table.xls").write_bytes(b"unsupported")

    preview = build_new_case_preview(
        str(vdr_folder),
        "case-b",
        registered_cases=[],
        repository_root=repository_root,
    )

    assert preview.supported_files == 0
    assert preview.blockers == ("No supported documents or preprocessable workbooks were found.",)
    assert not preview.can_create_manifest


def test_repository_folder_registered_folder_and_duplicate_id_are_blocked(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    inside_vdr = repository_root / "Project" / "VDR"
    inside_vdr.mkdir(parents=True)
    (inside_vdr / "document.pdf").write_bytes(b"pdf")

    with pytest.raises(NewCaseValidationError, match="outside"):
        build_new_case_preview(
            str(inside_vdr),
            "case-b",
            registered_cases=[],
            repository_root=repository_root,
        )

    _, external_vdr = make_external_vdr(tmp_path / "other")
    (external_vdr / "document.pdf").write_bytes(b"pdf")
    existing = registered_case("Legacy-ID", external_vdr)

    with pytest.raises(NewCaseValidationError, match="case ID"):
        build_new_case_preview(
            str(tmp_path / "missing"),
            "legacy-id",
            registered_cases=[existing],
            repository_root=repository_root,
        )

    with pytest.raises(NewCaseValidationError, match="already registered"):
        build_new_case_preview(
            str(external_vdr),
            "new-id",
            registered_cases=[existing],
            repository_root=repository_root,
        )

    relative_variant = os.path.relpath(external_vdr, Path.cwd()).replace("\\", "/")
    with pytest.raises(NewCaseValidationError, match="already registered"):
        build_new_case_preview(
            relative_variant,
            "another-id",
            registered_cases=[existing],
            repository_root=repository_root,
        )


def test_missing_folder_and_file_path_are_rejected(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    with pytest.raises(NewCaseValidationError, match="does not exist"):
        build_new_case_preview(
            str(tmp_path / "missing"),
            "case-b",
            registered_cases=[],
            repository_root=repository_root,
        )

    local_file = tmp_path / "not-a-folder.pdf"
    local_file.write_bytes(b"file")
    with pytest.raises(NewCaseValidationError, match="not a folder"):
        build_new_case_preview(
            str(local_file),
            "case-b",
            registered_cases=[],
            repository_root=repository_root,
        )


def test_existing_unregistered_manifest_resumes_without_scanning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository_root, vdr_folder = make_external_vdr(tmp_path)
    create_manifest(make_blank_manifest(vdr_folder), vdr_folder)
    monkeypatch.setattr(
        new_case_setup,
        "build_manifest",
        lambda *_args, **_kwargs: pytest.fail("existing manifest was rescanned"),
    )

    preview = build_new_case_preview(
        str(vdr_folder),
        "case-b",
        registered_cases=[],
        repository_root=repository_root,
    )

    assert preview.state == "resume_association"
    assert preview.fingerprint is None


def test_existing_associated_manifest_is_phase1_complete(tmp_path: Path) -> None:
    repository_root, vdr_folder = make_external_vdr(tmp_path)
    manifest = make_blank_manifest(vdr_folder)
    manifest.vector_store_id = "vs_existing"
    create_manifest(manifest, vdr_folder)

    preview = build_new_case_preview(
        str(vdr_folder),
        "case-b",
        registered_cases=[],
        repository_root=repository_root,
    )

    assert preview.state == "phase1_complete"


def test_invalid_existing_manifest_is_blocked_without_overwrite(
    tmp_path: Path,
) -> None:
    repository_root, vdr_folder = make_external_vdr(tmp_path)
    paths = derive_manifest_paths(vdr_folder)
    paths.assistant_folder.mkdir()
    paths.manifest_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(NewCaseValidationError, match="invalid or unreadable"):
        build_new_case_preview(
            str(vdr_folder),
            "case-b",
            registered_cases=[],
            repository_root=repository_root,
        )

    assert paths.manifest_path.read_text(encoding="utf-8") == "{broken"


def test_manifest_creation_requires_current_reviewed_fingerprint(
    tmp_path: Path,
) -> None:
    repository_root, vdr_folder = make_external_vdr(tmp_path)
    document = vdr_folder / "document.pdf"
    document.write_bytes(b"reviewed")
    preview = build_new_case_preview(
        str(vdr_folder),
        "case-b",
        registered_cases=[],
        repository_root=repository_root,
    )

    document.write_bytes(b"changed-after-review")

    with pytest.raises(StalePreviewError, match="changed"):
        create_new_case_manifest(vdr_folder, preview.fingerprint or "")
    assert not derive_manifest_paths(vdr_folder).manifest_path.exists()


def test_manifest_is_created_once_with_existing_schema_defaults(
    tmp_path: Path,
) -> None:
    repository_root, vdr_folder = make_external_vdr(tmp_path)
    (vdr_folder / "document.pdf").write_bytes(b"reviewed")
    preview = build_new_case_preview(
        str(vdr_folder),
        "case-b",
        registered_cases=[],
        repository_root=repository_root,
    )

    result = create_new_case_manifest(vdr_folder, preview.fingerprint or "")
    persisted = load_manifest(vdr_folder)

    assert result.manifest_path == derive_manifest_paths(vdr_folder).manifest_path
    assert persisted.schema_version == 2
    assert persisted.vector_store_id is None
    assert persisted.files[0].upload_status == "not_uploaded"
    assert persisted.files[0].indexing_status == "not_started"

    with pytest.raises(new_case_setup.ExistingManifestError):
        create_new_case_manifest(vdr_folder, preview.fingerprint or "")


def test_empty_unused_vector_store_is_associated_and_reloaded(
    tmp_path: Path,
) -> None:
    _, vdr_folder = make_external_vdr(tmp_path)
    create_manifest(make_blank_manifest(vdr_folder), vdr_folder)
    client = FakeClient("vs_empty_store")

    result = associate_empty_case_vector_store(
        client,
        vdr_folder,
        "  vs_empty_store  ",
        registered_cases=[],
    )

    assert result.action == "adopted"
    assert result.vector_store_id == "vs_empty_store"
    assert result.manifest.vector_store_id == "vs_empty_store"
    assert load_manifest(vdr_folder).vector_store_id == "vs_empty_store"
    assert client.vector_stores.retrieve_calls == ["vs_empty_store"]
    assert client.vector_stores.files.calls == ["vs_empty_store"]


def test_nonempty_or_registered_vector_store_is_blocked(tmp_path: Path) -> None:
    _, vdr_folder = make_external_vdr(tmp_path)
    create_manifest(make_blank_manifest(vdr_folder), vdr_folder)
    nonempty_client = FakeClient(
        "vs_populated",
        attachments=[SimpleNamespace(id="file_existing")],
    )

    with pytest.raises(CaseVectorStoreNotEmptyError):
        associate_empty_case_vector_store(
            nonempty_client,
            vdr_folder,
            "vs_populated",
            registered_cases=[],
        )
    assert load_manifest(vdr_folder).vector_store_id is None

    used_client = FakeClient("vs_used")
    used_case = registered_case("other", tmp_path / "other-vdr", "vs_used")
    with pytest.raises(CaseVectorStoreAlreadyUsedError):
        associate_empty_case_vector_store(
            used_client,
            vdr_folder,
            "vs_used",
            registered_cases=[used_case],
        )
    assert used_client.vector_stores.retrieve_calls == []


def test_blank_or_mismatched_vector_store_id_is_not_persisted(
    tmp_path: Path,
) -> None:
    _, vdr_folder = make_external_vdr(tmp_path)
    create_manifest(make_blank_manifest(vdr_folder), vdr_folder)
    client = FakeClient("vs_returned")

    with pytest.raises(InvalidVectorStoreIdError):
        associate_empty_case_vector_store(
            client,
            vdr_folder,
            "   ",
            registered_cases=[],
        )
    assert client.vector_stores.retrieve_calls == []

    with pytest.raises(VectorStoreIdMismatchError):
        associate_empty_case_vector_store(
            client,
            vdr_folder,
            "vs_requested",
            registered_cases=[],
        )
    assert load_manifest(vdr_folder).vector_store_id is None


def test_existing_same_association_is_reused_without_remote_call(
    tmp_path: Path,
) -> None:
    _, vdr_folder = make_external_vdr(tmp_path)
    manifest = make_blank_manifest(vdr_folder)
    manifest.vector_store_id = "vs_persisted"
    create_manifest(manifest, vdr_folder)
    client = FakeClient("vs_persisted")

    result = associate_empty_case_vector_store(
        client,
        vdr_folder,
        "vs_persisted",
        registered_cases=[],
    )

    assert result.action == "reused"
    assert client.vector_stores.retrieve_calls == []
    assert client.vector_stores.files.calls == []


def test_switching_association_is_blocked(tmp_path: Path) -> None:
    _, vdr_folder = make_external_vdr(tmp_path)
    manifest = make_blank_manifest(vdr_folder)
    manifest.vector_store_id = "vs_first"
    create_manifest(manifest, vdr_folder)

    with pytest.raises(CaseVectorStoreConflictError):
        associate_empty_case_vector_store(
            FakeClient("vs_second"),
            vdr_folder,
            "vs_second",
            registered_cases=[],
        )
    assert load_manifest(vdr_folder).vector_store_id == "vs_first"


def test_association_save_failure_is_retryable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, vdr_folder = make_external_vdr(tmp_path)
    create_manifest(make_blank_manifest(vdr_folder), vdr_folder)
    client = FakeClient("vs_retry")
    monkeypatch.setattr(
        case_vector_store,
        "save_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ManifestPersistenceError("simulated save failure")
        ),
    )

    with pytest.raises(CaseVectorStorePersistenceError) as error:
        associate_empty_case_vector_store(
            client,
            vdr_folder,
            "vs_retry",
            registered_cases=[],
        )

    assert error.value.vector_store_id == "vs_retry"
    assert load_manifest(vdr_folder).vector_store_id is None


def test_vector_store_mask_never_returns_full_normal_id() -> None:
    full_id = "vs_abcdefghijklmnopqrstuvwxyz789"
    masked = mask_vector_store_id(full_id)

    assert masked == "vs_abc...789"
    assert full_id not in masked
