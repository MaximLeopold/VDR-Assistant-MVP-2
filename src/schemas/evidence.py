"""Schemas for retrieved File Search evidence and rendered sources."""

from pydantic import BaseModel, Field

from src.schemas.evidence_presentation import VerifiedEvidencePresentation


class RetrievedSearchResult(BaseModel):
    """One result returned by a completed OpenAI File Search call."""

    file_id: str | None = None
    filename: str | None = None
    text: str | None = None
    score: float | None = None


class SourceReference(BaseModel):
    """A cited source and its associated retrieved passages."""

    file_id: str | None = None
    display_name: str
    evidence: list[str] = Field(default_factory=list)
    presentations: list[VerifiedEvidencePresentation] = Field(
        default_factory=list
    )
