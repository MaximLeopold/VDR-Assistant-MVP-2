"""Schemas for selecting and displaying verified source support."""

from pydantic import BaseModel, Field, StrictInt


class QuoteCandidate(BaseModel):
    """A model-proposed quotation tied to one retrieved passage."""

    file_id: str
    passage_index: StrictInt = Field(ge=0)
    quote: str


class EvidenceExcerptCandidate(BaseModel):
    """A model-proposed support excerpt tied to one retrieved passage."""

    file_id: str
    passage_index: StrictInt = Field(ge=0)
    text: str = Field(min_length=1, max_length=3500)


class SupportSelectionPassage(BaseModel):
    """One bounded retrieved passage supplied to the combined selector."""

    file_id: str
    passage_index: StrictInt = Field(ge=0)
    text: str = Field(min_length=1, max_length=3500)


class QuoteSelection(BaseModel):
    """Structured output returned by the combined support selector."""

    candidates: list[QuoteCandidate] = Field(
        default_factory=list,
        max_length=6,
    )
    best_support_candidates: list[EvidenceExcerptCandidate] = Field(
        default_factory=list,
        max_length=12,
    )
    additional_context_candidates: list[EvidenceExcerptCandidate] = Field(
        default_factory=list,
        max_length=24,
    )


class VerifiedQuote(BaseModel):
    """A source-derived quotation that passed deterministic verification."""

    file_id: str
    source_display_name: str
    text: str
