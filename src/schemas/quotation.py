"""Schemas for selecting and displaying verified source quotations."""

from pydantic import BaseModel, Field


class QuoteCandidate(BaseModel):
    """A model-proposed quotation candidate tied to an opaque file ID."""

    file_id: str
    quote: str


class QuoteSelection(BaseModel):
    """Structured output returned by the quote-selection request."""

    candidates: list[QuoteCandidate] = Field(default_factory=list)


class VerifiedQuote(BaseModel):
    """A source-derived quotation that passed deterministic verification."""

    file_id: str
    source_display_name: str
    text: str
