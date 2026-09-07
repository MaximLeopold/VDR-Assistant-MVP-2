from contextlib import contextmanager

import pytest

from src.context.conversation_context import build_conversation_context
from src.schemas.answer import VDRAnswer
from src.schemas.evidence import SourceReference, VerifiedEvidenceExcerpt
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
        self.expander_calls = []
        self.markdown_calls = []
        self.caption_calls = []
        self.text_calls = []
        self.code_calls = []
        self.tabs_calls = []
        self.columns_calls = []
        self.metric_calls = []
        self.table_calls = []
        self.events = []
        self.html_calls = []

    def html(self, body):
        self.html_calls.append(body)

    @contextmanager
    def container(self, **kwargs):
        self.events.append(("container_enter", kwargs))
        yield
        self.events.append(("container_exit", kwargs))

    def chat_message(self, role):
        self.chat_roles.append(role)
        return NullContext()

    def expander(self, label, **kwargs):
        self.expander_labels.append(label)
        self.expander_calls.append((label, kwargs))
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
                evidence_selection_status="completed",
                selected_evidence=[
                    VerifiedEvidenceExcerpt(
                        role="best_support", passage_index=0,
                        text="First ranked passage\nwith Unicode €42.6 million",
                    ),
                    VerifiedEvidenceExcerpt(
                        role="additional_context", passage_index=1,
                        text="Second ranked passage",
                    ),
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


@pytest.mark.parametrize(
    "answer",
    [
        "| Metric | Value |\n| :--- | ---: |\n| Revenue | 10 |",
        "Metric | Value\n--- | :---:\nRevenue | 10",
    ],
)
def test_markdown_table_detection_accepts_header_and_delimiter(
    answer: str,
) -> None:
    assert chat.answer_contains_markdown_table(answer) is True


@pytest.mark.parametrize(
    "answer",
    [
        "Ordinary prose containing A | B in one sentence.",
        "Header | Value",
        "Header | Value\nnot a delimiter | ---",
        "--- | ---\n--- | ---",
        "<div>Header | Value</div>\n--- | ---",
        "```markdown\n| Header | Value |\n| --- | --- |\n| A | B |\n```",
        "~~~\nHeader | Value\n--- | ---\nA | B\n~~~",
    ],
)
def test_markdown_table_detection_rejects_non_tables_and_fenced_code(
    answer: str,
) -> None:
    assert chat.answer_contains_markdown_table(answer) is False


def test_successful_prose_answer_discloses_synthesis(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_answer(structured_answer())

    assert chat.SYNTHESIZED_ANSWER_CAPTION in fake_st.caption_calls
    assert chat.UNVERIFIED_TABLE_CAPTION not in fake_st.caption_calls
    assert chat.VERIFIED_TABLE_AVAILABLE_CAPTION not in fake_st.caption_calls


def test_unverified_answer_table_gets_cell_verification_warning(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = structured_answer().model_copy(
        update={
            "answer": "Metric | Value\n--- | ---:\nRevenue | 10",
        }
    )

    chat.render_answer(answer)

    assert chat.SYNTHESIZED_ANSWER_CAPTION in fake_st.caption_calls
    assert chat.UNVERIFIED_TABLE_CAPTION in fake_st.caption_calls
    assert chat.VERIFIED_TABLE_AVAILABLE_CAPTION not in fake_st.caption_calls


def test_answer_table_with_verified_source_table_uses_conservative_wording(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = answer_with_verified_presentations().model_copy(
        update={
            "answer": "Metric | Value\n:--- | ---:\nRevenue | 10",
        }
    )

    chat.render_answer(answer)

    assert chat.VERIFIED_TABLE_AVAILABLE_CAPTION in fake_st.caption_calls
    assert chat.UNVERIFIED_TABLE_CAPTION not in fake_st.caption_calls
    assert "match" not in chat.VERIFIED_TABLE_AVAILABLE_CAPTION.lower()
    assert "answer table" not in chat.VERIFIED_TABLE_AVAILABLE_CAPTION.lower()


@pytest.mark.parametrize("status", ["not_found", "error"])
def test_fallback_answers_do_not_show_trust_disclosures(
    status: str,
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = VDRAnswer(
        answer="I can not find this information in the VDR documents",
        status=status,
    )

    chat.render_answer(answer)

    assert fake_st.caption_calls == []


def test_success_status_without_cited_sources_has_no_synthesis_caption(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_answer(VDRAnswer(answer="Uncited answer", status="success"))

    assert fake_st.caption_calls == []


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
    assert "- VDR → Legal → Agreement.pdf" not in fake_st.markdown_calls
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
            ["Evidence", "Original retrieved passages"],
            {"default": "Evidence"},
        ),
    ]
    assert fake_st.caption_calls == [
        chat.SYNTHESIZED_ANSWER_CAPTION,
        "Additional context 1",
        "Best supporting passage",
        "Additional retrieved context 1",
    ]
    assert chat.FORMATTED_SOURCE_EXCERPTS_DISCLOSURE in fake_st.markdown_calls
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


def test_verified_presentations_add_structured_tab_with_evidence_default(
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
            ["Evidence", "Structured", "Original retrieved passages"],
            {"default": "Evidence"},
        ),
    ]
    assert fake_st.caption_calls.count(
        "Structured from retrieved evidence; values are source-verified."
    ) == 1
    assert "Readable text" not in str(fake_st.tabs_calls)


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
            ["Evidence", "Original retrieved passages"],
            {"default": "Evidence"},
        ),
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
        ["Evidence", "Structured", "Original retrieved passages"],
        {"default": "Evidence"},
    )


def test_verified_quotes_render_safely_between_answer_and_sources(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = answer_with_verified_quote()

    chat.render_answer(answer)

    answer_event = ("markdown", "Supported answer")
    heading_event = ("expander", "Verified quotations")
    source_event = ("markdown", "**Evidence**")
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
        "Verified quotations",
        "Retrieved evidence — VDR → Finance → Annual Report.pdf"
    ]
    assert fake_st.expander_calls[0] == ("Verified quotations", {})


def test_verified_quotation_section_is_omitted_when_empty(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_answer(structured_answer())

    assert "Verified quotations" not in fake_st.expander_labels


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

    quote_heading = ("expander", "Verified quotations")
    source_heading = ("markdown", "**Evidence**")
    structured_tabs = (
        "tabs",
        ["Evidence", "Structured", "Original retrieved passages"],
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


@pytest.mark.parametrize("length", [20, 1199, 1200])
def test_boundary_truncation_leaves_short_and_target_text_complete(
    length: int,
) -> None:
    passage = "x" * length

    assert chat.truncate_evidence_at_boundary(passage) == (passage, False)


def test_boundary_truncation_uses_nearby_sentence_and_preserves_unicode() -> None:
    passage = "ü" * 1190 + " continuation finishes here. " + "tail " * 200

    excerpt, was_truncated = chat.truncate_evidence_at_boundary(passage)

    assert was_truncated is True
    assert excerpt == "ü" * 1190 + " continuation finishes here.…"
    assert excerpt[:-1] == passage[: len(excerpt) - 1]
    assert len(excerpt) <= chat.EVIDENCE_HARD_MAX_CHARS


@pytest.mark.parametrize("marker", ["-", "1)"])
def test_boundary_truncation_completes_current_list_item(marker: str) -> None:
    prefix = "Context " * 145
    current_item = f"\n{marker} " + "qualitative evidence " * 18 + "ends here."
    passage = prefix + current_item + "\n- Later item " + "z" * 900

    excerpt, was_truncated = chat.truncate_evidence_at_boundary(passage)

    assert was_truncated is True
    assert current_item.strip() in excerpt
    assert "Later item" not in excerpt
    assert excerpt.endswith("…")
    assert len(excerpt) <= chat.EVIDENCE_HARD_MAX_CHARS


def test_boundary_truncation_completes_nearby_paragraph() -> None:
    passage = (
        "x" * 1190
        + " paragraph conclusion"
        + "\n\n"
        + "A later paragraph "
        + "y" * 700
    )

    excerpt, was_truncated = chat.truncate_evidence_at_boundary(passage)

    assert was_truncated is True
    assert excerpt == "x" * 1190 + " paragraph conclusion…"


@pytest.mark.parametrize(
    "passage",
    [
        "unbroken" * 500,
        "x" * 1799 + "." + "tail" * 100,
    ],
)
def test_boundary_truncation_is_hard_bounded_and_visibly_marked(
    passage: str,
) -> None:

    excerpt, was_truncated = chat.truncate_evidence_at_boundary(passage)

    assert was_truncated is True
    assert excerpt.endswith("…")
    assert excerpt.count("…") == 1
    assert len(excerpt) == chat.EVIDENCE_HARD_MAX_CHARS
    assert excerpt[:-1] == passage[: len(excerpt) - 1]


def test_single_passage_renders_directly_without_inner_navigation(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    source = SourceReference(
        file_id="file-A",
        display_name="Report.pdf",
        evidence=["Only passage"],
    )

    chat.render_evidence_tab(source)

    assert fake_st.tabs_calls == []
    assert fake_st.caption_calls == [
        chat.BEST_SUPPORT_LABEL,
    ]
    assert fake_st.markdown_calls == []
    assert fake_st.text_calls == [
        ("Only passage", {"width": "stretch"})
    ]


def test_two_passages_use_ranked_inner_tabs_and_ignore_later_passages(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    source = SourceReference(
        file_id="file-secret",
        display_name="Report.pdf",
        evidence=["Best", "Second", "Third"],
    )

    chat.render_evidence_tab(source)

    assert fake_st.tabs_calls == [
        (
            ["Best supporting passage", "Additional retrieved context"],
            {"default": "Best supporting passage"},
        )
    ]
    assert fake_st.caption_calls == []
    assert chat.FORMATTED_SOURCE_EXCERPTS_DISCLOSURE not in fake_st.markdown_calls
    assert [text for text, _ in fake_st.text_calls] == ["Best", "Second"]
    rendered = "\n".join(str(value) for _, value in fake_st.events)
    assert "Third" not in rendered
    assert "file-secret" not in rendered
    assert "passage_index" not in rendered
    assert "score" not in rendered.lower()


def test_truncation_caption_appears_only_for_truncated_evidence(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_evidence_passage("short", label="Short")
    chat.render_evidence_passage("x" * 3000, label="Long")

    assert fake_st.caption_calls.count(chat.EVIDENCE_TRUNCATION_CAPTION) == 1
    assert len(fake_st.text_calls[-1][0]) <= chat.EVIDENCE_HARD_MAX_CHARS


def test_raw_retrieval_is_complete_exact_and_limited_to_two_passages(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    first = "\r\n  Heading  \r\n" + "A" * 1500 + "  "
    second = "soft wrapped line\ncontinues exactly\t€42.6m  "
    source = SourceReference(
        file_id="file-A",
        display_name="Report.pdf",
        evidence=[first, second, "Third passage"],
    )

    chat.render_raw_retrieval(source)

    assert fake_st.code_calls == [
        (first, {"language": None, "wrap_lines": False}),
        (second, {"language": None, "wrap_lines": False}),
    ]
    assert fake_st.caption_calls == ["Raw passage 1", "Raw passage 2"]
    assert len(fake_st.code_calls[0][0]) > chat.MAX_VISIBLE_EVIDENCE_CHARS
    assert all(not text.endswith("…") for text, _ in fake_st.code_calls)
    assert "Third passage" not in [text for text, _ in fake_st.code_calls]


def test_completed_selection_renders_best_without_empty_additional(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    source = SourceReference(
        file_id="file-A",
        display_name="Report.pdf",
        evidence=["Full raw passage"],
        evidence_selection_status="completed",
        selected_evidence=[
            VerifiedEvidenceExcerpt(
                role="best_support",
                passage_index=0,
                text="Selected support",
            )
        ],
    )

    chat.render_evidence_tab(source)

    assert fake_st.tabs_calls == []
    assert [text for text, _ in fake_st.text_calls] == ["Selected support"]
    assert chat.BEST_SUPPORT_LABEL in fake_st.markdown_calls
    assert chat.ADDITIONAL_CONTEXT_LABEL not in fake_st.markdown_calls
    assert fake_st.caption_calls == []
    assert "Full raw passage" not in [text for text, _ in fake_st.text_calls]


def test_completed_empty_selection_omits_empty_role_statements(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    source = SourceReference(
        display_name="Report.pdf",
        evidence=["Raw but not selected"],
        evidence_selection_status="completed",
    )

    chat.render_evidence_tab(source)

    assert fake_st.caption_calls == []
    assert fake_st.markdown_calls == []
    assert fake_st.text_calls == []


def test_completed_source_without_raw_evidence_has_no_central_expander(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = VDRAnswer(
        answer="Supported answer",
        source_files=["No retrieval.pdf"],
        sources=[
            SourceReference(
                display_name="No retrieval.pdf",
                evidence_selection_status="completed",
            )
        ],
    )

    chat.render_answer(answer)

    assert fake_st.expander_labels == []
    assert fake_st.tabs_calls == []
    assert fake_st.markdown_calls == ["Supported answer"]


def test_completed_raw_view_maps_roles_to_full_passages_once(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    source = SourceReference(
        display_name="Report.pdf",
        evidence=["Unselected raw", "Selected raw one", "Selected raw two"],
        evidence_selection_status="completed",
        selected_evidence=[
            VerifiedEvidenceExcerpt(
                role="best_support", passage_index=1, text="Selected"
            ),
            VerifiedEvidenceExcerpt(
                role="additional_context", passage_index=1, text="raw one"
            ),
            VerifiedEvidenceExcerpt(
                role="additional_context", passage_index=2, text="raw two"
            ),
        ],
    )

    chat.render_raw_retrieval(source)

    assert fake_st.code_calls == [
        ("Selected raw one", {"language": None, "wrap_lines": False}),
        ("Selected raw two", {"language": None, "wrap_lines": False}),
    ]
    assert fake_st.caption_calls == [
        "Best supporting passage; Additional retrieved context 1",
        "Additional retrieved context 2",
    ]
    assert "Unselected raw" not in [text for text, _ in fake_st.code_calls]


def test_completed_raw_view_never_substitutes_for_invalid_index(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    source = SourceReference(
        display_name="Report.pdf",
        evidence=["Must not be substituted"],
        evidence_selection_status="completed",
        selected_evidence=[
            VerifiedEvidenceExcerpt(
                role="best_support", passage_index=9, text="Selected"
            )
        ],
    )

    chat.render_raw_retrieval(source)

    assert fake_st.code_calls == []
    assert fake_st.caption_calls == [
        "No selected raw passage is available for this source."
    ]


@pytest.mark.parametrize(
    "passage",
    [
        "- Revenue grew 10%\n- Margin held at 15%",
        "* First\n  continuation\n* Second",
        "- Multiline item\n  first\n  second\n  third\n  fourth\n  fifth",
        "• First\n  ◦ Nested\n• Second",
        "– First\n— Second",
        "1. First\n2) Second",
        "a. First\n  b) Nested\nc. Third",
    ],
)
def test_qualitative_lists_preserve_markers_indentation_and_lines(
    passage: str,
) -> None:
    assert chat.reflow_clear_soft_wraps(passage) == passage
    assert chat.is_table_like_evidence(passage) is False
    assert chat.is_severely_fragmented(passage) is False


def test_conservative_soft_wrap_reflow_joins_only_lowercase_prose() -> None:
    passage = (
        "Customer retention remained stable across the\n"
        "reporting period despite slower new-logo growth."
    )

    assert chat.reflow_clear_soft_wraps(passage) == (
        "Customer retention remained stable across the reporting period "
        "despite slower new-logo growth."
    )


@pytest.mark.parametrize(
    "passage",
    [
        "Expansion\ninto\nAdjacent\nVerticals\nExisting\nPharma\nCustomer\nGrowth",
        "Revenue remained stable through 2024.\nnext sentence stays separate.",
        "Revenue remained stable across the\n\nreporting period.",
        "Revenue remained stable across the\n- reporting period",
        "Revenue remained stable across the\n2024\nreporting period",
        "Already readable prose remains unchanged.",
    ],
)
def test_conservative_reflow_preserves_ambiguous_or_separated_lines(
    passage: str,
) -> None:
    assert chat.reflow_clear_soft_wraps(passage) == passage


@pytest.mark.parametrize(
    "passage",
    [
        "FY2021\nFY2022\nFY2023\nFY2024",
        "2022\n10%\n2023\n11%\n2024\n12%",
        "Revenue\n100\nEBITDA\n50\nMargin\n20%",
    ],
)
def test_period_and_value_fragments_are_recognized_conservatively(
    passage: str,
) -> None:
    assert chat.is_table_like_evidence(passage) is True


def test_ambiguous_one_word_lines_render_preformatted_with_notice(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    passage = (
        "Expansion\ninto\nAdjacent\nVerticals\nExisting\nPharma\n"
        "Customer\nGrowth"
    )

    chat.render_evidence_passage(passage, label="Best supporting passage")

    assert fake_st.caption_calls == [
        "Best supporting passage",
        chat.FRAGMENTED_LAYOUT_NOTICE,
    ]
    assert fake_st.code_calls == [
        (passage, {"language": None, "wrap_lines": True})
    ]
    assert fake_st.text_calls == []
    assert fake_st.table_calls == []


def test_empty_historical_passage_is_stored_but_has_no_central_expander(
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
    assert fake_st.code_calls == []
    assert fake_st.expander_labels == []
    assert answer.sources[0].evidence == [" \t\r\n "]
    assert fake_st.caption_calls == [chat.SYNTHESIZED_ANSWER_CAPTION]


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
    assert "- VDR → Legal → Agreement.pdf" not in fake_st.markdown_calls


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
    assert "Verified quotations" in fake_st.expander_labels


def test_three_same_source_quotes_round_trip_in_collapsed_history_expander(
    monkeypatch,
) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    quotes = [
        VerifiedQuote(
            file_id="file-A",
            source_display_name="VDR → Finance → Annual Report.pdf",
            text=f"Distinct verified quotation number {index} is preserved.",
        )
        for index in range(1, 4)
    ]
    answer = structured_answer().model_copy(
        update={"verified_quotes": quotes}
    )
    message = chat.build_assistant_message(answer)

    chat.render_chat_history([message])

    restored = VDRAnswer.model_validate(message["vdr_answer"])
    assert restored.verified_quotes == quotes
    assert fake_st.expander_calls[0] == ("Verified quotations", {})
    assert [text for text, _ in fake_st.text_calls[:3]] == [
        f"“{quote.text}”" for quote in quotes
    ]
    assert fake_st.caption_calls.count(
        "Source: VDR → Finance → Annual Report.pdf"
    ) == 3


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
        ["Evidence", "Structured", "Original retrieved passages"],
        {"default": "Evidence"},
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
                evidence_selection_status="completed",
                selected_evidence=[VerifiedEvidenceExcerpt(
                    role="best_support", passage_index=0, text="Evidence €42.6m",
                )],
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


def test_selected_evidence_and_raw_mapping_survive_history_replay(
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
                evidence=["Raw zero", "Full raw selected passage"],
                evidence_selection_status="completed",
                selected_evidence=[
                    VerifiedEvidenceExcerpt(
                        role="best_support",
                        passage_index=1,
                        text="selected passage",
                    )
                ],
            )
        ],
    )

    chat.render_chat_history([chat.build_assistant_message(answer)])

    assert ("selected passage", {"width": "stretch"}) in fake_st.text_calls
    assert fake_st.code_calls == [
        (
            "Full raw selected passage",
            {"language": None, "wrap_lines": False},
        )
    ]
    assert "Raw zero" not in [text for text, _ in fake_st.code_calls]


def test_legacy_assistant_message_still_renders(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_chat_history(
        [{"role": "assistant", "content": "Legacy answer"}]
    )

    assert fake_st.markdown_calls == ["Legacy answer"]
    assert fake_st.caption_calls == []


def test_history_replay_reproduces_answer_table_disclosures(monkeypatch) -> None:
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    answer = structured_answer().model_copy(
        update={"answer": "Metric | Value\n--- | ---\nRevenue | 10"}
    )

    chat.render_chat_history([chat.build_assistant_message(answer)])

    assert chat.SYNTHESIZED_ANSWER_CAPTION in fake_st.caption_calls
    assert chat.UNVERIFIED_TABLE_CAPTION in fake_st.caption_calls


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
    assert "Verified quotations" not in fake_st.expander_labels
    assert "- Report.pdf" not in fake_st.markdown_calls


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


@pytest.mark.parametrize("replay", [False, True])
@pytest.mark.parametrize("empty_status", ["legacy", "completed"])
def test_mixed_sources_keep_all_citations_but_only_useful_central_evidence(
    monkeypatch, replay, empty_status,
) -> None:
    fake_st = FakeStreamlit()
    sidebar = FakeSidebar()
    monkeypatch.setattr(chat, "st", fake_st)
    monkeypatch.setattr(source_panel.st, "sidebar", sidebar)

    def fail_api(*args, **kwargs):
        pytest.fail("Rendering and replay must not create an OpenAI client")

    monkeypatch.setattr("openai.OpenAI.__init__", fail_api)
    best = structured_answer().sources[0]
    additional = SourceReference(
        file_id="file-context", display_name="Context.pdf",
        evidence=["Complementary context."],
        evidence_selection_status="completed",
        selected_evidence=[VerifiedEvidenceExcerpt(
            role="additional_context", passage_index=0,
            text="Complementary context.",
        )],
    )
    structured = answer_with_verified_presentations().sources[0].model_copy(update={
        "file_id": "file-structured", "display_name": "Figures.pdf",
        "selected_evidence": [],
    })
    empty = SourceReference(
        file_id="file-empty", display_name="Empty.pdf",
        evidence=["Unselected raw passage"],
        evidence_selection_status=empty_status,
        presentations=[VerifiedEvidencePresentation(passage_index=0)],
    )
    sources = [best, empty, additional, structured]
    answer = VDRAnswer(
        answer="Supported answer", sources=sources,
        source_files=[source.display_name for source in sources],
    )
    original = answer.model_dump(mode="json")

    if replay:
        chat.render_chat_history([chat.build_assistant_message(answer)])
    else:
        chat.render_answer(answer)
    source_panel.render_source_panel(answer)

    assert fake_st.expander_labels == [
        f"Retrieved evidence — {source.display_name}"
        for source in [best, additional, structured]
    ]
    assert sidebar.info_calls == [f"📄 {name}" for name in answer.source_files]
    assert ("Complementary context.", {"width": "stretch"}) in fake_st.text_calls
    assert fake_st.metric_calls
    assert fake_st.table_calls
    assert "Unselected raw passage" not in str(fake_st.events)
    assert answer.model_dump(mode="json") == original
    assert fake_st.markdown_calls.count(chat.FORMATTED_SOURCE_EXCERPTS_DISCLOSURE) == 1
    disclosure_index = fake_st.events.index(
        ("markdown", chat.FORMATTED_SOURCE_EXCERPTS_DISCLOSURE)
    )
    assert fake_st.events.index(("markdown", "**Evidence**")) < disclosure_index
    assert disclosure_index < fake_st.events.index(
        ("expander", fake_st.expander_labels[0])
    )


def test_additional_only_has_no_missing_best_state_and_preserves_raw_mapping(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    raw = "Prefix. First context. Second context. Suffix."
    source = SourceReference(
        file_id="file-context", display_name="Context.pdf", evidence=[raw],
        evidence_selection_status="completed",
        selected_evidence=[
            VerifiedEvidenceExcerpt(role="additional_context", passage_index=0, text=text)
            for text in ["First context.", "Second context."]
        ],
    )

    chat.render_evidence_tab(source)
    chat.render_raw_retrieval(source)

    assert chat.ADDITIONAL_CONTEXT_LABEL in fake_st.markdown_calls
    assert chat.BEST_SUPPORT_LABEL not in fake_st.markdown_calls
    assert [text for text, _ in fake_st.text_calls] == ["First context.", "Second context."]
    assert fake_st.code_calls == [(raw, {"language": None, "wrap_lines": False})]
    assert fake_st.caption_calls[-1] == (
        "Additional retrieved context 1; Additional retrieved context 2"
    )
    assert not any("No " in caption for caption in fake_st.caption_calls)


def test_disclosure_keeps_heading_and_explanation_in_one_block(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)

    chat.render_answer(structured_answer())

    disclosure = [body for body in fake_st.markdown_calls if "Formatted source excerpts" in body]
    assert len(disclosure) == 1
    assert chat.FORMATTED_SOURCE_EXCERPTS_CAPTION in disclosure[0]
    assert chat.FORMATTED_SOURCE_EXCERPTS_CAPTION not in fake_st.caption_calls


@pytest.mark.parametrize("replay", [False, True])
def test_answer_markdown_is_unchanged_and_alone_in_heading_style_container(monkeypatch, replay):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(chat, "st", fake_st)
    markdown = "# Business Model\nBody text.\n## Revenue Streams\n### Revenue Model Evolution"
    answer = structured_answer().model_copy(update={
        "answer": markdown,
        "verified_quotes": [VerifiedQuote(
            file_id="file-A", source_display_name="Report.pdf", text="Exact source text.",
        )],
    })
    original = answer.model_dump(mode="json")

    if replay:
        chat.render_chat_history([chat.build_assistant_message(answer)])
    else:
        chat.render_answer(answer)

    start = next(i for i, event in enumerate(fake_st.events) if event[0] == "container_enter")
    end = next(i for i, event in enumerate(fake_st.events) if event[0] == "container_exit")
    assert fake_st.events[start + 1:end] == [("markdown", markdown)]
    assert fake_st.html_calls == [chat.SYNTHESIZED_ANSWER_STYLES]
    assert fake_st.events.index(("expander", "Verified quotations")) > end
    assert fake_st.events.index(("markdown", "**Evidence**")) > end
    assert answer.model_dump(mode="json") == original


def test_heading_containers_support_multiple_history_answers_and_current_answer():
    from streamlit.testing.v1 import AppTest

    def app_script():
        from src.schemas.answer import VDRAnswer
        from src.ui.chat import build_assistant_message, render_answer, render_chat_history

        answer = VDRAnswer(answer="# Business Model\n## Revenue Streams\nBody text.")
        message = build_assistant_message(answer)
        render_chat_history([message, message])
        render_answer(answer)

    app = AppTest.from_function(app_script).run(timeout=10)
    assert not app.exception
    assert [item.value for item in app.markdown] == [
        "# Business Model\n## Revenue Streams\nBody text."
    ] * 3


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
            ["Evidence", "Structured", "Original retrieved passages"],
            {"default": "Evidence"},
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
