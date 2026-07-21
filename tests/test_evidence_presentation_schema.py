import pytest
from pydantic import ValidationError

from src.schemas.answer import VDRAnswer
from src.schemas.evidence import SourceReference
from src.schemas.evidence_presentation import (
    EvidenceMetricCandidate,
    EvidencePresentationPassage,
    EvidencePresentationSelection,
    EvidenceTableCandidate,
    VerifiedEvidenceMetric,
    VerifiedEvidencePresentation,
    VerifiedEvidenceTable,
)


def metric_candidate() -> EvidenceMetricCandidate:
    return EvidenceMetricCandidate(
        file_id="file-A",
        passage_index=0,
        label="Revenue",
        value="28,051",
        period="FY2024",
        unit="EURm",
        source_span="Revenue FY2024 EURm 28,051",
    )


def table_candidate(
    *,
    columns: list[str] | None = None,
    rows: list[list[str]] | None = None,
    row_source_spans: list[str] | None = None,
) -> EvidenceTableCandidate:
    selected_columns = columns or ["Year", "Revenue"]
    selected_rows = rows or [["2023", "23,683"], ["2024", "28,051"]]
    selected_spans = row_source_spans or [" ".join(row) for row in selected_rows]
    return EvidenceTableCandidate(
        file_id="file-A",
        passage_index=0,
        columns=selected_columns,
        rows=selected_rows,
        header_source_span=" ".join(selected_columns),
        row_source_spans=selected_spans,
    )


def test_candidate_and_verified_lists_default_to_independent_empty_lists() -> None:
    first_selection = EvidencePresentationSelection()
    second_selection = EvidencePresentationSelection()
    first_presentation = VerifiedEvidencePresentation(passage_index=0)
    second_presentation = VerifiedEvidencePresentation(passage_index=1)

    first_selection.metrics.append(metric_candidate())
    first_presentation.metrics.append(
        VerifiedEvidenceMetric(
            label="Revenue",
            value="28,051",
            source_text="Revenue 28,051",
        )
    )

    assert second_selection.metrics == []
    assert second_selection.tables == []
    assert second_presentation.metrics == []
    assert second_presentation.tables == []


def test_source_reference_presentations_are_default_empty_and_independent() -> None:
    first = SourceReference(display_name="First.pdf")
    second = SourceReference(display_name="Second.pdf")

    first.presentations.append(VerifiedEvidencePresentation(passage_index=0))

    assert second.presentations == []


def test_old_source_payload_without_presentations_remains_valid() -> None:
    source = SourceReference.model_validate(
        {
            "file_id": "file-A",
            "display_name": "VDR → Finance → Report.pdf",
            "evidence": ["Revenue FY2024 EURm 28,051"],
        }
    )

    assert source.presentations == []


def test_verified_presentation_round_trips_through_answer_json() -> None:
    presentation = VerifiedEvidencePresentation(
        passage_index=0,
        metrics=[
            VerifiedEvidenceMetric(
                label="Revenue",
                value="28,051",
                period="FY2024",
                unit="EURm",
                source_text="Revenue FY2024 EURm 28,051",
            )
        ],
        tables=[
            VerifiedEvidenceTable(
                title=None,
                columns=["Year", "Revenue"],
                rows=[["2023", "23,683"], ["2024", "28,051"]],
                source_texts=[
                    "Year Revenue",
                    "2023 23,683",
                    "2024 28,051",
                ],
            )
        ],
    )
    answer = VDRAnswer(
        answer="Supported answer",
        source_files=["VDR → Finance → Report.pdf"],
        sources=[
            SourceReference(
                file_id="file-A",
                display_name="VDR → Finance → Report.pdf",
                evidence=["Revenue FY2024 EURm 28,051"],
                presentations=[presentation],
            )
        ],
    )

    restored = VDRAnswer.model_validate(answer.model_dump(mode="json"))

    assert restored == answer
    assert restored.sources[0].file_id == "file-A"


def test_candidate_models_are_transient_not_answer_fields() -> None:
    selection = EvidencePresentationSelection(metrics=[metric_candidate()])
    answer = VDRAnswer(
        answer="Supported answer",
        sources=[SourceReference(display_name="Report.pdf")],
    )

    payload = answer.model_dump(mode="json")

    assert selection.metrics
    assert "metrics" not in payload
    assert "tables" not in payload
    assert "candidates" not in payload


def test_candidate_selection_rejects_more_than_twelve_metrics() -> None:
    with pytest.raises(ValidationError):
        EvidencePresentationSelection(metrics=[metric_candidate()] * 13)


def test_candidate_selection_rejects_more_than_four_tables() -> None:
    with pytest.raises(ValidationError):
        EvidencePresentationSelection(tables=[table_candidate()] * 5)


def test_candidate_table_accepts_exact_fifteen_by_six_cell_limit() -> None:
    columns = [f"Column {index}" for index in range(6)]
    rows = [
        [f"r{row}c{column}" for column in range(6)]
        for row in range(15)
    ]

    candidate = table_candidate(columns=columns, rows=rows)

    assert len(candidate.rows) == 15
    assert sum(len(row) for row in candidate.rows) == 90


@pytest.mark.parametrize(
    ("columns", "rows"),
    [
        (["A", "B"], [[str(row), "value"] for row in range(16)]),
        ([f"C{column}" for column in range(7)], [["x"] * 7] * 2),
    ],
)
def test_candidate_table_rejects_row_column_and_cell_limit_violations(
    columns: list[str],
    rows: list[list[str]],
) -> None:
    with pytest.raises(ValidationError):
        table_candidate(columns=columns, rows=rows)


def test_candidate_table_rejects_malformed_row_width() -> None:
    with pytest.raises(ValidationError, match="column count"):
        table_candidate(rows=[["2023", "23,683"], ["2024"]])


def test_candidate_table_rejects_missing_row_source_span() -> None:
    with pytest.raises(ValidationError):
        table_candidate(row_source_spans=["2023 23,683"])


def test_models_reject_coercion_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EvidencePresentationPassage(
            file_id="file-A",
            passage_index="0",
            text="Revenue 1 2 3 4",
        )

    with pytest.raises(ValidationError):
        EvidencePresentationSelection.model_validate({"unexpected": []})
