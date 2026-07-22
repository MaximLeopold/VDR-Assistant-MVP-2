import pytest

from src.presentation.parallel_series_verifier import (
    verify_parallel_series_candidate,
)
from src.schemas.evidence import SourceReference
from src.schemas.evidence_presentation import (
    EvidenceParallelSeriesCandidate,
    EvidenceSeriesCandidate,
)


def candidate(
    passage: str,
    *,
    category_label: str = "Period",
    categories: list[str] | None = None,
    series_specs: list[tuple[str, list[str], str | None]] | None = None,
    category_span: str | None = None,
    file_id: str = "file-A",
    passage_index: int = 0,
) -> EvidenceParallelSeriesCandidate:
    lines = passage.splitlines()
    selected_categories = categories or ["2024A", "2025E", "2026E"]
    selected_specs = series_specs or [
        ("Revenue", ["10,131", "12,324", "13,533"], None)
    ]
    series = []
    for label, values, unit in selected_specs:
        matching_line = next(
            (line for line in lines if line.strip().startswith(label)),
            f"{label} {' '.join(values)}",
        )
        series.append(
            EvidenceSeriesCandidate(
                label=label,
                values=values,
                unit=unit,
                source_span=matching_line.strip(),
            )
        )
    return EvidenceParallelSeriesCandidate(
        file_id=file_id,
        passage_index=passage_index,
        category_label=category_label,
        categories=selected_categories,
        category_source_span=(category_span or lines[0].strip()),
        series=series,
    )


def verify(
    passage: str,
    proposed: EvidenceParallelSeriesCandidate | None = None,
    *,
    scoped_text: str | None = None,
):
    selected = proposed or candidate(passage)
    sources = [
        SourceReference(
            file_id="file-A",
            display_name="Report.pdf",
            evidence=[passage],
        )
    ]
    return verify_parallel_series_candidate(
        selected,
        sources,
        passage_scope={("file-A", 0): scoped_text or passage},
    )


@pytest.mark.parametrize(
    "categories",
    [
        ["2024A", "2025E", "2026F"],
        ["2026B", "2027B", "2028E"],
        ["FY26B", "FY27E", "FY28E"],
        ["FY2026B", "FY2027E", "FY2028E"],
        ["2025A", "2026B", "2027E"],
        ["2024A", "2025PF", "2026F"],
        ["Actual", "Budget", "Forecast"],
        ["FY25", "FY2026", "FY27E"],
        ["Q1 27", "Q2 27", "Q3 27"],
        ["H1 2026", "H2 2026"],
        ["LTM", "NTM"],
        ["Base", "Upside", "Downside"],
    ],
)
def test_explicit_financial_categories_verify_exactly(
    categories: list[str],
) -> None:
    values = [str(index + 1) for index in range(len(categories))]
    passage = (
        f"Period {' '.join(categories)}\n"
        f"Revenue {' '.join(values)}"
    )

    match = verify(
        passage,
        candidate(
            passage,
            categories=categories,
            series_specs=[("Revenue", values, None)],
        ),
    )

    assert match is not None
    assert [row[0] for row in match.table.rows] == categories


def test_revenue_and_costs_convert_to_exact_verified_table() -> None:
    passage = (
        "Period 2024A 2025E 2026E\n"
        "Revenue 10,131 12,324 13,533\n"
        "Costs 7,200 8,150 9,100"
    )
    proposed = candidate(
        passage,
        series_specs=[
            ("Revenue", ["10,131", "12,324", "13,533"], None),
            ("Costs", ["7,200", "8,150", "9,100"], None),
        ],
    )

    match = verify(passage, proposed)

    assert match is not None
    assert match.table.columns == ["Period", "Revenue", "Costs"]
    assert match.table.rows == [
        ["2024A", "10,131", "7,200"],
        ["2025E", "12,324", "8,150"],
        ["2026E", "13,533", "9,100"],
    ]
    assert match.table.source_texts == passage.splitlines()


def test_clean_budget_horizontal_table_verifies_without_normalization() -> None:
    passage = (
        "Period 2026B 2027E 2028E 2029E 2030E\n"
        "Revenue 10.1 12.3 14.6 16.0 18.4\n"
        "Costs 7.2 8.5 9.4 10.1 11.3"
    )
    categories = ["2026B", "2027E", "2028E", "2029E", "2030E"]
    proposed = candidate(
        passage,
        categories=categories,
        series_specs=[
            ("Revenue", ["10.1", "12.3", "14.6", "16.0", "18.4"], None),
            ("Costs", ["7.2", "8.5", "9.4", "10.1", "11.3"], None),
        ],
    )

    match = verify(passage, proposed)

    assert match is not None
    assert [row[0] for row in match.table.rows] == categories
    assert match.table.rows[0] == ["2026B", "10.1", "7.2"]
    assert "2026 Budget" not in str(match.table.rows)


def test_interleaved_budget_structure_without_category_label_still_rejects() -> None:
    passage = (
        "2026B 2027E 2028E 2029E 2030E\n"
        "8.1%\n"
        "(0.1%)\n"
        "(9.4%)\n"
        "FTEs by division\n"
        "Management 3.0 3.0 3.0 3.0 3.0"
    )
    proposed = candidate(
        passage,
        categories=["2026B", "2027E", "2028E", "2029E", "2030E"],
        series_specs=[
            ("Management", ["3.0", "3.0", "3.0", "3.0", "3.0"], None)
        ],
    )

    assert verify(passage, proposed) is None


def test_explicit_mixed_units_are_preserved_in_column_labels() -> None:
    passage = (
        "Period 2024A 2025E 2026E\n"
        "Revenue EURm 10,131 12,324 13,533\n"
        "EBITDA margin % 15.6% 15.7% 16.1%\n"
        "Headcount FTE 100 110 120"
    )
    proposed = candidate(
        passage,
        series_specs=[
            ("Revenue", ["10,131", "12,324", "13,533"], "EURm"),
            ("EBITDA margin", ["15.6%", "15.7%", "16.1%"], "%"),
            ("Headcount", ["100", "110", "120"], "FTE"),
        ],
    )

    match = verify(passage, proposed)

    assert match is not None
    assert match.table.columns == [
        "Period",
        "Revenue — EURm",
        "EBITDA margin — %",
        "Headcount — FTE",
    ]


@pytest.mark.parametrize(
    "values",
    [
        ["-1,200", "(1,100)", "+900"],
        ["15.6%", "15.7%", "16.1%"],
        ["€10.5", "$12.4", "£13.6"],
        ["1.2x", "1.4x", "1.5x"],
        ["EUR 10.5", "EUR 11.2", "EUR 12.1"],
    ],
)
def test_exact_numeric_value_forms_remain_strings(values: list[str]) -> None:
    passage = f"Period 2024A 2025E 2026E\nMetric {' '.join(values)}"

    match = verify(
        passage,
        candidate(
            passage,
            series_specs=[("Metric", values, None)],
        ),
    )

    assert match is not None
    assert [row[1] for row in match.table.rows] == values
    assert all(isinstance(row[1], str) for row in match.table.rows)


def test_fifteen_periods_five_series_and_seventy_five_points_verify() -> None:
    categories = [f"{2010 + index}A" for index in range(15)]
    specs = [
        (
            f"Series {series_index}",
            [str(series_index * 100 + index) for index in range(15)],
            None,
        )
        for series_index in range(5)
    ]
    lines = [f"Period {' '.join(categories)}"] + [
        f"{label} {' '.join(values)}" for label, values, _ in specs
    ]
    passage = "\n".join(lines)

    match = verify(
        passage,
        candidate(passage, categories=categories, series_specs=specs),
    )

    assert match is not None
    assert len(match.table.rows) == 15
    assert len(match.table.columns) == 6
    assert sum(len(row) for row in match.table.rows) == 90


@pytest.mark.parametrize(
    ("passage", "categories"),
    [
        ("Period North South\nRevenue 10 12", ["North", "South"]),
        ("Period 2024A 2024A\nRevenue 10 12", ["2024A", "2024A"]),
        ("Period 2024A 2025E\nRevenue 10 12", ["2025E", "2024A"]),
        ("Period 2024A 2025E\nRevenue 10 12", ["2024", "2025"]),
        (
            "Period 2026 Budget 2027E\nRevenue 10 12",
            ["2026 Budget", "2027E"],
        ),
    ],
)
def test_generic_duplicate_reordered_or_normalized_categories_reject(
    passage: str,
    categories: list[str],
) -> None:
    proposed = candidate(
        passage,
        categories=categories,
        series_specs=[("Revenue", ["10", "12"], None)],
    )

    assert verify(passage, proposed) is None


def test_missing_or_extra_value_rejects_complete_candidate() -> None:
    passage = (
        "Period 2024A 2025E 2026E\n"
        "Revenue 10 12 14\n"
        "Margin 15% 16%"
    )
    proposed = candidate(
        passage,
        series_specs=[
            ("Revenue", ["10", "12", "14"], None),
            ("Margin", ["15%", "16%"], None),
        ],
    )

    assert verify(passage, proposed) is None


@pytest.mark.parametrize(
    "series_values",
    [
        ["10", "14", "12"],
        ["10", "12", "15"],
        ["+10", "12", "14"],
        ["10%", "12", "14"],
    ],
)
def test_reordered_or_changed_values_reject(series_values: list[str]) -> None:
    passage = "Period 2024A 2025E 2026E\nRevenue 10 12 14"
    proposed = candidate(
        passage,
        series_specs=[("Revenue", series_values, None)],
    )

    assert verify(passage, proposed) is None


def test_value_cannot_drop_source_sign_or_accounting_punctuation() -> None:
    passage = "Period 2024A 2025E\nRevenue -10 (12)"
    proposed = candidate(
        passage,
        categories=["2024A", "2025E"],
        series_specs=[("Revenue", ["10", "12"], None)],
    )

    assert verify(passage, proposed) is None


def test_inferred_or_omitted_explicit_unit_rejects() -> None:
    passage = "Period 2024A 2025E\nRevenue EURm 10 12"

    omitted = candidate(
        passage,
        categories=["2024A", "2025E"],
        series_specs=[("Revenue", ["10", "12"], None)],
    )
    inferred = candidate(
        "Period 2024A 2025E\nRevenue 10 12",
        categories=["2024A", "2025E"],
        series_specs=[("Revenue", ["10", "12"], "EURm")],
    )

    assert verify(passage, omitted) is None
    assert verify(
        "Period 2024A 2025E\nRevenue 10 12",
        inferred,
    ) is None


def test_whitespace_normalized_spans_recover_original_lines() -> None:
    passage = "Period\t2024A   2025E\r\nRevenue\t10   12"
    proposed = EvidenceParallelSeriesCandidate(
        file_id="file-A",
        passage_index=0,
        category_label="Period",
        categories=["2024A", "2025E"],
        category_source_span="Period 2024A 2025E",
        series=[
            EvidenceSeriesCandidate(
                label="Revenue",
                values=["10", "12"],
                source_span="Revenue 10 12",
            )
        ],
    )

    match = verify(passage, proposed)

    assert match is not None
    assert match.table.source_texts == [
        "Period\t2024A   2025E",
        "Revenue\t10   12",
    ]


def test_flattened_or_noncontiguous_sequences_reject() -> None:
    flattened = "Period 2024A 2025E Revenue 10 12"
    flattened_candidate = EvidenceParallelSeriesCandidate(
        file_id="file-A",
        passage_index=0,
        category_label="Period",
        categories=["2024A", "2025E"],
        category_source_span="Period 2024A 2025E",
        series=[
            EvidenceSeriesCandidate(
                label="Revenue",
                values=["10", "12"],
                source_span="Revenue 10 12",
            )
        ],
    )
    noncontiguous = "Period 2024A 2025E\nNote\nRevenue 10 12"

    assert verify(flattened, flattened_candidate) is None
    assert verify(
        noncontiguous,
        candidate(
            noncontiguous,
            categories=["2024A", "2025E"],
            series_specs=[("Revenue", ["10", "12"], None)],
        ),
    ) is None


def test_adjacent_unclaimed_numeric_series_rejects_partial_table() -> None:
    passage = (
        "Period 2024A 2025E 2026E\n"
        "Revenue 10 12 14\n"
        "Costs 7 8 9"
    )
    proposed = candidate(
        passage,
        series_specs=[("Revenue", ["10", "12", "14"], None)],
    )

    assert verify(passage, proposed) is None


def test_competing_period_sequence_proposed_as_values_rejects() -> None:
    passage = "Period 2024A 2025E\nOther 2026 2027"
    proposed = candidate(
        passage,
        categories=["2024A", "2025E"],
        series_specs=[("Other", ["2026", "2027"], None)],
    )

    assert verify(passage, proposed) is None


def test_unlabelled_adjacent_percentage_sequence_rejects() -> None:
    passage = (
        "Period 2024A 2025E 2026E\n"
        "Revenue 10 12 14\n"
        "15.6% 15.7% 16.1%"
    )

    assert verify(passage, candidate(passage)) is None


def test_wrong_source_passage_or_bounded_scope_rejects() -> None:
    passage = "Period 2024A 2025E 2026E\nRevenue 10,131 12,324 13,533"
    wrong_file = candidate(passage, file_id="file-B")
    wrong_passage = candidate(passage, passage_index=1)
    scoped = passage.splitlines()[0]

    assert verify(passage, wrong_file) is None
    assert verify(passage, wrong_passage) is None
    assert verify(passage, scoped_text=scoped) is None


def test_blank_line_breaks_the_candidate_block() -> None:
    passage = (
        "Period 2024A 2025E 2026E\n\n"
        "Revenue 10,131 12,324 13,533"
    )

    assert verify(passage, candidate(passage)) is None
