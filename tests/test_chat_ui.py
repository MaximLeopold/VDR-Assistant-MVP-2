import pytest

from src.context.conversation_context import build_conversation_context
from src.schemas.answer import VDRAnswer
from src.schemas.evidence import SourceReference
from src.ui import chat, source_panel


class NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeStreamlit:
    def __init__(self):
        self.chat_roles = []
        self.expander_labels = []
        self.markdown_calls = []
        self.caption_calls = []
        self.text_calls = []

    def chat_message(self, role):
        self.chat_roles.append(role)
        return NullContext()

    def expander(self, label):
        self.expander_labels.append(label)
        return NullContext()

    def markdown(self, body):
        self.markdown_calls.append(body)

    def caption(self, body):
        self.caption_calls.append(body)

    def text(self, body, **kwargs):
        self.text_calls.append((body, kwargs))


def structured_answer() -> VDRAnswer:
    return VDRAnswer(
        answer="Supported answer",
        source_files=[
            "VDR → Finance → Annual Report.pdf",
            "VDR → Legal → Agreement.pdf",
        ],
        sources=[
            SourceReference(
                file_id="file-A",
                display_name="VDR → Finance → Annual Report.pdf",
                evidence=[
                    "First ranked passage\nwith Unicode €42.6 million",
                    "Second ranked passage",
                    "Third passage",
                    "Fourth passage",
                ],
            ),
            SourceReference(
                file_id="file-B",
                display_name="VDR → Legal → Agreement.pdf",
            ),
        ],
        status="success",
    )


def test_render_answer_uses_safe_source_level_evidence_expander(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_answer(structured_answer())

    assert fake_st.chat_roles == ["assistant"]
    assert fake_st.expander_labels == [
        "Retrieved evidence — VDR → Finance → Annual Report.pdf"
    ]
    assert "- VDR → Legal → Agreement.pdf" in fake_st.markdown_calls
    assert fake_st.text_calls == [
        (
            "First ranked passage\nwith Unicode €42.6 million",
            {"width": "stretch"},
        ),
        ("Second ranked passage", {"width": "stretch"}),
    ]
    assert fake_st.caption_calls == [
        "Retrieved passage 1",
        "Retrieved passage 2",
    ]
    assert all("Showing" not in caption for caption in fake_st.caption_calls)
    assert all("of 4" not in caption for caption in fake_st.caption_calls)

    rendered_control_text = "\n".join(
        fake_st.markdown_calls
        + fake_st.caption_calls
        + fake_st.expander_labels
    )
    assert "file-A" not in rendered_control_text
    assert "0.8" not in rendered_control_text
    assert all(
        passage not in fake_st.markdown_calls
        for passage, _ in fake_st.text_calls
    )
    assert structured_answer().sources[0].evidence[2] == "Third passage"


@pytest.mark.parametrize(
    ("text", "max_chars", "expected"),
    [
        ("short text", 20, "short text"),
        ("exact text", 10, "exact text"),
        ("  trimmed text  ", 20, "trimmed text"),
        ("alpha beta gamma", 10, "alpha beta…"),
        ("abcdefghijk", 5, "abcde…"),
        ("äöüß漢字abcdef", 6, "äöüß漢字…"),
        ("first\nsecond third", 13, "first\nsecond…"),
    ],
)
def test_truncate_evidence_excerpt(
    text: str,
    max_chars: int,
    expected: str,
) -> None:
    excerpt = chat.truncate_evidence_excerpt(text, max_chars=max_chars)

    assert excerpt == expected
    assert len(excerpt) <= max_chars + 1


def test_long_excerpt_uses_exactly_one_ellipsis() -> None:
    excerpt = chat.truncate_evidence_excerpt("one two three four", 13)

    assert excerpt == "one two three…"
    assert excerpt.count("…") == 1


def test_default_limit_leaves_exactly_1200_characters_unchanged() -> None:
    text = "x" * chat.MAX_VISIBLE_EVIDENCE_CHARS

    assert chat.truncate_evidence_excerpt(text) == text


def test_negative_excerpt_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        chat.truncate_evidence_excerpt("passage", max_chars=-1)


def test_ui_truncates_only_rendered_excerpt_and_preserves_stored_text(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    full_passage = ("Substantial retrieved context " * 60).strip()
    answer = VDRAnswer(
        answer="Supported answer",
        source_files=["VDR → Finance → Annual Report.pdf"],
        sources=[
            SourceReference(
                file_id="file-A",
                display_name="VDR → Finance → Annual Report.pdf",
                evidence=[full_passage, "Second passage", "Third passage"],
            )
        ],
    )

    chat.render_answer(answer)

    rendered_excerpt = fake_st.text_calls[0][0]
    assert rendered_excerpt == chat.truncate_evidence_excerpt(full_passage)
    assert rendered_excerpt.endswith("…")
    assert len(rendered_excerpt) <= chat.MAX_VISIBLE_EVIDENCE_CHARS + 1
    assert answer.sources[0].evidence[0] == full_passage
    assert [text for text, _ in fake_st.text_calls] == [
        rendered_excerpt,
        "Second passage",
    ]
    assert "Third passage" not in [text for text, _ in fake_st.text_calls]
    assert all("Showing" not in caption for caption in fake_st.caption_calls)


def test_source_without_evidence_has_no_evidence_expander(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = VDRAnswer(
        answer="Supported answer",
        source_files=["VDR → Legal → Agreement.pdf"],
        sources=[
            SourceReference(
                file_id="file-B",
                display_name="VDR → Legal → Agreement.pdf",
            )
        ],
    )

    chat.render_answer(answer)

    assert fake_st.expander_labels == []
    assert "- VDR → Legal → Agreement.pdf" in fake_st.markdown_calls


def test_assistant_message_serializes_complete_answer() -> None:
    answer = structured_answer()

    message = chat.build_assistant_message(answer)

    assert message["role"] == "assistant"
    assert message["content"] == "Supported answer"
    assert VDRAnswer.model_validate(message["vdr_answer"]) == answer
    assert "score" not in message["vdr_answer"]["sources"][0]


def test_structured_answer_replays_after_rerun(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    message = chat.build_assistant_message(structured_answer())

    chat.render_chat_history([message])

    assert fake_st.chat_roles == ["assistant"]
    assert fake_st.text_calls[0] == (
        "First ranked passage\nwith Unicode €42.6 million",
        {"width": "stretch"},
    )


def test_legacy_assistant_message_still_renders(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_chat_history(
        [{"role": "assistant", "content": "Legacy answer"}]
    )

    assert fake_st.markdown_calls == ["Legacy answer"]


def test_legacy_answer_payload_without_sources_validates() -> None:
    answer = VDRAnswer.model_validate(
        {
            "answer": "Legacy answer",
            "source_files": ["Report.pdf"],
            "status": "success",
            "workflow": "qa",
        }
    )

    assert answer.sources == []


def test_conversation_context_ignores_structured_payload() -> None:
    message = chat.build_assistant_message(structured_answer())

    assert build_conversation_context([message]) == (
        "ASSISTANT: Supported answer"
    )


class FakeSidebar:
    def __init__(self):
        self.info_calls = []

    def subheader(self, body):
        pass

    def caption(self, body):
        pass

    def info(self, body):
        self.info_calls.append(body)

    def warning(self, body):
        pass


def test_sidebar_remains_citation_only(monkeypatch) -> None:
    sidebar = FakeSidebar()
    monkeypatch.setattr(source_panel.st, "sidebar", sidebar)

    source_panel.render_source_panel(structured_answer())

    rendered = "\n".join(sidebar.info_calls)
    assert "VDR → Finance → Annual Report.pdf" in rendered
    assert "VDR → Legal → Agreement.pdf" in rendered
    assert "First ranked passage" not in rendered
    assert "file-A" not in rendered
