from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.config.case_registry import PreparedCase
from src.config import settings
from src.context.conversation_context import build_conversation_context
from src.ingestion.manifest import VDRManifest
from src.ingestion.manifest_persistence import create_manifest
from src.schemas.answer import VDRAnswer
from src.ui import case_selection, sidebar


def manifest(case_name: str, vector_store_id: str) -> VDRManifest:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return VDRManifest(
        schema_version=2,
        snapshot_state="sealed",
        case_name=case_name,
        vector_store_id=vector_store_id,
        created_at=now,
        updated_at=now,
        total_files=0,
        supported_files=0,
        unsupported_files=0,
        ignored_files=0,
        error_files=0,
        files=[],
    )


def prepared_case(case_id: str, case_name: str, vector_store_id: str):
    case_manifest = manifest(case_name, vector_store_id)
    return PreparedCase(
        case_id=case_id,
        vdr_folder=Path("test-fixtures") / case_id / "VDR",
        case_name=case_name,
        manifest=case_manifest,
        vector_store_id=vector_store_id,
    )


def make_registered_case(
    root: Path,
    case_id: str,
    case_name: str,
    vector_store_id: str,
) -> Path:
    vdr_folder = root / case_id / "VDR"
    vdr_folder.mkdir(parents=True)
    candidate=manifest(case_name,vector_store_id)
    candidate.root_path=str(vdr_folder.resolve())
    create_manifest(candidate,vdr_folder)
    return vdr_folder


def write_registry(path: Path, cases: list[dict]) -> None:
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")


def button_with_label(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_startup_initializes_with_no_selected_case() -> None:
    state = {}

    case_selection.initialize_case_session(state)

    assert state == {
        "messages": [],
        "last_answer": None,
        "selected_case_id": None,
        "active_case": None,
    }
    assert case_selection.get_active_case(state) is None


def test_normal_chat_settings_do_not_require_legacy_single_case_values(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "VECTOR_STORE_ID", None)
    monkeypatch.setattr(settings, "VDR_FOLDER", None)

    assert settings.validate_settings() == []


def test_selection_stores_case_and_clears_previous_answer_state() -> None:
    selected = prepared_case("case-a", "Case A", "vs_a")
    state = {
        "messages": [{"role": "assistant", "content": "Old answer"}],
        "last_answer": VDRAnswer(answer="Old answer"),
    }

    case_selection.activate_case(state, selected)

    assert state["selected_case_id"] == "case-a"
    assert state["active_case"] is selected
    assert state["messages"] == []
    assert state["last_answer"] is None


def test_selected_manifest_and_vector_store_are_exact_qa_inputs() -> None:
    selected = prepared_case("case-a", "Case A", "vs_a")

    vector_store_id, selected_manifest = case_selection.active_case_qa_inputs(
        selected
    )

    assert vector_store_id == "vs_a"
    assert selected_manifest is selected.manifest


def test_close_case_returns_to_selection_and_removes_sources() -> None:
    selected = prepared_case("case-a", "Case A", "vs_a")
    old_answer = VDRAnswer(answer="Old answer", source_files=["Old.pdf"])
    state = {}
    case_selection.initialize_case_session(state)
    case_selection.activate_case(state, selected)
    state["messages"] = [
        {
            "role": "assistant",
            "content": old_answer.answer,
            "vdr_answer": old_answer.model_dump(mode="json"),
        }
    ]
    state["last_answer"] = old_answer

    case_selection.close_active_case(state)

    assert case_selection.get_active_case(state) is None
    assert state["selected_case_id"] is None
    assert state["active_case"] is None
    assert state["messages"] == []
    assert state["last_answer"] is None


def test_switching_a_to_b_clears_a_context_before_b() -> None:
    case_a = prepared_case("case-a", "Case A", "vs_a")
    case_b = prepared_case("case-b", "Case B", "vs_b")
    state = {}
    case_selection.initialize_case_session(state)
    case_selection.activate_case(state, case_a)
    state["messages"] = [
        {"role": "user", "content": "Question only for Case A"},
        {"role": "assistant", "content": "Answer only for Case A"},
    ]
    state["last_answer"] = VDRAnswer(
        answer="Answer only for Case A",
        source_files=["Case A source.pdf"],
    )

    case_selection.activate_case(state, case_b)

    assert case_selection.get_active_case(state) is case_b
    assert state["messages"] == []
    assert state["last_answer"] is None
    assert build_conversation_context(state["messages"]) == ""


def test_inconsistent_active_case_state_fails_closed_and_clears_history() -> None:
    state = {
        "selected_case_id": "case-b",
        "active_case": prepared_case("case-a", "Case A", "vs_a"),
        "messages": [{"role": "user", "content": "Old context"}],
        "last_answer": VDRAnswer(answer="Old answer"),
    }

    assert case_selection.get_active_case(state) is None
    assert state["messages"] == []
    assert state["last_answer"] is None
    assert state["selected_case_id"] is None
    assert state["active_case"] is None


def test_missing_active_case_object_clears_orphaned_case_state() -> None:
    state = {
        "selected_case_id": "case-a",
        "active_case": None,
        "messages": [{"role": "user", "content": "Old context"}],
        "last_answer": VDRAnswer(answer="Old answer"),
    }

    assert case_selection.get_active_case(state) is None
    assert state["messages"] == []
    assert state["last_answer"] is None
    assert state["selected_case_id"] is None


def test_invalid_case_cannot_supply_qa_inputs() -> None:
    invalid = PreparedCase(
        case_id="invalid",
        vdr_folder=Path("unavailable") / "VDR",
        error="The case manifest is invalid.",
    )

    with pytest.raises(case_selection.ActiveCaseError, match="manifest"):
        case_selection.active_case_qa_inputs(invalid)


class FakeCaseSelectionStreamlit:
    def __init__(self, selected_case_id=None, open_clicked=False):
        self.selected_case_id = selected_case_id
        self.open_clicked = open_clicked
        self.formatted_options = []
        self.subheaders = []

    def subheader(self, body):
        self.subheaders.append(body)

    def caption(self, body):
        pass

    def selectbox(self, label, options, **kwargs):
        self.formatted_options = [
            kwargs["format_func"](case_id) for case_id in options
        ]
        return self.selected_case_id

    def button(self, label, **kwargs):
        return self.open_clicked


def test_selector_requires_explicit_open_and_displays_manifest_name(
    monkeypatch,
) -> None:
    valid = prepared_case("case-a", "Manifest Case A", "vs_a")
    invalid = PreparedCase(
        case_id="case-b",
        vdr_folder=Path("missing") / "VDR",
        error="The configured VDR folder is unavailable.",
    )
    fake_st = FakeCaseSelectionStreamlit("case-a", open_clicked=False)
    monkeypatch.setattr(case_selection, "st", fake_st)

    assert case_selection.render_case_selection([valid, invalid]) is None
    assert fake_st.formatted_options == [
        "Manifest Case A",
        "case-b — configuration issue",
    ]

    fake_st.open_clicked = True
    assert case_selection.render_case_selection([valid, invalid]) is valid


class FakeSidebar:
    def __init__(self):
        self.success_calls = []
        self.button_labels = []

    def header(self, body):
        pass

    def success(self, body):
        self.success_calls.append(body)

    def selectbox(self, label, options, **kwargs):
        return "qa"

    def divider(self):
        pass

    def button(self, label, **kwargs):
        self.button_labels.append(label)
        return label == "Close case"


class FakeSidebarStreamlit:
    def __init__(self):
        self.sidebar = FakeSidebar()


def test_active_sidebar_shows_case_name_without_vector_store_override(
    monkeypatch,
) -> None:
    fake_st = FakeSidebarStreamlit()
    monkeypatch.setattr(sidebar, "st", fake_st)

    mode, reset_chat, close_case = sidebar.render_sidebar("Manifest Case A")

    assert mode == "qa"
    assert reset_chat is False
    assert close_case is True
    assert fake_st.sidebar.success_calls == ["Manifest Case A"]
    assert fake_st.sidebar.button_labels == ["Reset chat", "Close case"]


def test_streamlit_gate_opens_with_manifest_owned_case_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vdr_folder = make_registered_case(
        tmp_path,
        "case-a",
        "Manifest Case A",
        "vs_case_a",
    )
    registry_path = tmp_path / "cases.json"
    write_registry(
        registry_path,
        [{"case_id": "case-a", "vdr_folder": str(vdr_folder)}],
    )
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")

    app = AppTest.from_file("app/main.py").run()
    assert len(app.exception) == 0
    assert len(app.chat_input) == 0
    assert app.selectbox[0].label == "Prepared case"

    app.selectbox[0].select("case-a").run()
    button_with_label(app, "Open case").click().run()

    assert len(app.exception) == 0
    assert len(app.chat_input) == 1
    assert any(message.value == "Manifest Case A" for message in app.success)
    active = app.session_state["active_case"]
    assert active.vector_store_id == "vs_case_a"
    assert active.manifest.case_name == "Manifest Case A"
    assert app.session_state["messages"] == []
    assert app.session_state["last_answer"] is None


def test_streamlit_missing_registry_blocks_chat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "CASE_REGISTRY_PATH",
        str(tmp_path / "missing-cases.json"),
    )

    app = AppTest.from_file("app/main.py").run()

    assert len(app.exception) == 0
    assert len(app.chat_input) == 0
    assert any("could not be found" in error.value for error in app.error)


def test_streamlit_invalid_selected_case_blocks_chat_and_qa(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path = tmp_path / "cases.json"
    write_registry(
        registry_path,
        [
            {
                "case_id": "invalid-case",
                "vdr_folder": str(tmp_path / "missing" / "VDR"),
            }
        ],
    )
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    qa_calls = []
    monkeypatch.setattr(
        "src.chains.qa_chain.run_qa_chain",
        lambda **kwargs: qa_calls.append(kwargs),
    )

    app = AppTest.from_file("app/main.py").run()
    app.selectbox[0].select("invalid-case").run()
    button_with_label(app, "Open case").click().run()

    assert len(app.exception) == 0
    assert len(app.chat_input) == 0
    assert qa_calls == []
    assert any("cannot be opened" in error.value for error in app.error)
    assert any(button.label == "Close case" for button in app.button)
