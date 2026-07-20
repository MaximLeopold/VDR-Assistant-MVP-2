"""Extract retrieved passages from completed OpenAI File Search calls."""

from src.schemas.evidence import RetrievedSearchResult


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_score(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def extract_search_results(
    response: object,
) -> list[RetrievedSearchResult]:
    """Return File Search results in response and result order."""

    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return []

    extracted: list[RetrievedSearchResult] = []

    for item in output:
        if getattr(item, "type", None) != "file_search_call":
            continue
        if getattr(item, "status", None) != "completed":
            continue

        results = getattr(item, "results", None)
        if not isinstance(results, list):
            continue

        for result in results:
            extracted.append(
                RetrievedSearchResult(
                    file_id=_optional_text(
                        getattr(result, "file_id", None)
                    ),
                    filename=_optional_text(
                        getattr(result, "filename", None)
                    ),
                    text=_optional_text(getattr(result, "text", None)),
                    score=_optional_score(getattr(result, "score", None)),
                )
            )

    return extracted
