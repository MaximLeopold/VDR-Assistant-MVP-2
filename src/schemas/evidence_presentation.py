"""Schemas for proposed and verified structured evidence presentations."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


MAX_PRESENTATION_CHARS_PER_PASSAGE = 4500

MAX_CANDIDATE_METRICS = 12
MAX_CANDIDATE_TABLES = 4
MAX_CANDIDATE_TABLE_ROWS = 15
MAX_CANDIDATE_TABLE_COLUMNS = 6
MAX_CANDIDATE_TABLE_CELLS = 90


class _StrictPresentationModel(BaseModel):
    """Reject coercion and undeclared structured-output fields."""

    model_config = ConfigDict(strict=True, extra="forbid")


class EvidencePresentationPassage(_StrictPresentationModel):
    """One bounded raw passage supplied to the presentation selector."""

    file_id: str = Field(min_length=1)
    passage_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=MAX_PRESENTATION_CHARS_PER_PASSAGE)


class EvidenceMetricCandidate(_StrictPresentationModel):
    """A transient model-proposed label/value relationship."""

    file_id: str = Field(min_length=1)
    passage_index: int = Field(ge=0)
    label: str
    value: str
    period: str | None = None
    unit: str | None = None
    source_span: str


class EvidenceTableCandidate(_StrictPresentationModel):
    """A transient model-proposed row-oriented table."""

    file_id: str = Field(min_length=1)
    passage_index: int = Field(ge=0)
    title: str | None = None
    columns: list[str] = Field(
        min_length=2,
        max_length=MAX_CANDIDATE_TABLE_COLUMNS,
    )
    rows: list[list[str]] = Field(
        min_length=2,
        max_length=MAX_CANDIDATE_TABLE_ROWS,
    )
    header_source_span: str
    row_source_spans: list[str] = Field(
        min_length=2,
        max_length=MAX_CANDIDATE_TABLE_ROWS,
    )

    @model_validator(mode="after")
    def validate_table_shape(self) -> "EvidenceTableCandidate":
        """Reject malformed or oversized tables without partial recovery."""

        column_count = len(self.columns)
        if len(self.row_source_spans) != len(self.rows):
            raise ValueError("each row requires one source span")

        if any(len(row) != column_count for row in self.rows):
            raise ValueError("every row must match the column count")

        cell_count = sum(len(row) for row in self.rows)
        if cell_count > MAX_CANDIDATE_TABLE_CELLS:
            raise ValueError("candidate table exceeds the cell limit")

        return self


class EvidencePresentationSelection(_StrictPresentationModel):
    """Structured candidates returned by the presentation request."""

    metrics: list[EvidenceMetricCandidate] = Field(
        default_factory=list,
        max_length=MAX_CANDIDATE_METRICS,
    )
    tables: list[EvidenceTableCandidate] = Field(
        default_factory=list,
        max_length=MAX_CANDIDATE_TABLES,
    )


class VerifiedEvidenceMetric(_StrictPresentationModel):
    """A source-derived metric that passed local verification."""

    label: str
    value: str
    period: str | None = None
    unit: str | None = None
    source_text: str


class VerifiedEvidenceTable(_StrictPresentationModel):
    """A source-derived row-oriented table that passed local verification."""

    title: str | None = None
    columns: list[str]
    rows: list[list[str]]
    source_texts: list[str]


class VerifiedEvidencePresentation(_StrictPresentationModel):
    """Verified structured components belonging to one raw passage."""

    passage_index: int = Field(ge=0)
    metrics: list[VerifiedEvidenceMetric] = Field(default_factory=list)
    tables: list[VerifiedEvidenceTable] = Field(default_factory=list)
