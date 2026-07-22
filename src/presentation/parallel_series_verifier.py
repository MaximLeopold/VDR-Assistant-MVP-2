"""Verify explicit horizontal financial series against cited raw evidence."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from src.schemas.evidence import SourceReference
from src.schemas.evidence_presentation import (
    MAX_CANDIDATE_TABLE_CELLS,
    MAX_CANDIDATE_TABLE_COLUMNS,
    MAX_CANDIDATE_TABLE_ROWS,
    MAX_PARALLEL_CATEGORIES,
    MAX_PARALLEL_DATA_POINTS,
    MAX_PARALLEL_SERIES,
    MAX_PARALLEL_VALUES_PER_SERIES,
    EvidenceParallelSeriesCandidate,
    VerifiedEvidenceTable,
)


MAX_PARALLEL_SOURCE_SPAN_CHARS = 2000
MAX_PARALLEL_FIELD_CHARS = 200

_FINANCIAL_CATEGORY_PATTERN = (
    r"(?:"
    r"(?:19|20)\d{2}(?:PF|[ABEF])?"
    r"|FY[ \t]*(?:(?:19|20)\d{2}|\d{2})(?:PF|[ABEF])?"
    r"|(?:Q[1-4]|H[12])[ \t]+(?:(?:19|20)\d{2}|\d{2})(?:PF|[AEF])?"
    r"|LTM|NTM|Actual|Estimate|Forecast|Budget|Plan"
    r"|Base|Upside|Downside"
    r")"
)
_FINANCIAL_CATEGORY_RE = re.compile(
    rf"{_FINANCIAL_CATEGORY_PATTERN}\Z",
    re.IGNORECASE,
)
_FINANCIAL_CATEGORY_TOKEN_RE = re.compile(
    rf"(?<![\w]){_FINANCIAL_CATEGORY_PATTERN}(?![\w])",
    re.IGNORECASE,
)
_NUMBER_CORE = r"\d+(?:[.,/'\N{RIGHT SINGLE QUOTATION MARK}]\d+)*"
_VALUE_RE = re.compile(
    rf"(?:"
    rf"(?:[$\N{{EURO SIGN}}\N{{POUND SIGN}}\N{{YEN SIGN}}][ \t]*)?"
    rf"(?:[A-Z]{{3}}(?:k|m|mn|bn|b)?[ \t]+)?"
    rf"(?:\([-+]?{_NUMBER_CORE}\)|[-+]?{_NUMBER_CORE})"
    rf"(?:[ \t]?(?:%|x|times))?"
    rf")\Z",
    re.IGNORECASE,
)
_NUMERIC_TOKEN_RE = re.compile(
    rf"(?<![\w])(?:\([-+]?{_NUMBER_CORE}\)|[-+]?{_NUMBER_CORE})"
    rf"(?:[ \t]?(?:%|x))?(?![\w])",
    re.IGNORECASE,
)
_UNIT_RE = re.compile(
    r"(?:"
    r"[%$\N{EURO SIGN}\N{POUND SIGN}\N{YEN SIGN}]"
    r"|(?:EUR|USD|GBP|CHF|JPY|CNY|RMB|AUD|CAD|SEK|NOK|DKK)"
    r"(?:[ \t]?(?:k|m|mn|bn|b|thousand|million|billion))?"
    r"|k|m|mn|bn|b|000s|thousand|million|billion"
    r"|percent|percentage|bps|basis[ \t]+points|x|times"
    r"|FTE|employees?|people|headcount|tonnes?|tons?|kg|g"
    r"|mw|mwh|kw|kwh"
    r")\Z",
    re.IGNORECASE,
)
_SAFE_RESIDUE_RE = re.compile(r"[ \t|:;,=/\-\N{EN DASH}\N{EM DASH}]*\Z")


class _RecoveredSpan(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    text: str
    start: int
    end: int


class VerifiedParallelSeriesMatch(BaseModel):
    """One locally verified converted table with transient source ordering."""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_id: str
    passage_index: int
    table: VerifiedEvidenceTable
    source_start: int
    source_end: int
    candidate_index: int


def _normalize_whitespace_with_spans(
    text: str,
) -> tuple[str, list[tuple[int, int]]]:
    normalized: list[str] = []
    source_spans: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            start = index
            while index < len(text) and text[index].isspace():
                index += 1
            if normalized and index < len(text):
                normalized.append(" ")
                source_spans.append((start, index))
            continue
        normalized.append(text[index])
        source_spans.append((index, index + 1))
        index += 1
    return "".join(normalized), source_spans


def _recover_source_span(
    candidate_span: str,
    passage: str,
    *,
    start_at: int = 0,
) -> _RecoveredSpan | None:
    if (
        not isinstance(candidate_span, str)
        or not candidate_span.strip()
        or len(candidate_span) > MAX_PARALLEL_SOURCE_SPAN_CHARS
        or not isinstance(passage, str)
        or not passage
        or start_at < 0
        or start_at > len(passage)
    ):
        return None

    exact_start = passage.find(candidate_span, start_at)
    if exact_start >= 0:
        if passage.find(candidate_span, exact_start + 1) >= 0:
            return None
        exact_end = exact_start + len(candidate_span)
        return _RecoveredSpan(
            text=passage[exact_start:exact_end],
            start=exact_start,
            end=exact_end,
        )

    normalized_candidate, _ = _normalize_whitespace_with_spans(candidate_span)
    if not normalized_candidate:
        return None
    suffix = passage[start_at:]
    normalized_passage, source_spans = _normalize_whitespace_with_spans(suffix)
    normalized_start = normalized_passage.find(normalized_candidate)
    if normalized_start < 0:
        return None
    if normalized_passage.find(normalized_candidate, normalized_start + 1) >= 0:
        return None
    normalized_end = normalized_start + len(normalized_candidate) - 1
    source_start = start_at + source_spans[normalized_start][0]
    source_end = start_at + source_spans[normalized_end][1]
    return _RecoveredSpan(
        text=passage[source_start:source_end],
        start=source_start,
        end=source_end,
    )


def _candidate_passage(
    file_id: str,
    passage_index: int,
    sources: list[SourceReference],
    passage_scope: dict[tuple[str, int], str] | None,
) -> tuple[str, str] | None:
    if passage_scope is None or not file_id or file_id.strip() != file_id:
        return None
    matching = [source for source in sources if source.file_id == file_id]
    if len(matching) != 1 or passage_index < 0:
        return None
    source = matching[0]
    if passage_index >= len(source.evidence):
        return None
    passage = source.evidence[passage_index]
    scope = passage_scope.get((file_id, passage_index))
    if (
        not isinstance(passage, str)
        or not passage
        or not isinstance(scope, str)
        or not scope
        or not passage.startswith(scope)
    ):
        return None
    return passage, scope


def _is_in_scope(span: _RecoveredSpan, scope: str) -> bool:
    return span.end <= len(scope)


def _same_line_surroundings(
    passage: str,
    span: _RecoveredSpan,
) -> tuple[str, str]:
    line_start = max(
        passage.rfind("\n", 0, span.start),
        passage.rfind("\r", 0, span.start),
    ) + 1
    endings = [
        position
        for position in (
            passage.find("\n", span.end),
            passage.find("\r", span.end),
        )
        if position >= 0
    ]
    line_end = min(endings) if endings else len(passage)
    return passage[line_start:span.start], passage[span.end:line_end]


def _is_complete_logical_line(passage: str, span: _RecoveredSpan) -> bool:
    if "\n" in span.text or "\r" in span.text:
        return False
    before, after = _same_line_surroundings(passage, span)
    return not before.strip() and not after.strip()


def _is_clean_field(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and len(value) <= MAX_PARALLEL_FIELD_CHARS
        and "\n" not in value
        and "\r" not in value
    )


def _has_field_boundaries(text: str, start: int, end: int) -> bool:
    if start > 0 and text[start - 1].isalnum() and text[start].isalnum():
        return False
    if end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
        return False
    return True


def _ordered_positions(
    text: str,
    fields: list[str],
    *,
    start_at: int = 0,
) -> list[tuple[int, int]] | None:
    positions: list[tuple[int, int]] = []
    cursor = start_at
    for field in fields:
        position = text.find(field, cursor)
        while position >= 0 and not _has_field_boundaries(
            text,
            position,
            position + len(field),
        ):
            position = text.find(field, position + 1)
        if position < 0:
            return None
        end = position + len(field)
        positions.append((position, end))
        cursor = end
    return positions


def _residue_is_safe(
    text: str,
    positions: list[tuple[int, int]],
) -> bool:
    ordered = sorted(positions)
    if any(previous[1] > current[0] for previous, current in zip(ordered, ordered[1:])):
        return False
    cursor = 0
    residue: list[str] = []
    for start, end in ordered:
        residue.append(text[cursor:start])
        cursor = end
    residue.append(text[cursor:])
    return _SAFE_RESIDUE_RE.fullmatch("".join(residue)) is not None


def _value_position_is_complete(
    text: str,
    position: tuple[int, int],
) -> bool:
    start, end = position
    if start > 0 and text[start - 1] in "+-(":
        return False
    if end < len(text) and text[end] in "%)xX":
        return False
    if (
        end + 1 < len(text)
        and text[end] in ".,/'\N{RIGHT SINGLE QUOTATION MARK}"
        and text[end + 1].isdigit()
    ):
        return False
    return True


def _line_index(passage: str, position: int) -> int:
    prefix = passage[:position].replace("\r\n", "\n").replace("\r", "\n")
    return prefix.count("\n")


def _single_line_break_between(
    passage: str,
    first: _RecoveredSpan,
    second: _RecoveredSpan,
) -> bool:
    gap = passage[first.end:second.start]
    normalized = gap.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace(" ", "").replace("\t", "")
    return normalized == "\n"


def _line_at(passage: str, line_index: int) -> str | None:
    lines = passage.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if 0 <= line_index < len(lines):
        return lines[line_index]
    return None


def _looks_like_table_line(line: str | None) -> bool:
    if line is None or not line.strip() or len(line) > MAX_PARALLEL_SOURCE_SPAN_CHARS:
        return False
    stripped = line.strip()
    if stripped.endswith((".", "?", "!")):
        return False
    return (
        len(_FINANCIAL_CATEGORY_TOKEN_RE.findall(stripped)) >= 2
        or len(_NUMERIC_TOKEN_RE.findall(stripped)) >= 2
    )


def _verify_category_line(
    candidate: EvidenceParallelSeriesCandidate,
    passage: str,
    scope: str,
) -> _RecoveredSpan | None:
    categories = candidate.categories
    if (
        not (2 <= len(categories) <= MAX_PARALLEL_CATEGORIES)
        or not _is_clean_field(candidate.category_label)
        or any(not _is_clean_field(category) for category in categories)
        or any(
            _FINANCIAL_CATEGORY_RE.fullmatch(category) is None
            for category in categories
        )
        or len(set(categories)) != len(categories)
    ):
        return None
    recovered = _recover_source_span(candidate.category_source_span, passage)
    if (
        recovered is None
        or not _is_in_scope(recovered, scope)
        or not _is_complete_logical_line(passage, recovered)
    ):
        return None
    positions = _ordered_positions(
        recovered.text,
        [candidate.category_label, *categories],
    )
    if positions is None or not _residue_is_safe(recovered.text, positions):
        return None
    return recovered


def _verify_series_line(
    label: str,
    values: list[str],
    unit: str | None,
    source_span: str,
    passage: str,
    scope: str,
    *,
    start_at: int,
) -> _RecoveredSpan | None:
    if (
        not _is_clean_field(label)
        or not (2 <= len(values) <= MAX_PARALLEL_VALUES_PER_SERIES)
        or any(not _is_clean_field(value) for value in values)
        or any(_VALUE_RE.fullmatch(value) is None for value in values)
        or sum(
            _FINANCIAL_CATEGORY_RE.fullmatch(value) is not None
            for value in values
        )
        >= 2
        or (unit is not None and (
            not _is_clean_field(unit) or _UNIT_RE.fullmatch(unit) is None
        ))
    ):
        return None
    recovered = _recover_source_span(source_span, passage, start_at=start_at)
    if (
        recovered is None
        or not _is_in_scope(recovered, scope)
        or not _is_complete_logical_line(passage, recovered)
    ):
        return None

    label_positions = _ordered_positions(recovered.text, [label])
    if label_positions is None:
        return None
    label_position = label_positions[0]
    value_positions = _ordered_positions(
        recovered.text,
        values,
        start_at=label_position[1],
    )
    if value_positions is None:
        return None
    if any(
        not _value_position_is_complete(recovered.text, position)
        for position in value_positions
    ):
        return None
    positions = [label_position, *value_positions]
    if unit is not None:
        unit_positions = _ordered_positions(
            recovered.text,
            [unit],
            start_at=label_position[1],
        )
        if unit_positions is None or unit_positions[0][1] > value_positions[0][0]:
            return None
        positions.append(unit_positions[0])
    if not _residue_is_safe(recovered.text, positions):
        return None
    return recovered


def _convert_to_table(
    candidate: EvidenceParallelSeriesCandidate,
    category_line: str,
    series_lines: list[str],
) -> VerifiedEvidenceTable:
    columns = [candidate.category_label]
    for series in candidate.series:
        columns.append(
            series.label
            if series.unit is None
            else f"{series.label} — {series.unit}"
        )
    rows = [
        [
            category,
            *(series.values[index] for series in candidate.series),
        ]
        for index, category in enumerate(candidate.categories)
    ]
    return VerifiedEvidenceTable(
        title=None,
        columns=columns,
        rows=rows,
        source_texts=[category_line, *series_lines],
    )


def verify_parallel_series_candidate(
    candidate: EvidenceParallelSeriesCandidate,
    sources: list[SourceReference],
    *,
    passage_scope: dict[tuple[str, int], str] | None = None,
    candidate_index: int = 0,
) -> VerifiedParallelSeriesMatch | None:
    """Verify and convert one complete explicit horizontal financial table."""

    source_match = _candidate_passage(
        candidate.file_id,
        candidate.passage_index,
        sources,
        passage_scope,
    )
    if source_match is None:
        return None
    passage, scope = source_match
    if (
        not (1 <= len(candidate.series) <= MAX_PARALLEL_SERIES)
        or any(
            len(series.values) != len(candidate.categories)
            for series in candidate.series
        )
        or sum(len(series.values) for series in candidate.series)
        > MAX_PARALLEL_DATA_POINTS
    ):
        return None

    category = _verify_category_line(candidate, passage, scope)
    if category is None:
        return None

    series_spans: list[_RecoveredSpan] = []
    cursor = category.end
    for series in candidate.series:
        verified = _verify_series_line(
            series.label,
            series.values,
            series.unit,
            series.source_span,
            passage,
            scope,
            start_at=cursor,
        )
        if verified is None:
            return None
        series_spans.append(verified)
        cursor = verified.end

    all_spans = [category, *series_spans]
    line_indexes = [_line_index(passage, span.start) for span in all_spans]
    if line_indexes != list(range(line_indexes[0], line_indexes[0] + len(all_spans))):
        return None
    if any(
        not _single_line_break_between(passage, first, second)
        for first, second in zip(all_spans, all_spans[1:])
    ):
        return None

    columns = [
        candidate.category_label,
        *(
            series.label
            if series.unit is None
            else f"{series.label} — {series.unit}"
            for series in candidate.series
        ),
    ]
    if (
        len({column.casefold() for column in columns}) != len(columns)
        or len(candidate.categories) > MAX_CANDIDATE_TABLE_ROWS
        or len(columns) > MAX_CANDIDATE_TABLE_COLUMNS
        or len(candidate.categories) * len(columns) > MAX_CANDIDATE_TABLE_CELLS
    ):
        return None

    before_line = _line_at(passage, line_indexes[0] - 1)
    after_line = _line_at(passage, line_indexes[-1] + 1)
    if _looks_like_table_line(before_line) or _looks_like_table_line(after_line):
        return None

    table = _convert_to_table(
        candidate,
        category.text,
        [span.text for span in series_spans],
    )
    return VerifiedParallelSeriesMatch(
        file_id=candidate.file_id,
        passage_index=candidate.passage_index,
        table=table,
        source_start=category.start,
        source_end=series_spans[-1].end,
        candidate_index=candidate_index,
    )
