"""Schemas for retrieved File Search evidence and rendered sources."""

from typing import Literal

from pydantic import BaseModel, Field, StrictInt

from src.schemas.evidence_presentation import VerifiedEvidencePresentation


class RetrievedSearchResult(BaseModel):
    """One result returned by a completed OpenAI File Search call."""

    file_id: str | None = None
    filename: str | None = None
    text: str | None = None
    score: float | None = None


class VerifiedEvidenceExcerpt(BaseModel):
    """A source-derived excerpt selected for a persisted evidence role."""

    role: Literal["best_support", "additional_context"]
    passage_index: StrictInt = Field(ge=0)
    text: str


class ExcelSourceProvenance(BaseModel):
    original_relative_path: str
    worksheet_name: str


class SourceReference(BaseModel):
    """A cited source and its associated retrieved passages."""

    file_id: str | None = None
    display_name: str
    excel_provenance: ExcelSourceProvenance | None = None
    evidence: list[str] = Field(default_factory=list)
    presentations: list[VerifiedEvidencePresentation] = Field(
        default_factory=list
    )
    evidence_selection_status: Literal["legacy", "completed"] = "legacy"
    selected_evidence: list[VerifiedEvidenceExcerpt] = Field(
        default_factory=list
    )
