import pytest

from src.context.conversation_context import build_conversation_context
from src.schemas.answer import VDRAnswer
from src.schemas.evidence import SourceReference
from src.schemas.evidence_presentation import (
    VerifiedEvidenceMetric,
    VerifiedEvidencePresentation,
    VerifiedEvidenceTable,
)
from src.schemas.quotation import VerifiedQuote
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
        self.code_calls = []
        self.tabs_calls = []
        self.columns_calls = []
        self.metric_calls = []
        self.table_calls = []
        self.events = []

    def chat_message(self, role):
        self.chat_roles.append(role)
        return NullContext()

    def expander(self, label):
        self.expander_labels.append(label)
        self.events.append(("expander", label))
        return NullContext()

    def markdown(self, body):
        self.markdown_calls.append(body)
        self.events.append(("markdown", body))

    def caption(self, body):
        self.caption_calls.append(body)
        self.events.append(("caption", body))

    def text(self, body, **kwargs):
        self.text_calls.append((body, kwargs))
        self.events.append(("text", body))

    def tabs(self, labels, **kwargs):
        self.tabs_calls.append((list(labels), kwargs))
        self.events.append(("tabs", list(labels)))
        return [NullContext() for _ in labels]

    def code(self, body, **kwargs):
        self.code_calls.append((body, kwargs))
        self.events.append(("code", body))

    def columns(self, spec, **kwargs):
        self.columns_calls.append((spec, kwargs))
        self.events.append(("columns", spec))
        count = spec if isinstance(spec, int) else len(spec)
        return [NullContext() for _ in range(count)]

    def metric(self, label, value, **kwargs):
        self.metric_calls.append((label, value, kwargs))
        self.events.append(("metric", (label, value)))

    def table(self, data, **kwargs):
        self.table_calls.append((data, kwargs))
        self.events.append(("table", data))


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


def answer_with_verified_quote() -> VDRAnswer:
    return structured_answer().model_copy(
        update={
            "verified_quotes": [
                VerifiedQuote(
                    file_id="file-A",
                    source_display_name=(
                        "VDR → Finance → Annual Report.pdf"
                    ),
                    text=(
                        "Revenue increased from €38.1 million "
                        "to €42.6 million."
                    ),
                )
            ]
        }
    )


def answer_with_verified_presentations() -> VDRAnswer:
    answer = structured_answer()
    source = answer.sources[0].model_copy(
        update={
            "presentations": [
                VerifiedEvidencePresentation(
                    passage_index=0,
                    metrics=[
                        VerifiedEvidenceMetric(
                            label="Revenue",
                            value="€42.6 million",
                            period="FY2024",
                            unit="EUR",
                            source_text="METRIC_SOURCE_SPAN_INTERNAL",
                        ),
                        VerifiedEvidenceMetric(
                            label="Margin",
                            value="15.7%",
                            source_text="SECOND_METRIC_SOURCE_SPAN_INTERNAL",
                        ),
                    ],
                    tables=[
                        VerifiedEvidenceTable(
                            title="Revenue by year",
                            columns=["Year", "Revenue"],
                            rows=[
                                ["2023", "€38.1 million"],
                                ["2024", "€42.6 million"],
                            ],
                            source_texts=[
                                "TABLE_HEADER_SOURCE_SPAN_INTERNAL",
                                "TABLE_ROW_SOURCE_SPAN_INTERNAL_1",
                                "TABLE_ROW_SOURCE_SPAN_INTERNAL_2",
                            ],
                        )
                    ],
                )
            ]
        }
    )
    return answer.model_copy(update={"sources": [source, answer.sources[1]]})


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
    assert fake_st.events.index(
        (
            "expander",
            "Retrieved evidence — VDR → Finance → Annual Report.pdf",
        )
    ) < fake_st.events.index(
        ("markdown", "- VDR → Legal → Agreement.pdf")
    )
    assert "- VDR → Legal → Agreement.pdf" in fake_st.markdown_calls
    assert fake_st.text_calls == [
        (
            "First ranked passage\nwith Unicode €42.6 million",
            {"width": "stretch"},
        ),
        ("Second ranked passage", {"width": "stretch"}),
    ]
    assert fake_st.code_calls == [
        (
            "First ranked passage\nwith Unicode €42.6 million",
            {"language": None, "wrap_lines": False},
        ),
        (
            "Second ranked passage",
            {"language": None, "wrap_lines": False},
        ),
    ]
    assert fake_st.tabs_calls == [
        (
            ["Readable text", "Raw text"],
            {"default": "Readable text"},
        )
    ]
    assert fake_st.caption_calls == [
        "Formatting cleanup only; document wording and values are unchanged.",
        "Retrieved passage 1",
        "Retrieved passage 2",
        "Retrieved passage 1",
        "Retrieved passage 2",
    ]
    assert fake_st.caption_calls.count(
        "Formatting cleanup only; document wording and values are unchanged."
    ) == 1
    assert fake_st.caption_calls[1:] == [
        "Retrieved passage 1",
        "Retrieved passage 2",
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


def test_verified_presentations_add_default_structured_tab(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_answer(answer_with_verified_presentations())

    assert fake_st.expander_labels == [
        "Retrieved evidence — VDR → Finance → Annual Report.pdf"
    ]
    assert fake_st.tabs_calls == [
        (
            ["Structured view", "Readable text", "Raw text"],
            {"default": "Structured view"},
        )
    ]
    assert fake_st.caption_calls.count(
        "Structured from retrieved evidence; values are source-verified."
    ) == 1
    assert fake_st.caption_calls.count(
        "Formatting cleanup only; document wording and values are unchanged."
    ) == 1


def test_verified_metrics_render_exact_strings_without_calculation_options(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_answer(answer_with_verified_presentations())

    assert fake_st.columns_calls == [(2, {})]
    assert fake_st.metric_calls == [
        ("Revenue — FY2024 — EUR", "€42.6 million", {}),
        ("Margin", "15.7%", {}),
    ]
    assert all(isinstance(value, str) for _, value, _ in fake_st.metric_calls)
    assert all(
        "delta" not in kwargs
        and "chart_data" not in kwargs
        and "chart_type" not in kwargs
        for _, _, kwargs in fake_st.metric_calls
    )


def test_verified_table_renders_exact_ordered_strings_without_index(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_answer(answer_with_verified_presentations())

    assert "Revenue by year" in fake_st.caption_calls
    assert fake_st.table_calls == [
        (
            {
                "Year": ["2023", "2024"],
                "Revenue": ["€38.1 million", "€42.6 million"],
            },
            {"hide_index": True},
        )
    ]
    table_data, _ = fake_st.table_calls[0]
    assert list(table_data) == ["Year", "Revenue"]
    assert all(
        isinstance(cell, str)
        for column in table_data.values()
        for cell in column
    )


def test_structured_view_hides_verification_internals(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_answer(answer_with_verified_presentations())

    rendered = "\n".join(str(value) for _, value in fake_st.events)
    assert "file-A" not in rendered
    assert "METRIC_SOURCE_SPAN_INTERNAL" not in rendered
    assert "SECOND_METRIC_SOURCE_SPAN_INTERNAL" not in rendered
    assert "TABLE_HEADER_SOURCE_SPAN_INTERNAL" not in rendered
    assert "TABLE_ROW_SOURCE_SPAN_INTERNAL" not in rendered
    assert "passage_index" not in rendered
    assert "source_text" not in rendered
    assert "score" not in rendered.lower()
    assert "rejection" not in rendered.lower()
    assert all(
        value not in fake_st.markdown_calls
        for value in (
            "€42.6 million",
            "15.7%",
            "Revenue by year",
            "2023",
            "2024",
        )
    )


def test_empty_presentations_do_not_add_structured_tab(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = structured_answer()
    source = answer.sources[0].model_copy(
        update={
            "presentations": [
                VerifiedEvidencePresentation(passage_index=0)
            ]
        }
    )
    answer = answer.model_copy(
        update={"sources": [source, answer.sources[1]]}
    )

    chat.render_answer(answer)

    assert fake_st.tabs_calls == [
        (
            ["Readable text", "Raw text"],
            {"default": "Readable text"},
        )
    ]
    assert fake_st.columns_calls == []
    assert fake_st.metric_calls == []
    assert fake_st.table_calls == []
    assert (
        "Structured from retrieved evidence; values are source-verified."
        not in fake_st.caption_calls
    )


@pytest.mark.parametrize("component", ["metrics", "tables"])
def test_each_verified_component_type_enables_structured_tab(
    component: str,
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = answer_with_verified_presentations()
    presentation = answer.sources[0].presentations[0]
    presentation = presentation.model_copy(
        update={
            "metrics": presentation.metrics if component == "metrics" else [],
            "tables": presentation.tables if component == "tables" else [],
        }
    )
    source = answer.sources[0].model_copy(
        update={"presentations": [presentation]}
    )
    answer = answer.model_copy(
        update={"sources": [source, answer.sources[1]]}
    )

    chat.render_answer(answer)

    assert fake_st.tabs_calls[0] == (
        ["Structured view", "Readable text", "Raw text"],
        {"default": "Structured view"},
    )


def test_verified_quotes_render_safely_between_answer_and_sources(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = answer_with_verified_quote()

    chat.render_answer(answer)

    answer_event = ("markdown", "Supported answer")
    heading_event = ("markdown", "**Verified quotations**")
    source_event = ("markdown", "**Sources**")
    assert fake_st.events.index(answer_event) < fake_st.events.index(heading_event)
    assert fake_st.events.index(heading_event) < fake_st.events.index(source_event)
    assert (
        "“Revenue increased from €38.1 million to €42.6 million.”",
        {"width": "stretch"},
    ) in fake_st.text_calls
    assert (
        "Source: VDR → Finance → Annual Report.pdf"
        in fake_st.caption_calls
    )
    assert all(
        "Revenue increased from €38.1 million to €42.6 million."
        not in markdown
        for markdown in fake_st.markdown_calls
    )

    rendered = "\n".join(str(value) for _, value in fake_st.events)
    assert "file-A" not in rendered
    assert "score" not in rendered.lower()
    assert "confidence" not in rendered.lower()
    assert fake_st.expander_labels == [
        "Retrieved evidence — VDR → Finance → Annual Report.pdf"
    ]


def test_verified_quotation_section_is_omitted_when_empty(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_answer(structured_answer())

    assert "**Verified quotations**" not in fake_st.markdown_calls


def test_verified_quotations_remain_before_structured_sources(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = answer_with_verified_presentations().model_copy(
        update={
            "verified_quotes": answer_with_verified_quote().verified_quotes
        }
    )

    chat.render_answer(answer)

    quote_heading = ("markdown", "**Verified quotations**")
    source_heading = ("markdown", "**Sources**")
    structured_tabs = (
        "tabs",
        ["Structured view", "Readable text", "Raw text"],
    )
    assert fake_st.events.index(quote_heading) < fake_st.events.index(
        source_heading
    )
    assert fake_st.events.index(source_heading) < fake_st.events.index(
        structured_tabs
    )


@pytest.mark.parametrize(
    ("text", "max_chars", "expected"),
    [
        ("short text", 20, "short text"),
        ("exact text", 10, "exact text"),
        ("  raw text  ", 20, "  raw text  "),
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
    assert [text for text, _ in fake_st.code_calls] == [
        rendered_excerpt,
        "Second passage",
    ]
    assert all("Showing" not in caption for caption in fake_st.caption_calls)


def test_readable_and_raw_views_share_the_same_bounded_excerpt(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    raw_passage = "\r\n  Heading  \r\n\r\n\r\nValue\t€42.6m  "
    answer = VDRAnswer(
        answer="Supported answer",
        source_files=["Report.pdf"],
        sources=[
            SourceReference(
                file_id="file-A",
                display_name="Report.pdf",
                evidence=[raw_passage],
            )
        ],
    )

    chat.render_answer(answer)

    raw_excerpt = chat.truncate_evidence_excerpt(raw_passage)
    assert fake_st.code_calls == [
        (raw_excerpt, {"language": None, "wrap_lines": False})
    ]
    assert fake_st.text_calls == [
        (
            chat.clean_evidence_text(raw_excerpt),
            {"width": "stretch"},
        )
    ]
    assert raw_excerpt == raw_passage
    assert raw_passage not in fake_st.markdown_calls
    assert chat.clean_evidence_text(raw_excerpt) not in fake_st.markdown_calls


def test_empty_readable_historical_passage_remains_available_as_raw(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = VDRAnswer(
        answer="Supported answer",
        source_files=["Report.pdf"],
        sources=[
            SourceReference(
                file_id="file-A",
                display_name="Report.pdf",
                evidence=[" \t\r\n "],
            )
        ],
    )

    chat.render_answer(answer)

    assert fake_st.text_calls == []
    assert fake_st.code_calls == [
        (" \t\r\n ", {"language": None, "wrap_lines": False})
    ]
    assert fake_st.caption_calls == [
        "Formatting cleanup only; document wording and values are unchanged.",
        "Retrieved passage 1",
    ]


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
    assert fake_st.tabs_calls == []
    assert "- VDR → Legal → Agreement.pdf" in fake_st.markdown_calls


def test_assistant_message_serializes_complete_answer() -> None:
    answer = structured_answer()

    message = chat.build_assistant_message(answer)

    assert message["role"] == "assistant"
    assert message["content"] == "Supported answer"
    assert VDRAnswer.model_validate(message["vdr_answer"]) == answer
    assert "score" not in message["vdr_answer"]["sources"][0]


def test_verified_quotes_survive_serialized_history_replay(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    message = chat.build_assistant_message(answer_with_verified_quote())

    chat.render_chat_history([message])

    restored = VDRAnswer.model_validate(message["vdr_answer"])
    assert restored.verified_quotes[0].file_id == "file-A"
    assert (
        "“Revenue increased from €38.1 million to €42.6 million.”",
        {"width": "stretch"},
    ) in fake_st.text_calls
    assert "**Verified quotations**" in fake_st.markdown_calls


def test_verified_presentations_survive_serialized_history_replay(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = answer_with_verified_presentations()
    message = chat.build_assistant_message(answer)

    chat.render_chat_history([message])

    restored = VDRAnswer.model_validate(message["vdr_answer"])
    assert restored == answer
    assert fake_st.tabs_calls[0] == (
        ["Structured view", "Readable text", "Raw text"],
        {"default": "Structured view"},
    )
    assert fake_st.metric_calls == [
        ("Revenue — FY2024 — EUR", "€42.6 million", {}),
        ("Margin", "15.7%", {}),
    ]
    assert fake_st.table_calls[0][0] == {
        "Year": ["2023", "2024"],
        "Revenue": ["€38.1 million", "€42.6 million"],
    }


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
    assert fake_st.code_calls[0] == (
        "First ranked passage\nwith Unicode €42.6 million",
        {"language": None, "wrap_lines": False},
    )


def test_raw_evidence_survives_serialized_history_replay_exactly(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    raw_passage = "\t Leading\r\nEvidence €42.6m\u2003 "
    answer = VDRAnswer(
        answer="Supported answer",
        source_files=["Report.pdf"],
        sources=[
            SourceReference(
                file_id="file-A",
                display_name="Report.pdf",
                evidence=[raw_passage],
            )
        ],
    )

    chat.render_chat_history([chat.build_assistant_message(answer)])

    assert fake_st.code_calls == [
        (
            raw_passage,
            {"language": None, "wrap_lines": False},
        )
    ]


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
    assert answer.verified_quotes == []


def test_old_structured_payload_without_verified_quotes_renders(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    payload = {
        "answer": "Old structured answer",
        "source_files": ["Report.pdf"],
        "sources": [],
        "status": "success",
        "workflow": "qa",
    }

    chat.render_chat_history(
        [
            {
                "role": "assistant",
                "content": "Old structured answer",
                "vdr_answer": payload,
            }
        ]
    )

    assert "Old structured answer" in fake_st.markdown_calls
    assert "**Verified quotations**" not in fake_st.markdown_calls
    assert "- Report.pdf" in fake_st.markdown_calls


def test_legacy_quotes_are_not_rendered(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = VDRAnswer(
        answer="Legacy structured answer",
        source_files=["Report.pdf"],
        quotes=["Unverified legacy quote"],
    )

    chat.render_answer(answer)

    rendered = "\n".join(str(value) for _, value in fake_st.events)
    assert "Unverified legacy quote" not in rendered
    assert "Quotes" not in fake_st.expander_labels


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


def test_converted_parallel_table_reuses_structured_history_renderer(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    horizontal = (
        "Period 2024A 2025E\n"
        "Revenue EURm 10 12"
    )
    table = VerifiedEvidenceTable(
        title=None,
        columns=["Period", "Revenue — EURm"],
        rows=[["2024A", "10"], ["2025E", "12"]],
        source_texts=horizontal.splitlines(),
    )
    answer = VDRAnswer(
        answer="Supported answer",
        source_files=["Report.pdf"],
        sources=[
            SourceReference(
                file_id="file-A",
                display_name="Report.pdf",
                evidence=[horizontal],
                presentations=[
                    VerifiedEvidencePresentation(
                        passage_index=0,
                        tables=[table],
                    )
                ],
            )
        ],
    )

    chat.render_chat_history([chat.build_assistant_message(answer)])

    assert fake_st.tabs_calls == [
        (
            ["Structured view", "Readable text", "Raw text"],
            {"default": "Structured view"},
        )
    ]
    assert fake_st.table_calls == [
        (
            {
                "Period": ["2024A", "2025E"],
                "Revenue — EURm": ["10", "12"],
            },
            {"hide_index": True},
        )
    ]
    rendered = "\n".join(str(value) for _, value in fake_st.events)
    assert "file-A" not in rendered
    assert "source_span" not in rendered
    assert "score" not in rendered
    assert "chart" not in rendered.lower()
