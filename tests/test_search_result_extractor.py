from types import SimpleNamespace

import pytest

from src.retrieval.search_result_extractor import extract_search_results
from src.schemas.evidence import RetrievedSearchResult


def result(
    file_id: str | None = "file-A",
    filename: str | None = "report.pdf",
    text: str | None = "Retrieved passage",
    score: float | None = 0.8,
):
    return SimpleNamespace(
        file_id=file_id,
        filename=filename,
        text=text,
        score=score,
    )


def search_call(status: str = "completed", results=None):
    return SimpleNamespace(
        type="file_search_call",
        status=status,
        results=results,
    )


def response_with(*output):
    return SimpleNamespace(output=list(output))


def test_extracts_one_completed_result_with_optional_fields() -> None:
    extracted = extract_search_results(
        response_with(search_call(results=[result()]))
    )

    assert extracted == [
        RetrievedSearchResult(
            file_id="file-A",
            filename="report.pdf",
            text="Retrieved passage",
            score=0.8,
        )
    ]


def test_flattens_calls_and_preserves_output_and_result_order() -> None:
    extracted = extract_search_results(
        response_with(
            search_call(
                results=[
                    result("file-B", "b.pdf", "B1", 0.9),
                    result("file-A", "a.pdf", "A1", 0.7),
                ]
            ),
            SimpleNamespace(type="message"),
            search_call(
                results=[result("file-B", "b.pdf", "B2", 0.6)]
            ),
        )
    )

    assert [item.text for item in extracted] == ["B1", "A1", "B2"]


@pytest.mark.parametrize("results", [None, [], (), "malformed"])
def test_missing_empty_or_non_list_results_are_ignored(results) -> None:
    assert extract_search_results(
        response_with(search_call(results=results))
    ) == []


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(),
        SimpleNamespace(output=None),
        SimpleNamespace(output=()),
        SimpleNamespace(output="malformed"),
    ],
)
def test_missing_or_non_list_output_returns_no_results(response) -> None:
    assert extract_search_results(response) == []


def test_missing_result_fields_are_retained_safely() -> None:
    extracted = extract_search_results(
        response_with(
            search_call(
                results=[
                    SimpleNamespace(),
                    result(file_id=None),
                    result(filename=None),
                    result(text=None),
                    result(score=None),
                ]
            )
        )
    )

    assert extracted[0] == RetrievedSearchResult()
    assert extracted[1].file_id is None
    assert extracted[2].filename is None
    assert extracted[3].text is None
    assert extracted[4].score is None


def test_malformed_optional_result_fields_degrade_to_none() -> None:
    malformed = SimpleNamespace(
        file_id=object(),
        filename=42,
        text=["not text"],
        score="not a score",
    )

    assert extract_search_results(
        response_with(search_call(results=[malformed]))
    ) == [RetrievedSearchResult()]


@pytest.mark.parametrize(
    "status",
    ["in_progress", "searching", "incomplete", "failed"],
)
def test_non_completed_calls_are_ignored(status: str) -> None:
    assert extract_search_results(
        response_with(search_call(status=status, results=[result()]))
    ) == []


def test_non_file_search_output_is_ignored() -> None:
    response = response_with(
        SimpleNamespace(
            type="message",
            status="completed",
            results=[result()],
        )
    )

    assert extract_search_results(response) == []
