import pytest

from src.presentation import evidence_verifier
from src.presentation.evidence_verifier import (
    attach_verified_presentations,
    verify_evidence_presentations,
    verify_metric_candidate,
    verify_table_candidate,
)
from src.schemas.evidence import SourceReference
from src.schemas.evidence_presentation import (
    EvidenceMetricCandidate,
    EvidencePresentationPassage,
    EvidencePresentationSelection,
    EvidenceTableCandidate,
    VerifiedEvidencePresentation,
)


def source(
    file_id: str | None = "file-A",
    evidence: list[str] | None = None,
) -> SourceReference:
    return SourceReference(
        file_id=file_id,
        display_name="VDR → Finance → Report.pdf",
        evidence=[] if evidence is None else evidence,
    )


def metric(
    *,
    file_id: str = "file-A",
    passage_index: int = 0,
    label: str = "Revenue",
    value: str = "28,051",
    period: str | None = "FY2024",
    unit: str | None = "EURm",
    source_span: str = "Revenue FY2024 EURm 28,051",
) -> EvidenceMetricCandidate:
    return EvidenceMetricCandidate(
        file_id=file_id,
        passage_index=passage_index,
        label=label,
        value=value,
        period=period,
        unit=unit,
        source_span=source_span,
    )


def table(
    *,
    file_id: str = "file-A",
    passage_index: int = 0,
    title: str | None = None,
    columns: list[str] | None = None,
    rows: list[list[str]] | None = None,
    header_source_span: str | None = None,
    row_source_spans: list[str] | None = None,
) -> EvidenceTableCandidate:
    actual_columns = ["Year", "Revenue"] if columns is None else columns
    actual_rows = (
        [["2022", "20,062"], ["2023", "23,683"]]
        if rows is None
        else rows
    )
    return EvidenceTableCandidate(
        file_id=file_id,
        passage_index=passage_index,
        title=title,
        columns=actual_columns,
        rows=actual_rows,
        header_source_span=(
            " ".join(actual_columns)
            if header_source_span is None
            else header_source_span
        ),
        row_source_spans=(
            [" ".join(row) for row in actual_rows]
            if row_source_spans is None
            else row_source_spans
        ),
    )


def test_exact_metric_verifies_with_source_derived_span() -> None:
    passage = "Prefix\nRevenue FY2024 EURm 28,051\nSuffix"

    verified = verify_metric_candidate(metric(), [source(evidence=[passage])])

    assert verified is not None
    assert verified.file_id == "file-A"
    assert verified.passage_index == 0
    assert verified.metric.model_dump() == {
        "label": "Revenue",
        "value": "28,051",
        "period": "FY2024",
        "unit": "EURm",
        "source_text": "Revenue FY2024 EURm 28,051",
    }


def test_whitespace_normalized_metric_recovers_original_raw_span() -> None:
    raw = "Revenue\tFY2024  EURm\r\n28,051"

    verified = verify_metric_candidate(metric(), [source(evidence=[raw])])

    assert verified is not None
    assert verified.metric.source_text == raw


@pytest.mark.parametrize(
    "candidate",
    [
        metric(file_id="file-B"),
        metric().model_copy(update={"file_id": ""}),
        metric(file_id=" file-A "),
        metric(passage_index=1),
        metric(source_span="Revenue FY2024 EURm 99,999", value="99,999"),
        metric(label="revenue"),
        metric(value="28051"),
        metric(period="FY2025"),
        metric(unit="USDm"),
        metric(label="Rev."),
    ],
)
def test_unverifiable_metric_identity_or_exact_fields_fail(candidate) -> None:
    assert verify_metric_candidate(
        candidate,
        [source(evidence=["Revenue FY2024 EURm 28,051"])],
    ) is None


def test_metric_source_span_cannot_come_from_another_passage() -> None:
    sources = [
        source(
            evidence=[
                "Revenue FY2023 EURm 23,683",
                "Revenue FY2024 EURm 28,051",
            ]
        )
    ]

    assert verify_metric_candidate(metric(passage_index=0), sources) is None


@pytest.mark.parametrize(
    ("candidate", "passage"),
    [
        (
            metric(
                label="2024",
                value="28,051",
                period=None,
                unit=None,
                source_span="2024 28,051",
            ),
            "2024 28,051",
        ),
        (
            metric(
                value="Not available",
                period=None,
                unit=None,
                source_span="Revenue Not available",
            ),
            "Revenue Not available",
        ),
    ],
)
def test_metric_requires_a_label_and_numeric_value(candidate, passage) -> None:
    assert verify_metric_candidate(
        candidate,
        [source(evidence=[passage])],
    ) is None


@pytest.mark.parametrize(
    "passage",
    [
        "Revenue 10,131 FY2024 EURm 28,051",
        "Revenue FY2024 USD 20,000 and EURm 28,051",
        "Revenue FY2023 20,000. Revenue FY2024 EURm 28,051",
        "Revenue FY2024\n\nEURm 28,051",
    ],
)
def test_metric_fails_for_competing_or_broad_relationship(passage: str) -> None:
    assert verify_metric_candidate(
        metric(source_span=passage),
        [source(evidence=[passage])],
    ) is None


def test_metric_cannot_hide_competing_value_outside_candidate_span() -> None:
    passage = "Revenue FY2024 EURm 28,051 99,999"

    assert verify_metric_candidate(
        metric(),
        [source(evidence=[passage])],
    ) is None


def test_metric_label_cannot_be_recovered_from_inside_a_larger_word() -> None:
    passage = "TotalRevenue FY2024 EURm 28,051"

    assert verify_metric_candidate(
        metric(),
        [source(evidence=[passage])],
    ) is None


@pytest.mark.parametrize("qualifier", ["Q1", "H2", "Current", "Forecast"])
def test_metric_cannot_hide_period_context_outside_candidate_span(
    qualifier: str,
) -> None:
    relationship = "Revenue EURm 28,051"
    passage = f"{qualifier} {relationship}"

    assert verify_metric_candidate(
        metric(
            period=None,
            source_span=relationship,
        ),
        [source(evidence=[passage])],
    ) is None


@pytest.mark.parametrize(
    "qualifier",
    ["Target", "Estimated", "Unaudited", "Pro forma", "Approximately"],
)
def test_metric_cannot_hide_textual_qualifier_outside_candidate_span(
    qualifier: str,
) -> None:
    relationship = "Revenue EURm 28,051"
    passage = f"{qualifier} {relationship}"

    assert verify_metric_candidate(
        metric(period=None, source_span=relationship),
        [source(evidence=[passage])],
    ) is None


@pytest.mark.parametrize(
    "candidate",
    [
        metric(value="FY2024", period="28,051"),
        metric(label="EURm", unit=None),
        metric(unit="FY2024", period=None),
    ],
)
def test_metric_rejects_semantic_field_role_swaps(candidate) -> None:
    assert verify_metric_candidate(
        candidate,
        [source(evidence=["Revenue FY2024 EURm 28,051"])],
    ) is None


def test_metric_rejects_generic_currency_code_used_as_label() -> None:
    passage = "Revenue PLN 28,051"
    candidate = metric(
        label="PLN",
        period=None,
        unit=None,
        source_span="PLN 28,051",
    )

    assert verify_metric_candidate(
        candidate,
        [source(evidence=[passage])],
    ) is None


@pytest.mark.parametrize(
    ("candidate", "passage"),
    [
        (
            metric(
                value="28,051 99,999",
                source_span="Revenue FY2024 EURm 28,051 99,999",
            ),
            "Revenue FY2024 EURm 28,051 99,999",
        ),
        (
            metric(
                value="FY2024 EURm 28,051",
                period=None,
                unit=None,
            ),
            "Revenue FY2024 EURm 28,051",
        ),
        (
            metric(
                label="Revenue 99,999",
                source_span="Revenue 99,999 FY2024 EURm 28,051",
            ),
            "Revenue 99,999 FY2024 EURm 28,051",
        ),
    ],
)
def test_metric_rejects_competing_fields_packed_into_display_fields(
    candidate,
    passage: str,
) -> None:
    assert verify_metric_candidate(
        candidate,
        [source(evidence=[passage])],
    ) is None


@pytest.mark.parametrize(
    ("passage", "value"),
    [
        ("Revenue FY2024 EURm -28,051", "28,051"),
        ("Revenue FY2024 EURm +28,051", "28,051"),
        ("Revenue FY2024 EURm (28,051)", "28,051"),
    ],
)
def test_metric_cannot_drop_numeric_sign_or_accounting_punctuation(
    passage: str,
    value: str,
) -> None:
    assert verify_metric_candidate(
        metric(value=value, source_span=passage),
        [source(evidence=[passage])],
    ) is None


@pytest.mark.parametrize("value", ["-28,051", "+28,051", "(28,051)"])
def test_metric_preserves_exact_signed_or_accounting_value(value: str) -> None:
    passage = f"Revenue FY2024 EURm {value}"

    verified = verify_metric_candidate(
        metric(value=value, source_span=passage),
        [source(evidence=[passage])],
    )

    assert verified is not None
    assert verified.metric.value == value


@pytest.mark.parametrize(
    "passage",
    [
        "Revenue was not 28,051",
        "Revenue was approximately 28,051",
        "Revenue increased to 28,051",
    ],
)
def test_metric_cannot_drop_semantic_qualifiers(passage: str) -> None:
    assert verify_metric_candidate(
        metric(
            value="28,051",
            period=None,
            unit=None,
            source_span=passage,
        ),
        [source(evidence=[passage])],
    ) is None


def test_metric_span_over_200_characters_fails() -> None:
    passage = f"Revenue {'x' * 180} FY2024 EURm 28,051"

    assert verify_metric_candidate(
        metric(source_span=passage),
        [source(evidence=[passage])],
    ) is None


@pytest.mark.parametrize(
    "source_order",
    [
        "Revenue FY2024 EURm 28,051",
        "FY2024 Revenue 28,051 EURm",
        "Revenue 28,051 EURm FY2024",
    ],
)
def test_supported_metric_field_orders_verify(source_order: str) -> None:
    verified = verify_metric_candidate(
        metric(source_span=source_order),
        [source(evidence=[source_order])],
    )

    assert verified is not None


@pytest.mark.parametrize(
    "candidate",
    [
        metric(
            label="Margin",
            value="15.6",
            unit="%",
            source_span="Margin FY2024 15.6%",
        ),
        metric(
            value="28,051",
            unit="€",
            source_span="Revenue FY2024 €28,051",
        ),
    ],
)
def test_exact_percentage_and_currency_symbols_verify(candidate) -> None:
    verified = verify_metric_candidate(
        candidate,
        [source(evidence=[candidate.source_span])],
    )

    assert verified is not None


def test_exact_compound_currency_value_verifies_without_rewriting() -> None:
    passage = "Revenue FY2024 €42.6 million"
    candidate = metric(
        value="€42.6 million",
        unit=None,
        source_span=passage,
    )

    verified = verify_metric_candidate(
        candidate,
        [source(evidence=[passage])],
    )

    assert verified is not None
    assert verified.metric.value == "€42.6 million"


def test_exact_generic_currency_code_verifies_as_unit() -> None:
    passage = "Revenue FY2024 PLN 28,051"
    candidate = metric(unit="PLN", source_span=passage)

    verified = verify_metric_candidate(
        candidate,
        [source(evidence=[passage])],
    )

    assert verified is not None
    assert verified.metric.unit == "PLN"


@pytest.mark.parametrize("label", ["Employees", "Headcount", "People"])
def test_explicit_count_metric_labels_remain_supported(label: str) -> None:
    passage = f"{label} 12,000"
    candidate = metric(
        label=label,
        value="12,000",
        period=None,
        unit=None,
        source_span=passage,
    )

    verified = verify_metric_candidate(
        candidate,
        [source(evidence=[passage])],
    )

    assert verified is not None
    assert verified.metric.label == label


def test_valid_row_oriented_table_verifies_exact_strings() -> None:
    passage = "Year Revenue\n2022 20,062\n2023 23,683"

    verified = verify_table_candidate(table(), [source(evidence=[passage])])

    assert verified is not None
    assert verified.file_id == "file-A"
    assert verified.passage_index == 0
    assert verified.table.columns == ["Year", "Revenue"]
    assert verified.table.rows == [["2022", "20,062"], ["2023", "23,683"]]
    assert verified.table.source_texts == [
        "Year Revenue",
        "2022 20,062",
        "2023 23,683",
    ]


def test_table_recovers_whitespace_normalized_header_and_rows() -> None:
    passage = "Year\tRevenue\r\n2022  20,062\r\n2023\t23,683"

    verified = verify_table_candidate(table(), [source(evidence=[passage])])

    assert verified is not None
    assert verified.table.source_texts == [
        "Year\tRevenue",
        "2022  20,062",
        "2023\t23,683",
    ]


def test_valid_15_by_6_table_at_90_cell_limit_verifies() -> None:
    columns = ["Year", "Revenue", "EBITDA", "Debt", "Cash", "Employees"]
    rows = [
        [str(2010 + index), *[f"{index}-{column}" for column in range(1, 6)]]
        for index in range(15)
    ]
    passage = "\n".join(
        [" ".join(columns), *(" ".join(row) for row in rows)]
    )

    verified = verify_table_candidate(
        table(columns=columns, rows=rows),
        [source(evidence=[passage])],
    )

    assert verified is not None
    assert len(verified.table.rows) == 15
    assert len(verified.table.columns) == 6


@pytest.mark.parametrize(
    "candidate",
    [
        EvidenceTableCandidate.model_construct(
            file_id="file-A",
            passage_index=0,
            title=None,
            columns=["Year", "Revenue"],
            rows=[["2022", "20"], ["2023"]],
            header_source_span="Year Revenue",
            row_source_spans=["2022 20", "2023"],
        ),
        EvidenceTableCandidate.model_construct(
            file_id="file-A",
            passage_index=0,
            title=None,
            columns=["Year", "Revenue"],
            rows=[[str(index), str(index)] for index in range(16)],
            header_source_span="Year Revenue",
            row_source_spans=[f"{index} {index}" for index in range(16)],
        ),
        EvidenceTableCandidate.model_construct(
            file_id="file-A",
            passage_index=0,
            title=None,
            columns=[f"Column {index}" for index in range(7)],
            rows=[[str(index)] * 7 for index in range(2)],
            header_source_span="header",
            row_source_spans=["row", "row"],
        ),
        EvidenceTableCandidate.model_construct(
            file_id="file-A",
            passage_index=0,
            title=None,
            columns=["Year", "Revenue"],
            rows=[["2022", "20"]],
            header_source_span="Year Revenue",
            row_source_spans=["2022 20"],
        ),
        EvidenceTableCandidate.model_construct(
            file_id="file-A",
            passage_index=0,
            title=None,
            columns=["Year", "Year"],
            rows=[["2022", "20"], ["2023", "30"]],
            header_source_span="Year Year",
            row_source_spans=["2022 20", "2023 30"],
        ),
        EvidenceTableCandidate.model_construct(
            file_id="file-A",
            passage_index=0,
            title=None,
            columns=["Year", ""],
            rows=[["2022", "20"], ["2023", "30"]],
            header_source_span="Year",
            row_source_spans=["2022 20", "2023 30"],
        ),
    ],
)
def test_malformed_or_oversized_table_fails_whole(candidate) -> None:
    passage = "Year Revenue\n2022 20\n2023 30\n" + "\n".join(
        f"{index} {index}" for index in range(16)
    )

    assert verify_table_candidate(candidate, [source(evidence=[passage])]) is None


@pytest.mark.parametrize(
    "candidate",
    [
        table(file_id="file-B"),
        table(passage_index=1),
        table(header_source_span="Period Revenue"),
        table(row_source_spans=["2022 20,062", "2024 99,999"]),
        table().model_copy(update={"row_source_spans": ["2022 20,062"]}),
        table(rows=[["2022", "20,062"], ["2023", "23683"]]),
        table(rows=[["2023", "23,683"], ["2022", "20,062"]]),
    ],
)
def test_table_identity_header_rows_and_exact_cells_fail_closed(candidate) -> None:
    passage = "Year Revenue\n2022 20,062\n2023 23,683"

    assert verify_table_candidate(candidate, [source(evidence=[passage])]) is None


def test_table_rejects_header_after_rows() -> None:
    passage = "2022 20,062\n2023 23,683\nYear Revenue"

    assert verify_table_candidate(
        table(),
        [source(evidence=[passage])],
    ) is None


def test_table_rejects_overlapping_reused_row_spans() -> None:
    passage = "Year Revenue\n2022 20,062"
    candidate = table(
        rows=[["2022", "20,062"], ["2022", "20,062"]],
        row_source_spans=["2022 20,062", "2022 20,062"],
    )

    assert verify_table_candidate(
        candidate,
        [source(evidence=[passage])],
    ) is None


def test_table_cannot_assemble_rows_across_passages() -> None:
    sources = [
        source(
            evidence=[
                "Year Revenue\n2022 20,062",
                "2023 23,683",
            ]
        )
    ]

    assert verify_table_candidate(table(), sources) is None


def test_one_invalid_or_extra_row_value_rejects_whole_table() -> None:
    passage = "Year Revenue\n2022 20,062\n2023 23,683 15.7%"

    assert verify_table_candidate(table(), [source(evidence=[passage])]) is None


def test_horizontal_parallel_series_is_rejected() -> None:
    passage = (
        "Metric 2022 2023 2024\n"
        "Revenue 20,062 23,683 28,051\n"
        "EBITDA 3,245 4,102 4,905"
    )
    candidate = table(
        columns=["Metric", "2022", "2023", "2024"],
        rows=[
            ["Revenue", "20,062", "23,683", "28,051"],
            ["EBITDA", "3,245", "4,102", "4,905"],
        ],
    )

    assert verify_table_candidate(candidate, [source(evidence=[passage])]) is None


@pytest.mark.parametrize(
    "columns",
    [
        ["Metric", "FY2023A", "FY2024F"],
        ["Metric", "Current", "Prior"],
        ["Metric", "Actual", "Forecast"],
        ["Metric", "Base", "Upside"],
    ],
)
def test_period_like_horizontal_headers_are_rejected(
    columns: list[str],
) -> None:
    rows = [["Revenue", "20", "30"], ["EBITDA", "4", "5"]]
    passage = "\n".join(
        [" ".join(columns), *(" ".join(row) for row in rows)]
    )

    assert verify_table_candidate(
        table(columns=columns, rows=rows),
        [source(evidence=[passage])],
    ) is None


@pytest.mark.parametrize(
    ("first_value", "second_value"),
    [
        ("20 kg", "30 tonnes"),
        ("20 MW", "30 MWh"),
        ("20 employees", "30 headcount"),
        ("20 AUD", "30 CAD"),
        ("20 PLN", "30 CZK"),
    ],
)
def test_mixed_generic_units_require_an_explicit_unit_column(
    first_value: str,
    second_value: str,
) -> None:
    passage = f"Year Amount\n2023 {first_value}\n2024 {second_value}"
    candidate = table(
        columns=["Year", "Amount"],
        rows=[["2023", first_value], ["2024", second_value]],
    )

    assert verify_table_candidate(
        candidate,
        [source(evidence=[passage])],
    ) is None


@pytest.mark.parametrize(
    "raw_value",
    [
        "-23,683",
        "+23,683",
        "(23,683)",
        "23,683-",
        "~23,683",
        "<23,683",
        "($23,683)",
    ],
)
def test_table_cannot_drop_numeric_sign_or_accounting_punctuation(
    raw_value: str,
) -> None:
    passage = f"Year Revenue\n2022 20,062\n2023 {raw_value}"

    assert verify_table_candidate(
        table(),
        [source(evidence=[passage])],
    ) is None


def test_table_preserves_exact_signed_and_accounting_values() -> None:
    rows = [["2022", "-20,062"], ["2023", "(23,683)"]]
    passage = "Year Revenue\n2022 -20,062\n2023 (23,683)"

    verified = verify_table_candidate(
        table(rows=rows),
        [source(evidence=[passage])],
    )

    assert verified is not None
    assert verified.table.rows == rows


def test_mixed_units_require_an_explicit_unit_column() -> None:
    passage = "Year Revenue\n2022 EUR 20\n2023 USD 30"
    candidate = table(
        rows=[["2022", "EUR 20"], ["2023", "USD 30"]],
    )

    assert verify_table_candidate(candidate, [source(evidence=[passage])]) is None


def test_explicit_unit_column_allows_exact_mixed_units() -> None:
    passage = "Year Unit Revenue\n2022 EUR 20\n2023 USD 30"
    candidate = table(
        columns=["Year", "Unit", "Revenue"],
        rows=[["2022", "EUR", "20"], ["2023", "USD", "30"]],
    )

    verified = verify_table_candidate(candidate, [source(evidence=[passage])])

    assert verified is not None
    assert verified.table.rows[1] == ["2023", "USD", "30"]


def test_missing_unit_is_accepted_without_invention() -> None:
    passage = "Year Revenue\n2022 20\n2023 30"

    verified = verify_table_candidate(
        table(rows=[["2022", "20"], ["2023", "30"]]),
        [source(evidence=[passage])],
    )

    assert verified is not None
    assert all("EUR" not in cell for row in verified.table.rows for cell in row)


def test_ambiguous_revenue_example_produces_no_verified_structure() -> None:
    passage = (
        "Revenue 10,131 12,324 13,533 14,821 17,117 20,062 23,683\n"
        "28,051 15.6% 15.7%"
    )
    ambiguous_metric = metric(
        value="28,051",
        period=None,
        unit=None,
        source_span=passage,
    )
    horizontal_table = table(
        columns=["Revenue", "10,131", "12,324"],
        rows=[["Value", "13,533", "14,821"], ["Value", "17,117", "20,062"]],
        header_source_span="Revenue 10,131 12,324",
        row_source_spans=["13,533 14,821", "17,117 20,062"],
    )

    result = verify_evidence_presentations(
        EvidencePresentationSelection(
            metrics=[ambiguous_metric],
            tables=[horizontal_table],
        ),
        [source(evidence=[passage])],
    )

    assert result == {}


def test_row_oriented_revenue_without_unit_verifies() -> None:
    passage = "Year Revenue\n2022 20,062\n2023 23,683\n2024 28,051"
    candidate = table(
        rows=[
            ["2022", "20,062"],
            ["2023", "23,683"],
            ["2024", "28,051"],
        ]
    )

    verified = verify_table_candidate(candidate, [source(evidence=[passage])])

    assert verified is not None
    assert verified.table.columns == ["Year", "Revenue"]
    assert all(
        "EUR" not in value
        for row in verified.table.rows
        for value in row
    )


def test_revenue_rows_verify_while_ambiguous_percentages_are_omitted() -> None:
    passage = (
        "Year Revenue\n2022 20,062\n2023 23,683\n"
        "Margin 15.6% 15.7%"
    )
    revenue_table = table()
    percentage_metric = metric(
        label="Margin",
        value="15.6%",
        period=None,
        unit=None,
        source_span="Margin 15.6% 15.7%",
    )

    verified = verify_evidence_presentations(
        EvidencePresentationSelection(
            metrics=[percentage_metric],
            tables=[revenue_table],
        ),
        [source(evidence=[passage])],
    )

    assert len(verified["file-A"]) == 1
    assert verified["file-A"][0].metrics == []
    assert len(verified["file-A"][0].tables) == 1


def test_selection_cannot_reference_passage_outside_bounded_scope() -> None:
    sources = [
        source(
            evidence=[
                "Revenue FY2023 EURm 23,683",
                "Revenue FY2024 EURm 28,051",
            ]
        )
    ]
    scope = [
        EvidencePresentationPassage(
            file_id="file-A",
            passage_index=0,
            text=sources[0].evidence[0],
        )
    ]

    verified = verify_evidence_presentations(
        EvidencePresentationSelection(metrics=[metric(passage_index=1)]),
        sources,
        passage_scope=scope,
    )

    assert verified == {}


def test_selection_cannot_use_text_beyond_bounded_raw_prefix() -> None:
    passage = f"{'x' * 4500}\nRevenue FY2024 EURm 28,051"
    scope = [
        EvidencePresentationPassage(
            file_id="file-A",
            passage_index=0,
            text=passage[:4500],
        )
    ]

    verified = verify_evidence_presentations(
        EvidencePresentationSelection(metrics=[metric()]),
        [source(evidence=[passage])],
        passage_scope=scope,
    )

    assert verified == {}


def test_full_raw_suffix_still_blocks_metric_at_scope_boundary() -> None:
    relationship = "Revenue FY2024 EURm 28,051"
    passage = f"{'x' * (4500 - len(relationship))}{relationship} 99,999"
    scope = [
        EvidencePresentationPassage(
            file_id="file-A",
            passage_index=0,
            text=passage[:4500],
        )
    ]

    verified = verify_evidence_presentations(
        EvidencePresentationSelection(metrics=[metric()]),
        [source(evidence=[passage])],
        passage_scope=scope,
    )

    assert verified == {}


def test_duplicate_metrics_keep_earlier_ranked_passage_and_exact_source_order() -> None:
    sources = [
        source(
            evidence=[
                "Revenue FY2024 EURm 28,051",
                "Again: Revenue FY2024 EURm 28,051",
            ]
        )
    ]
    candidates = [
        metric(passage_index=1),
        metric(passage_index=0),
        metric(passage_index=0),
    ]

    verified = verify_evidence_presentations(
        EvidencePresentationSelection(metrics=candidates),
        sources,
    )

    assert len(verified["file-A"]) == 1
    assert verified["file-A"][0].passage_index == 0
    assert len(verified["file-A"][0].metrics) == 1


def test_verified_metric_limits_apply_per_passage_source_and_answer() -> None:
    sources: list[SourceReference] = []
    candidates: list[EvidenceMetricCandidate] = []
    for source_index in range(3):
        file_id = f"file-{source_index}"
        labels = [
            f"Metric{chr(65 + source_index)}{chr(65 + item)}"
            for item in range(4)
        ]
        lines = [
            f"{labels[item]} {1000 + item}" for item in range(4)
        ]
        candidates.extend(
            metric(
                file_id=file_id,
                passage_index=0,
                label=labels[item],
                value=str(1000 + item),
                period=None,
                unit=None,
                source_span=lines[item],
            )
            for item in range(4)
        )
        sources.append(source(file_id=file_id, evidence=["\n".join(lines)]))

    selection = EvidencePresentationSelection.model_construct(
        metrics=candidates,
        tables=[],
    )
    verified = verify_evidence_presentations(selection, sources)

    assert sum(
        len(presentation.metrics)
        for presentations in verified.values()
        for presentation in presentations
    ) == evidence_verifier.MAX_VERIFIED_METRICS_PER_ANSWER
    assert len(verified["file-0"][0].metrics) == 4
    assert len(verified["file-1"][0].metrics) == 4
    assert len(verified["file-2"][0].metrics) == 2


def test_verified_metric_source_limit_is_six_across_passages() -> None:
    passages: list[str] = []
    candidates: list[EvidenceMetricCandidate] = []
    for passage_index in range(2):
        labels = [
            f"Metric{chr(65 + passage_index)}{chr(65 + item)}"
            for item in range(4)
        ]
        lines = [
            f"{labels[item]} {1000 + item}" for item in range(4)
        ]
        passages.append("\n".join(lines))
        candidates.extend(
            metric(
                passage_index=passage_index,
                label=labels[item],
                value=str(1000 + item),
                period=None,
                unit=None,
                source_span=lines[item],
            )
            for item in range(4)
        )

    verified = verify_evidence_presentations(
        EvidencePresentationSelection(metrics=candidates),
        [source(evidence=passages)],
    )

    assert sum(len(item.metrics) for item in verified["file-A"]) == 6


def test_duplicate_tables_keep_first_and_table_limits_apply() -> None:
    passages = [
        "Year Revenue\n2022 20\n2023 30",
        "Year Revenue\n2024 40\n2025 50",
        "Year Revenue\n2026 60\n2027 70",
    ]
    candidates = [
        table(rows=[["2022", "20"], ["2023", "30"]]),
        table(rows=[["2022", "20"], ["2023", "30"]]),
        table(
            passage_index=1,
            rows=[["2024", "40"], ["2025", "50"]],
        ),
        table(
            passage_index=2,
            rows=[["2026", "60"], ["2027", "70"]],
        ),
    ]

    verified = verify_evidence_presentations(
        EvidencePresentationSelection(tables=candidates),
        [source(evidence=passages)],
    )

    assert len(verified["file-A"]) == 2
    assert [item.passage_index for item in verified["file-A"]] == [0, 1]
    assert sum(len(item.tables) for item in verified["file-A"]) == 2


def test_verified_table_passage_limit_is_one_for_distinct_tables() -> None:
    passage = (
        "Year Revenue\n2022 20\n2023 30\n"
        "Year EBITDA\n2022 4\n2023 5"
    )
    candidates = [
        table(rows=[["2022", "20"], ["2023", "30"]]),
        table(
            columns=["Year", "EBITDA"],
            rows=[["2022", "4"], ["2023", "5"]],
        ),
    ]

    verified = verify_evidence_presentations(
        EvidencePresentationSelection(tables=candidates),
        [source(evidence=[passage])],
    )

    assert len(verified["file-A"][0].tables) == 1
    assert verified["file-A"][0].tables[0].columns == ["Year", "Revenue"]


def test_verified_table_answer_limit_is_three() -> None:
    sources: list[SourceReference] = []
    candidates: list[EvidenceTableCandidate] = []
    for index in range(4):
        file_id = f"file-{index}"
        rows = [
            ["2022", str(20 + index)],
            ["2023", str(30 + index)],
        ]
        passage = "\n".join(
            ["Year Revenue", *(" ".join(row) for row in rows)]
        )
        sources.append(source(file_id=file_id, evidence=[passage]))
        candidates.append(table(file_id=file_id, rows=rows))

    verified = verify_evidence_presentations(
        EvidencePresentationSelection(tables=candidates),
        sources,
    )

    assert sum(
        len(presentation.tables)
        for presentations in verified.values()
        for presentation in presentations
    ) == evidence_verifier.MAX_VERIFIED_TABLES_PER_ANSWER


def test_verified_component_answer_limit_is_twelve() -> None:
    sources: list[SourceReference] = []
    metric_candidates: list[EvidenceMetricCandidate] = []
    table_candidates: list[EvidenceTableCandidate] = []
    for source_index in range(3):
        file_id = f"file-{source_index}"
        labels = [
            f"Metric{chr(65 + source_index)}{chr(65 + item)}"
            for item in range(4)
        ]
        metric_lines = [
            f"{labels[item]} {1000 + item}" for item in range(4)
        ]
        rows = [
            ["2022", str(20 + source_index)],
            ["2023", str(30 + source_index)],
        ]
        table_lines = ["Year Revenue", *(" ".join(row) for row in rows)]
        sources.append(
            source(
                file_id=file_id,
                evidence=["\n".join([*metric_lines, *table_lines])],
            )
        )
        metric_candidates.extend(
            metric(
                file_id=file_id,
                label=labels[item],
                value=str(1000 + item),
                period=None,
                unit=None,
                source_span=metric_lines[item],
            )
            for item in range(4)
        )
        table_candidates.append(table(file_id=file_id, rows=rows))

    selection = EvidencePresentationSelection(
        metrics=metric_candidates,
        tables=table_candidates,
    )
    verified = verify_evidence_presentations(selection, sources)
    presentations = [
        presentation
        for source_presentations in verified.values()
        for presentation in source_presentations
    ]
    component_count = sum(
        len(presentation.metrics) + len(presentation.tables)
        for presentation in presentations
    )

    assert component_count == evidence_verifier.MAX_VERIFIED_COMPONENTS_PER_ANSWER


def test_identical_metrics_from_different_files_remain_distinct(
) -> None:
    evidence = ["Revenue FY2024 EURm 28,051"]
    sources = [source("file-B", evidence), source("file-A", evidence)]
    selection = EvidencePresentationSelection(
        metrics=[metric(file_id="file-A"), metric(file_id="file-B")]
    )

    verified = verify_evidence_presentations(selection, sources)

    assert list(verified) == ["file-B", "file-A"]
    assert verified["file-A"][0].metrics == verified["file-B"][0].metrics


def test_attach_verified_presentations_copies_sources_without_mutation() -> None:
    original_sources = [source("file-A", ["raw A"]), source("file-B", ["raw B"])]
    presentation = VerifiedEvidencePresentation(
        passage_index=0,
        metrics=[],
        tables=[],
    )

    attached = attach_verified_presentations(
        original_sources,
        {"file-A": [presentation]},
    )

    assert attached is not original_sources
    assert attached[0] is not original_sources[0]
    assert original_sources[0].presentations == []
    assert attached[0].presentations == [presentation]
    assert attached[1].presentations == []
    assert attached[0].evidence == ["raw A"]
