"""Deterministically verify structured evidence against cited raw passages."""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from src.presentation.parallel_series_verifier import (
    verify_parallel_series_candidate,
)
from src.schemas.evidence import SourceReference
from src.schemas.evidence_presentation import (
    MAX_PARALLEL_CANDIDATES,
    EvidenceMetricCandidate,
    EvidencePresentationPassage,
    EvidencePresentationSelection,
    EvidenceTableCandidate,
    VerifiedEvidenceMetric,
    VerifiedEvidencePresentation,
    VerifiedEvidenceTable,
)


MAX_CANDIDATE_METRICS = 12
MAX_CANDIDATE_TABLES = 4

MAX_METRIC_SOURCE_SPAN_CHARS = 200
MAX_PRESENTATION_FIELD_CHARS = 200
MAX_METRIC_FIELD_GAP_CHARS = 80
MAX_METRIC_FIELD_GAP_WORDS = 4

MAX_VERIFIED_METRICS_PER_PASSAGE = 4
MAX_VERIFIED_METRICS_PER_SOURCE = 6
MAX_VERIFIED_METRICS_PER_ANSWER = 10

MAX_VERIFIED_TABLES_PER_PASSAGE = 1
MAX_VERIFIED_TABLES_PER_SOURCE = 2
MAX_VERIFIED_TABLES_PER_ANSWER = 3

MAX_VERIFIED_COMPONENTS_PER_ANSWER = 12
MAX_VERIFIED_TABLE_ROWS = 15
MAX_VERIFIED_TABLE_COLUMNS = 6
MAX_VERIFIED_TABLE_CELLS = 90


_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_NUMERIC_CORE = (
    r"(?:FY\s*)?\d+(?:[.,/'\N{RIGHT SINGLE QUOTATION MARK}]\d+)*"
)
_NUMERIC_TOKEN_RE = re.compile(
    rf"(?<![\w])(?:\({_NUMERIC_CORE}\)|[-+]?{_NUMERIC_CORE})(?![\w])"
)
_NUMERIC_FIELD_RE = re.compile(
    rf"(?:\({_NUMERIC_CORE}\)|[-+]?{_NUMERIC_CORE})\Z"
)
_UNIT_TOKEN_RE = re.compile(
    r"[%\N{EURO SIGN}$\N{POUND SIGN}\N{YEN SIGN}]"
    r"|\b(?:EUR|USD|GBP|CHF|JPY|CNY|RMB|AUD|CAD|SEK|NOK|DKK)"
    r"(?:[kKmMbBnN])?\b"
    r"|\b(?:thousand|million|billion|percent|percentage|bps"
    r"|basis[ \t]+points|employees?|people|headcount|tonnes?|tons?"
    r"|kg|g|mw|mwh|kw|kwh|times)\b",
    re.IGNORECASE,
)
_UNIT_FIELD_RE = re.compile(
    r"(?:[%\N{EURO SIGN}$\N{POUND SIGN}\N{YEN SIGN}]"
    r"|(?:EUR|USD|GBP|CHF|JPY|CNY|RMB|AUD|CAD|SEK|NOK|DKK)"
    r"(?:[ \t]?(?:k|m|mn|bn|b|thousand|million|billion))?"
    r"|k|m|mn|bn|b|thousand|million|billion|percent|percentage"
    r"|bps|basis[ \t]+points|employees?|people|headcount"
    r"|tonnes?|tons?|kg|g|mw|mwh|kw|kwh|x|times)",
    re.IGNORECASE,
)
_PERIOD_FIELD_RE = re.compile(
    r"(?:"
    r"(?:FY[ \t]*)?(?:19|20)\d{2}(?:[AEF])?"
    r"|(?:19|20)\d{2}[/-](?:\d{2}|(?:19|20)\d{2})"
    r"|(?:Q[1-4]|H[12])(?:[ \t]*(?:FY[ \t]*)?(?:19|20)\d{2})?"
    r"|\d{1,2}[./-]\d{1,2}[./-](?:\d{2}|\d{4})"
    r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May"
    r"|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?"
    r"|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[ \t]+(?:19|20)\d{2}"
    r"|current|prior|previous|actual|forecast|budget|plan|ltm|ntm|ytd"
    r")",
    re.IGNORECASE,
)
_SCENARIO_HEADER_RE = re.compile(
    r"(?:base|upside|downside|low|high|best(?:[ \t]+case)?"
    r"|worst(?:[ \t]+case)?)",
    re.IGNORECASE,
)
_GENERIC_CURRENCY_CODE_RE = re.compile(r"[A-Z]{3}")
_TABLE_UNIT_TOKEN_RE = re.compile(
    _UNIT_TOKEN_RE.pattern + r"|\b(?-i:[A-Z]{3})\b",
    re.IGNORECASE,
)
_SAFE_METRIC_CONNECTORS = frozenset(
    {"as", "at", "for", "in", "is", "of", "to", "was"}
)
_UNIT_WORDS_ALLOWED_AS_LABELS = frozenset(
    {"employee", "employees", "headcount", "people"}
)


class VerifiedMetricMatch(BaseModel):
    """A verified metric associated with one cited source passage."""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_id: str
    passage_index: int
    metric: VerifiedEvidenceMetric


class VerifiedTableMatch(BaseModel):
    """A verified table associated with one cited source passage."""

    model_config = ConfigDict(strict=True, extra="forbid")

    file_id: str
    passage_index: int
    table: VerifiedEvidenceTable


class _RecoveredSpan(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    text: str
    start: int
    end: int


class _VerifiedMetricWithPosition(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    match: VerifiedMetricMatch
    source_start: int
    source_end: int
    candidate_index: int


class _VerifiedTableWithPosition(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    match: VerifiedTableMatch
    source_start: int
    source_end: int
    candidate_index: int
    origin_priority: int = 0


def _normalize_whitespace_with_spans(
    text: str,
) -> tuple[str, list[tuple[int, int]]]:
    """Collapse whitespace while retaining source offsets for every character."""

    normalized_characters: list[str] = []
    source_spans: list[tuple[int, int]] = []
    index = 0

    while index < len(text):
        if text[index].isspace():
            whitespace_start = index
            while index < len(text) and text[index].isspace():
                index += 1

            if normalized_characters and index < len(text):
                normalized_characters.append(" ")
                source_spans.append((whitespace_start, index))
            continue

        normalized_characters.append(text[index])
        source_spans.append((index, index + 1))
        index += 1

    return "".join(normalized_characters), source_spans


def _collapse_whitespace(text: str) -> str:
    normalized, _ = _normalize_whitespace_with_spans(text)
    return normalized


def _has_blank_line(text: str) -> bool:
    normalized_newlines = text.replace("\r\n", "\n").replace("\r", "\n")
    return _BLANK_LINE_RE.search(normalized_newlines) is not None


def _recover_source_span(
    candidate_span: str,
    passage: str,
    *,
    start_at: int = 0,
) -> _RecoveredSpan | None:
    """Recover an exact or whitespace-normalized contiguous source span."""

    if not isinstance(candidate_span, str) or not candidate_span.strip():
        return None
    if not isinstance(passage, str) or not passage:
        return None
    if start_at < 0 or start_at > len(passage):
        return None

    exact_start = passage.find(candidate_span, start_at)
    if exact_start >= 0:
        exact_end = exact_start + len(candidate_span)
        return _RecoveredSpan(
            text=passage[exact_start:exact_end],
            start=exact_start,
            end=exact_end,
        )

    normalized_candidate = _collapse_whitespace(candidate_span)
    if not normalized_candidate:
        return None

    passage_suffix = passage[start_at:]
    normalized_passage, source_spans = _normalize_whitespace_with_spans(
        passage_suffix
    )
    normalized_start = normalized_passage.find(normalized_candidate)
    if normalized_start < 0:
        return None

    normalized_end = normalized_start + len(normalized_candidate) - 1
    source_start = start_at + source_spans[normalized_start][0]
    source_end = start_at + source_spans[normalized_end][1]
    return _RecoveredSpan(
        text=passage[source_start:source_end],
        start=source_start,
        end=source_end,
    )


def _candidate_source(
    file_id: str,
    passage_index: int,
    sources: list[SourceReference],
    passage_scope: dict[tuple[str, int], str] | None = None,
) -> tuple[SourceReference, str] | None:
    if not file_id or file_id.strip() != file_id:
        return None
    if type(passage_index) is not int or passage_index < 0:
        return None

    matching_sources = [source for source in sources if source.file_id == file_id]
    if len(matching_sources) != 1:
        return None

    source = matching_sources[0]
    if passage_index >= len(source.evidence):
        return None

    stored_passage = source.evidence[passage_index]
    if not isinstance(stored_passage, str) or not stored_passage:
        return None

    if passage_scope is None:
        return source, stored_passage

    scoped_passage = passage_scope.get((file_id, passage_index))
    if (
        not isinstance(scoped_passage, str)
        or not scoped_passage
        or not stored_passage.startswith(scoped_passage)
    ):
        return None
    return source, stored_passage


def _span_is_in_scope(
    recovered: _RecoveredSpan,
    file_id: str,
    passage_index: int,
    passage_scope: dict[tuple[str, int], str] | None,
) -> bool:
    if passage_scope is None:
        return True
    scoped_passage = passage_scope.get((file_id, passage_index))
    return scoped_passage is not None and recovered.end <= len(scoped_passage)


def _same_line_surroundings(
    passage: str,
    recovered: _RecoveredSpan,
) -> tuple[str, str]:
    line_start = max(
        passage.rfind("\n", 0, recovered.start),
        passage.rfind("\r", 0, recovered.start),
    ) + 1
    newline_positions = [
        position
        for position in (
            passage.find("\n", recovered.end),
            passage.find("\r", recovered.end),
        )
        if position >= 0
    ]
    line_end = min(newline_positions) if newline_positions else len(passage)
    return (
        passage[line_start:recovered.start],
        passage[recovered.end:line_end],
    )


def _contains_period_or_scenario(text: str) -> bool:
    return (
        _PERIOD_FIELD_RE.search(text) is not None
        or _SCENARIO_HEADER_RE.search(text) is not None
    )


def _has_source_token_boundaries(
    passage: str,
    recovered: _RecoveredSpan,
) -> bool:
    if recovered.start > 0:
        previous = passage[recovered.start - 1]
        if (
            previous.isalnum() or previous == "_"
        ) and (
            recovered.text[0].isalnum() or recovered.text[0] == "_"
        ):
            return False
    if recovered.end < len(passage):
        following = passage[recovered.end]
        if (
            following.isalnum() or following == "_"
        ) and (
            recovered.text[-1].isalnum() or recovered.text[-1] == "_"
        ):
            return False
    return True


def _is_clean_display_field(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and len(value) <= MAX_PRESENTATION_FIELD_CHARS
        and not _has_blank_line(value)
    )


def _has_word_boundary(text: str, start: int, end: int) -> bool:
    first_is_word = text[start].isalnum() or text[start] == "_"
    last_is_word = text[end - 1].isalnum() or text[end - 1] == "_"

    if first_is_word and start > 0:
        previous = text[start - 1]
        if previous.isalnum() or previous == "_":
            return False
    if last_is_word and end < len(text):
        following = text[end]
        if following.isalnum() or following == "_":
            return False
    return True


def _unique_field_position(text: str, field: str) -> tuple[int, int] | None:
    start = text.find(field)
    if start < 0:
        return None
    end = start + len(field)
    if not _has_word_boundary(text, start, end):
        return None

    next_start = text.find(field, start + 1)
    if next_start >= 0:
        return None
    return start, end


def _positions_do_not_overlap(
    positions: Iterable[tuple[int, int]],
) -> bool:
    ordered = sorted(positions)
    return all(
        current_end <= next_start
        for (_, current_end), (next_start, _) in zip(ordered, ordered[1:])
    )


def _covered_by_positions(
    start: int,
    end: int,
    positions: Iterable[tuple[int, int]],
) -> bool:
    return any(
        field_start <= start and end <= field_end
        for field_start, field_end in positions
    )


def _has_uncovered_numeric_or_unit(
    text: str,
    positions: list[tuple[int, int]],
) -> bool:
    matches = [
        *_NUMERIC_TOKEN_RE.finditer(text),
        *_TABLE_UNIT_TOKEN_RE.finditer(text),
    ]
    return any(
        not _covered_by_positions(match.start(), match.end(), positions)
        for match in matches
    )


def _metric_residue_is_safe(
    text: str,
    positions: list[tuple[int, int]],
) -> bool:
    """Allow only neutral connectors outside the exact displayed fields."""

    covered = [False] * len(text)
    for start, end in positions:
        for index in range(start, end):
            covered[index] = True

    residue = "".join(
        " " if covered[index] else character
        for index, character in enumerate(text)
    )
    if any(
        character not in " \t\r\n,:=/|."
        and not character.isalpha()
        for character in residue
    ):
        return False

    return all(
        word.casefold() in _SAFE_METRIC_CONNECTORS
        for word in _WORD_RE.findall(residue)
    )


def _value_is_supported_numeric_expression(value: str) -> bool:
    """Require one exact number plus only explicit unit/currency wording."""

    numeric_matches = list(_NUMERIC_TOKEN_RE.finditer(value))
    if len(numeric_matches) != 1:
        return False
    if _PERIOD_FIELD_RE.fullmatch(value) is not None:
        return False

    covered = [False] * len(value)
    for match in [*numeric_matches, *_TABLE_UNIT_TOKEN_RE.finditer(value)]:
        for index in range(match.start(), match.end()):
            covered[index] = True

    return all(
        covered[index]
        or character.isspace()
        or not character.isalnum()
        for index, character in enumerate(value)
    )


def _label_is_supported(label: str) -> bool:
    if _NUMERIC_TOKEN_RE.search(label) is not None:
        return False
    if _PERIOD_FIELD_RE.search(label) is not None:
        return False
    if _GENERIC_CURRENCY_CODE_RE.fullmatch(label) is not None:
        return False

    unit_match = _UNIT_FIELD_RE.fullmatch(label)
    return (
        unit_match is None
        or label.casefold() in _UNIT_WORDS_ALLOWED_AS_LABELS
    )


def _metric_fields_are_adjacent(
    span: str,
    positions: list[tuple[int, int]],
) -> bool:
    ordered = sorted(positions)
    for (_, current_end), (next_start, _) in zip(ordered, ordered[1:]):
        gap = span[current_end:next_start]
        if len(gap) > MAX_METRIC_FIELD_GAP_CHARS:
            return False
        if len(_WORD_RE.findall(gap)) > MAX_METRIC_FIELD_GAP_WORDS:
            return False
        if any(character in gap for character in ".!?"):
            return False
    return True


def _verify_metric_candidate_with_position(
    candidate: EvidenceMetricCandidate,
    sources: list[SourceReference],
    *,
    candidate_index: int = 0,
    passage_scope: dict[tuple[str, int], str] | None = None,
) -> _VerifiedMetricWithPosition | None:
    source_match = _candidate_source(
        candidate.file_id,
        candidate.passage_index,
        sources,
        passage_scope,
    )
    if source_match is None:
        return None
    _, passage = source_match

    recovered = _recover_source_span(candidate.source_span, passage)
    if recovered is None:
        return None
    if not _span_is_in_scope(
        recovered,
        candidate.file_id,
        candidate.passage_index,
        passage_scope,
    ):
        return None
    if not _has_source_token_boundaries(passage, recovered):
        return None
    if not (1 <= len(recovered.text) <= MAX_METRIC_SOURCE_SPAN_CHARS):
        return None
    if _has_blank_line(recovered.text):
        return None
    if any(
        _has_uncovered_numeric_or_unit(fragment, [])
        or _contains_period_or_scenario(fragment)
        or not _metric_residue_is_safe(fragment, [])
        for fragment in _same_line_surroundings(passage, recovered)
    ):
        return None

    named_fields = [("label", candidate.label), ("value", candidate.value)]
    if candidate.period is not None:
        named_fields.append(("period", candidate.period))
    if candidate.unit is not None:
        named_fields.append(("unit", candidate.unit))
    if not all(_is_clean_display_field(value) for _, value in named_fields):
        return None
    if not any(character.isalpha() for character in candidate.label):
        return None
    if not _label_is_supported(candidate.label):
        return None
    if not _value_is_supported_numeric_expression(candidate.value):
        return None
    if (
        candidate.period is not None
        and _PERIOD_FIELD_RE.fullmatch(candidate.period) is None
    ):
        return None
    if (
        candidate.unit is not None
        and _UNIT_FIELD_RE.fullmatch(candidate.unit) is None
        and _GENERIC_CURRENCY_CODE_RE.fullmatch(candidate.unit) is None
    ):
        return None

    field_positions: dict[str, tuple[int, int]] = {}
    for name, value in named_fields:
        position = _unique_field_position(recovered.text, value)
        if position is None:
            return None
        field_positions[name] = position

    positions = list(field_positions.values())
    if not _positions_do_not_overlap(positions):
        return None
    if not _metric_fields_are_adjacent(recovered.text, positions):
        return None
    if _has_uncovered_numeric_or_unit(recovered.text, positions):
        return None
    if not _metric_residue_is_safe(recovered.text, positions):
        return None

    verified_metric = VerifiedEvidenceMetric(
        label=candidate.label,
        value=candidate.value,
        period=candidate.period,
        unit=candidate.unit,
        source_text=recovered.text,
    )
    return _VerifiedMetricWithPosition(
        match=VerifiedMetricMatch(
            file_id=candidate.file_id,
            passage_index=candidate.passage_index,
            metric=verified_metric,
        ),
        source_start=recovered.start,
        source_end=recovered.end,
        candidate_index=candidate_index,
    )


def verify_metric_candidate(
    candidate: EvidenceMetricCandidate,
    sources: list[SourceReference],
) -> VerifiedMetricMatch | None:
    """Verify one metric candidate against its exact cited raw passage."""

    verified = _verify_metric_candidate_with_position(candidate, sources)
    return None if verified is None else verified.match


def _ordered_exact_positions(
    text: str,
    values: list[str],
) -> list[tuple[int, int]] | None:
    positions: list[tuple[int, int]] = []
    cursor = 0

    for value in values:
        start = text.find(value, cursor)
        if start < 0:
            return None
        end = start + len(value)
        if not _has_word_boundary(text, start, end):
            return None
        positions.append((start, end))
        cursor = end

    return positions


def _residue_contains_document_content(
    text: str,
    positions: list[tuple[int, int]],
) -> bool:
    covered = [False] * len(text)
    for start, end in positions:
        for index in range(start, end):
            covered[index] = True

    for index, character in enumerate(text):
        if covered[index]:
            continue
        if character.isalnum() or character in (
            "%\N{EURO SIGN}$\N{POUND SIGN}\N{YEN SIGN}"
            "+-()<>\N{LESS-THAN OR EQUAL TO}\N{GREATER-THAN OR EQUAL TO}"
            "\N{ALMOST EQUAL TO}~"
        ):
            return True
    return False


def _span_covers_complete_lines(
    passage: str,
    recovered: _RecoveredSpan,
) -> bool:
    before, after = _same_line_surroundings(passage, recovered)
    return not _residue_contains_document_content(
        before,
        [],
    ) and not _residue_contains_document_content(
        after,
        [],
    )


def _is_horizontal_series(columns: list[str]) -> bool:
    return any(
        _NUMERIC_FIELD_RE.fullmatch(column) is not None
        or _PERIOD_FIELD_RE.fullmatch(column) is not None
        or _SCENARIO_HEADER_RE.fullmatch(column) is not None
        for column in columns[1:]
    )


def _unit_markers(text: str) -> frozenset[str]:
    markers: set[str] = set()
    for match in _TABLE_UNIT_TOKEN_RE.finditer(text):
        marker = match.group(0).casefold()
        if marker in {"percent", "percentage"}:
            marker = "%"
        elif marker == "basis points":
            marker = "bps"
        markers.add(marker)
    return frozenset(markers)


def _table_units_are_consistent(
    columns: list[str],
    header_text: str,
    row_texts: list[str],
) -> bool:
    if any(column.casefold() == "unit" for column in columns):
        return True

    header_units = _unit_markers(header_text)
    row_units = [_unit_markers(row_text) for row_text in row_texts]
    if header_units:
        return all(not units or units == header_units for units in row_units)

    nonempty_units = [units for units in row_units if units]
    if not nonempty_units:
        return True
    return len(nonempty_units) == len(row_units) and len(set(nonempty_units)) == 1


def _verify_table_candidate_with_position(
    candidate: EvidenceTableCandidate,
    sources: list[SourceReference],
    *,
    candidate_index: int = 0,
    passage_scope: dict[tuple[str, int], str] | None = None,
) -> _VerifiedTableWithPosition | None:
    source_match = _candidate_source(
        candidate.file_id,
        candidate.passage_index,
        sources,
        passage_scope,
    )
    if source_match is None:
        return None
    _, passage = source_match

    columns = candidate.columns
    rows = candidate.rows
    row_spans = candidate.row_source_spans
    column_count = len(columns)
    row_count = len(rows)
    if not (2 <= column_count <= MAX_VERIFIED_TABLE_COLUMNS):
        return None
    if not (2 <= row_count <= MAX_VERIFIED_TABLE_ROWS):
        return None
    if row_count * column_count > MAX_VERIFIED_TABLE_CELLS:
        return None
    if len(row_spans) != row_count:
        return None
    if any(len(row) != column_count for row in rows):
        return None
    if not all(_is_clean_display_field(column) for column in columns):
        return None
    if len({column.casefold() for column in columns}) != column_count:
        return None
    if any(
        not _is_clean_display_field(cell)
        for row in rows
        for cell in row
    ):
        return None
    if candidate.title is not None and not _is_clean_display_field(candidate.title):
        return None
    if _is_horizontal_series(columns):
        return None

    header = _recover_source_span(candidate.header_source_span, passage)
    if (
        header is None
        or not _span_is_in_scope(
            header,
            candidate.file_id,
            candidate.passage_index,
            passage_scope,
        )
        or _has_blank_line(header.text)
        or not _span_covers_complete_lines(passage, header)
    ):
        return None

    header_positions = _ordered_exact_positions(header.text, columns)
    if header_positions is None:
        return None

    all_header_positions = list(header_positions)
    if candidate.title is not None:
        title_position = _unique_field_position(header.text, candidate.title)
        if title_position is None or title_position[1] > header_positions[0][0]:
            return None
        all_header_positions.append(title_position)
    if not _positions_do_not_overlap(all_header_positions):
        return None
    if _residue_contains_document_content(header.text, all_header_positions):
        return None
    if _has_uncovered_numeric_or_unit(header.text, all_header_positions):
        return None

    recovered_rows: list[_RecoveredSpan] = []
    cursor = header.end
    for row, candidate_row_span in zip(rows, row_spans):
        recovered_row = _recover_source_span(
            candidate_row_span,
            passage,
            start_at=cursor,
        )
        if recovered_row is None:
            return None
        if not _span_is_in_scope(
            recovered_row,
            candidate.file_id,
            candidate.passage_index,
            passage_scope,
        ):
            return None
        if _has_blank_line(recovered_row.text):
            return None
        if not _span_covers_complete_lines(passage, recovered_row):
            return None

        cell_positions = _ordered_exact_positions(recovered_row.text, row)
        if cell_positions is None:
            return None
        if _residue_contains_document_content(
            recovered_row.text,
            cell_positions,
        ):
            return None
        if _has_uncovered_numeric_or_unit(
            recovered_row.text,
            cell_positions,
        ):
            return None

        recovered_rows.append(recovered_row)
        cursor = recovered_row.end

    row_texts = [row.text for row in recovered_rows]
    if not _table_units_are_consistent(columns, header.text, row_texts):
        return None

    verified_table = VerifiedEvidenceTable(
        title=candidate.title,
        columns=list(columns),
        rows=[list(row) for row in rows],
        source_texts=[header.text, *row_texts],
    )
    return _VerifiedTableWithPosition(
        match=VerifiedTableMatch(
            file_id=candidate.file_id,
            passage_index=candidate.passage_index,
            table=verified_table,
        ),
        source_start=header.start,
        source_end=recovered_rows[-1].end,
        candidate_index=candidate_index,
    )


def verify_table_candidate(
    candidate: EvidenceTableCandidate,
    sources: list[SourceReference],
) -> VerifiedTableMatch | None:
    """Verify one row-oriented table against one cited raw passage."""

    verified = _verify_table_candidate_with_position(candidate, sources)
    return None if verified is None else verified.match


def _metric_key(match: _VerifiedMetricWithPosition) -> tuple[str, ...]:
    metric = match.match.metric
    return (
        metric.label,
        metric.value,
        metric.period or "",
        metric.unit or "",
    )


def _table_key(match: _VerifiedTableWithPosition) -> tuple[object, ...]:
    table = match.match.table
    return (
        table.title,
        tuple(table.columns),
        tuple(tuple(row) for row in table.rows),
    )


def _index_passage_scope(
    passages: list[EvidencePresentationPassage],
) -> dict[tuple[str, int], str]:
    indexed: dict[tuple[str, int], str] = {}
    ambiguous: set[tuple[str, int]] = set()

    for passage in passages:
        key = (passage.file_id, passage.passage_index)
        if key in indexed:
            ambiguous.add(key)
            continue
        indexed[key] = passage.text

    for key in ambiguous:
        indexed.pop(key, None)
    return indexed


def verify_evidence_presentations(
    selection: EvidencePresentationSelection,
    sources: list[SourceReference],
    passage_scope: list[EvidencePresentationPassage] | None = None,
) -> dict[str, list[VerifiedEvidencePresentation]]:
    """Verify, deduplicate, limit, and group structured candidates."""

    indexed_scope = (
        None
        if passage_scope is None
        else _index_passage_scope(passage_scope)
    )

    source_order = {
        source.file_id: index
        for index, source in enumerate(sources)
        if source.file_id
        and sum(item.file_id == source.file_id for item in sources) == 1
    }

    metrics = [
        verified
        for index, candidate in enumerate(
            selection.metrics[:MAX_CANDIDATE_METRICS]
        )
        if (
            verified := _verify_metric_candidate_with_position(
                candidate,
                sources,
                candidate_index=index,
                passage_scope=indexed_scope,
            )
        )
        is not None
    ]
    tables = [
        verified
        for index, candidate in enumerate(
            selection.tables[:MAX_CANDIDATE_TABLES]
        )
        if (
            verified := _verify_table_candidate_with_position(
                candidate,
                sources,
                candidate_index=index,
                passage_scope=indexed_scope,
            )
        )
        is not None
    ]
    parallel_tables = []
    for index, candidate in enumerate(
        selection.parallel_series[:MAX_PARALLEL_CANDIDATES]
    ):
        verified_parallel = verify_parallel_series_candidate(
            candidate,
            sources,
            passage_scope=indexed_scope,
            candidate_index=index,
        )
        if verified_parallel is None:
            continue
        parallel_tables.append(
            _VerifiedTableWithPosition(
                match=VerifiedTableMatch(
                    file_id=verified_parallel.file_id,
                    passage_index=verified_parallel.passage_index,
                    table=verified_parallel.table,
                ),
                source_start=verified_parallel.source_start,
                source_end=verified_parallel.source_end,
                candidate_index=verified_parallel.candidate_index,
                origin_priority=1,
            )
        )
    tables.extend(parallel_tables)

    metrics.sort(
        key=lambda item: (
            source_order.get(item.match.file_id, len(sources)),
            item.match.passage_index,
            item.source_start,
            item.source_end - item.source_start,
            item.candidate_index,
        )
    )
    tables.sort(
        key=lambda item: (
            source_order.get(item.match.file_id, len(sources)),
            item.match.passage_index,
            item.source_start,
            item.origin_priority,
            item.source_end - item.source_start,
            item.candidate_index,
        )
    )

    deduplicated_metrics: list[_VerifiedMetricWithPosition] = []
    seen_metrics: set[tuple[str, tuple[str, ...]]] = set()
    for metric in metrics:
        key = (metric.match.file_id, _metric_key(metric))
        if key not in seen_metrics:
            seen_metrics.add(key)
            deduplicated_metrics.append(metric)

    deduplicated_tables: list[_VerifiedTableWithPosition] = []
    seen_tables: dict[tuple[str, tuple[object, ...]], int] = {}
    for table in tables:
        key = (table.match.file_id, _table_key(table))
        existing_index = seen_tables.get(key)
        if existing_index is None:
            seen_tables[key] = len(deduplicated_tables)
            deduplicated_tables.append(table)
        elif (
            table.origin_priority
            < deduplicated_tables[existing_index].origin_priority
        ):
            deduplicated_tables[existing_index] = table

    components: list[
        tuple[str, _VerifiedMetricWithPosition | _VerifiedTableWithPosition]
    ] = [
        *(("metric", metric) for metric in deduplicated_metrics),
        *(("table", table) for table in deduplicated_tables),
    ]
    components.sort(
        key=lambda item: (
            source_order.get(item[1].match.file_id, len(sources)),
            item[1].match.passage_index,
            item[1].source_start,
            0 if item[0] == "metric" else 1,
            item[1].candidate_index,
        )
    )

    accepted_metrics: list[_VerifiedMetricWithPosition] = []
    accepted_tables: list[_VerifiedTableWithPosition] = []
    metric_passage_counts: dict[tuple[str, int], int] = {}
    metric_source_counts: dict[str, int] = {}
    table_passage_counts: dict[tuple[str, int], int] = {}
    table_source_counts: dict[str, int] = {}

    for component_type, component in components:
        if (
            len(accepted_metrics) + len(accepted_tables)
            >= MAX_VERIFIED_COMPONENTS_PER_ANSWER
        ):
            break

        file_id = component.match.file_id
        passage_index = component.match.passage_index
        passage_key = (file_id, passage_index)

        if component_type == "metric":
            if len(accepted_metrics) >= MAX_VERIFIED_METRICS_PER_ANSWER:
                continue
            if metric_source_counts.get(file_id, 0) >= MAX_VERIFIED_METRICS_PER_SOURCE:
                continue
            if (
                metric_passage_counts.get(passage_key, 0)
                >= MAX_VERIFIED_METRICS_PER_PASSAGE
            ):
                continue
            accepted_metrics.append(component)
            metric_source_counts[file_id] = metric_source_counts.get(file_id, 0) + 1
            metric_passage_counts[passage_key] = (
                metric_passage_counts.get(passage_key, 0) + 1
            )
            continue

        if len(accepted_tables) >= MAX_VERIFIED_TABLES_PER_ANSWER:
            continue
        if table_source_counts.get(file_id, 0) >= MAX_VERIFIED_TABLES_PER_SOURCE:
            continue
        if table_passage_counts.get(passage_key, 0) >= MAX_VERIFIED_TABLES_PER_PASSAGE:
            continue
        accepted_tables.append(component)
        table_source_counts[file_id] = table_source_counts.get(file_id, 0) + 1
        table_passage_counts[passage_key] = table_passage_counts.get(passage_key, 0) + 1

    grouped: dict[str, dict[int, dict[str, list[object]]]] = {}
    for metric in accepted_metrics:
        passage = grouped.setdefault(metric.match.file_id, {}).setdefault(
            metric.match.passage_index,
            {"metrics": [], "tables": []},
        )
        passage["metrics"].append(metric.match.metric)
    for table in accepted_tables:
        passage = grouped.setdefault(table.match.file_id, {}).setdefault(
            table.match.passage_index,
            {"metrics": [], "tables": []},
        )
        passage["tables"].append(table.match.table)

    presentations: dict[str, list[VerifiedEvidencePresentation]] = {}
    for source in sources:
        file_id = source.file_id
        if not file_id or file_id not in grouped or file_id in presentations:
            continue
        presentations[file_id] = [
            VerifiedEvidencePresentation(
                passage_index=passage_index,
                metrics=passage_data["metrics"],
                tables=passage_data["tables"],
            )
            for passage_index, passage_data in sorted(grouped[file_id].items())
        ]

    return presentations


def attach_verified_presentations(
    sources: list[SourceReference],
    presentations_by_file_id: dict[
        str,
        list[VerifiedEvidencePresentation],
    ],
) -> list[SourceReference]:
    """Return source copies with verified presentations attached by file ID."""

    return [
        source.model_copy(
            update={
                "presentations": list(
                    presentations_by_file_id.get(source.file_id, [])
                )
            }
        )
        for source in sources
    ]
