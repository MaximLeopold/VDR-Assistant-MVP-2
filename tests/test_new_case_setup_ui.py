from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest

from src.config import settings
from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_builder import build_manifest
from src.ingestion.manifest_persistence import (
    create_manifest,
    load_manifest,
)
from src.ui import new_case_setup as new_case_ui


def make_registered_case(root: Path) -> Path:
    vdr_folder = root / "existing" / "VDR"
    vdr_folder.mkdir(parents=True)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manifest = VDRManifest(
        case_name="Existing Case",
        root_path=str(vdr_folder.resolve()),
        vector_store_id="vs_existing",
        created_at=now,
        updated_at=now,
        total_files=0,
        supported_files=0,
        unsupported_files=0,
        ignored_files=0,
        error_files=0,
        files=[],
    )
    create_manifest(manifest, vdr_folder)
    return vdr_folder


class FakeFiles:
    def __init__(self):
        self.calls = []
        self.attach_calls = []

    def list(self, vector_store_id):
        self.calls.append(vector_store_id)
        return []

    def create_and_poll(self, file_id, *, vector_store_id):
        self.attach_calls.append((vector_store_id, file_id))
        return SimpleNamespace(status="completed")


class FakeOpenAIFiles:
    def __init__(self):
        self.create_calls = []

    def create(self, *, file, purpose):
        self.create_calls.append((Path(file.name).name, purpose))
        return SimpleNamespace(id=f"file_{Path(file.name).stem}")


class FakeVectorStores:
    def __init__(self):
        self.retrieve_calls = []
        self.files = FakeFiles()

    def retrieve(self, vector_store_id):
        self.retrieve_calls.append(vector_store_id)
        return SimpleNamespace(id=vector_store_id, name="Empty UI Store")


class FakeClient:
    def __init__(self):
        self.vector_stores = FakeVectorStores()
        self.files = FakeOpenAIFiles()


def button_with_label(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def input_with_label(app: AppTest, label: str):
    return next(widget for widget in app.text_input if widget.label == label)


def test_setup_state_does_not_change_active_case_and_cancel_is_local() -> None:
    state = {
        "selected_case_id": None,
        "active_case": None,
        "messages": [],
        "last_answer": None,
    }

    new_case_ui.start_new_case_setup(state)

    assert state["setup_active"] is True
    assert state["setup_step"] == "details"
    assert state["selected_case_id"] is None
    assert state["active_case"] is None

    new_case_ui.clear_new_case_setup_session(state)

    assert "setup_active" not in state
    assert state["selected_case_id"] is None
    assert state["active_case"] is None


def test_phase1_streamlit_flow_uses_fake_client_and_does_not_register(
    tmp_path: Path,
    monkeypatch,
) -> None:
    existing_vdr = make_registered_case(tmp_path)
    registry_path = tmp_path / "cases.json"
    original_registry = {
        "cases": [
            {
                "case_id": "existing",
                "vdr_folder": str(existing_vdr),
            }
        ]
    }
    registry_path.write_text(json.dumps(original_registry), encoding="utf-8")

    new_vdr = tmp_path / "new" / "Project B" / "VDR"
    new_vdr.mkdir(parents=True)
    (new_vdr / "A.pdf").write_bytes(b"supported")
    (new_vdr / "B.xlsx").write_bytes(b"unsupported")

    fake_client = FakeClient()
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(new_case_ui, "get_openai_client", lambda: fake_client)

    app = AppTest.from_file("app/main.py").run()
    assert len(app.exception) == 0
    assert button_with_label(app, "Prepare new case") is not None

    button_with_label(app, "Prepare new case").click().run()
    assert len(app.exception) == 0
    assert len(app.chat_input) == 0
    assert fake_client.vector_stores.retrieve_calls == []

    input_with_label(app, "Local VDR folder").input(str(new_vdr))
    input_with_label(app, "Technical case ID").input("CASE-B")
    app.run()
    button_with_label(app, "Validate and scan").click().run()

    assert len(app.exception) == 0
    assert any(button.label == "Create manifest" for button in app.button)
    assert fake_client.vector_stores.retrieve_calls == []
    assert not (new_vdr.parent / "VDR Assistant" / "manifest.json").exists()

    button_with_label(app, "Create manifest").click().run()

    assert len(app.exception) == 0
    assert input_with_label(app, "OpenAI vector-store ID") is not None
    assert load_manifest(new_vdr).vector_store_id is None
    assert fake_client.vector_stores.retrieve_calls == []

    input_with_label(app, "OpenAI vector-store ID").input("vs_new_case")
    app.run()
    button_with_label(app, "Validate and associate").click().run()

    assert len(app.exception) == 0
    assert fake_client.vector_stores.retrieve_calls == ["vs_new_case"]
    assert fake_client.vector_stores.files.calls == ["vs_new_case"]
    assert load_manifest(new_vdr).vector_store_id == "vs_new_case"
    assert json.loads(registry_path.read_text(encoding="utf-8")) == original_registry
    assert any("Phase 1 complete" in subheader.value for subheader in app.subheader)
    assert all("vs_new_case" not in element.value for element in app.markdown)
    assert any("vs_new...ase" in element.value for element in app.markdown)
    assert len(app.chat_input) == 0

    button_with_label(app, "Return to case selection").click().run()

    assert len(app.exception) == 0
    assert app.selectbox[0].options == ["Existing Case"]
    assert all(button.label != "Open case" for button in app.button)


def test_active_case_never_shows_setup_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    existing_vdr = make_registered_case(tmp_path)
    registry_path = tmp_path / "cases.json"
    registry_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "existing",
                        "vdr_folder": str(existing_vdr),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")

    app = AppTest.from_file("app/main.py").run()
    app.selectbox[0].select("existing").run()
    button_with_label(app, "Open case").click().run()

    assert len(app.exception) == 0
    assert len(app.chat_input) == 1
    assert all(button.label != "Prepare new case" for button in app.button)


def test_phase2_streamlit_flow_previews_uploads_and_registers_with_fake_client(
    tmp_path: Path,
    monkeypatch,
) -> None:
    existing_vdr = make_registered_case(tmp_path)
    registry_path = tmp_path / "cases.json"
    registry_path.write_text(
        json.dumps(
            {
                "cases": [
                    {"case_id": "existing", "vdr_folder": str(existing_vdr)}
                ]
            }
        ),
        encoding="utf-8",
    )
    new_vdr = tmp_path / "new" / "Project B" / "VDR"
    new_vdr.mkdir(parents=True)
    (new_vdr / "document.pdf").write_bytes(b"phase two")

    fake_client = FakeClient()
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(new_case_ui, "get_openai_client", lambda: fake_client)

    app = AppTest.from_file("app/main.py").run()
    button_with_label(app, "Prepare new case").click().run()
    input_with_label(app, "Local VDR folder").input(str(new_vdr))
    input_with_label(app, "Technical case ID").input("CASE-B")
    app.run()
    button_with_label(app, "Validate and scan").click().run()
    button_with_label(app, "Create manifest").click().run()
    input_with_label(app, "OpenAI vector-store ID").input("vs_new_case")
    app.run()
    button_with_label(app, "Validate and associate").click().run()

    button_with_label(app, "Continue case preparation").click().run()

    assert len(app.exception) == 0
    assert any("Upload preview" in item.value for item in app.subheader)
    assert fake_client.files.create_calls == []
    assert fake_client.vector_stores.files.attach_calls == []
    assert load_manifest(new_vdr).files[0].upload_status == "not_uploaded"

    button_with_label(app, "Upload and index all eligible files").click().run()

    assert len(app.exception) == 0
    assert fake_client.files.create_calls == [("document.pdf", "assistants")]
    assert fake_client.vector_stores.files.attach_calls == [
        ("vs_new_case", "file_document")
    ]
    persisted = load_manifest(new_vdr).files[0]
    assert persisted.openai_file_id == "file_document"
    assert persisted.upload_status == "uploaded"
    assert persisted.indexing_status == "completed"
    assert any("Upload result" in item.value for item in app.subheader)

    button_with_label(app, "Continue to registration").click().run()
    assert any("Register prepared case" in item.value for item in app.subheader)
    button_with_label(app, "Register prepared case").click().run()

    assert len(app.exception) == 0
    assert any("Case preparation complete" in item.value for item in app.subheader)
    stored = json.loads(registry_path.read_text(encoding="utf-8"))
    assert stored["cases"][-1] == {
        "case_id": "case-b",
        "vdr_folder": new_vdr.resolve().as_posix(),
    }

    button_with_label(app, "Return to case selection").click().run()
    assert len(app.exception) == 0
    assert "Project B" in app.selectbox[0].options
    assert len(app.chat_input) == 0


def test_restart_resume_reuses_associated_manifest_and_preview_is_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    existing_vdr = make_registered_case(tmp_path)
    registry_path = tmp_path / "cases.json"
    registry_path.write_text(
        json.dumps(
            {
                "cases": [
                    {"case_id": "existing", "vdr_folder": str(existing_vdr)}
                ]
            }
        ),
        encoding="utf-8",
    )
    new_vdr = tmp_path / "resume" / "Project C" / "VDR"
    new_vdr.mkdir(parents=True)
    (new_vdr / "document.pdf").write_bytes(b"resume")
    manifest = build_manifest(str(new_vdr))
    manifest.vector_store_id = "vs_resume"
    create_manifest(manifest, new_vdr)
    before = load_manifest(new_vdr).model_dump()

    factory = Mock(return_value=FakeClient())
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(new_case_ui, "get_openai_client", factory)

    app = AppTest.from_file("app/main.py").run()
    button_with_label(app, "Prepare new case").click().run()
    input_with_label(app, "Local VDR folder").input(str(new_vdr))
    input_with_label(app, "Technical case ID").input("CASE-C")
    app.run()
    button_with_label(app, "Validate and scan").click().run()

    assert any("Phase 1 complete" in item.value for item in app.subheader)
    assert factory.call_count == 0
    button_with_label(app, "Continue case preparation").click().run()

    assert any("Upload preview" in item.value for item in app.subheader)
    assert factory.call_count == 0
    assert load_manifest(new_vdr).model_dump() == before
