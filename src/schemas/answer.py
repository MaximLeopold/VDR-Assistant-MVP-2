"""Schema representing a response returned by the VDR Assistant."""

from typing import List, Literal

from pydantic import BaseModel, Field

from src.schemas.evidence import SourceReference
from src.schemas.quotation import VerifiedQuote


class VDRAnswer(BaseModel):
    """Standard response object used throughout the application."""

    answer: str

    source_files: List[str] = []

    sources: list[SourceReference] = Field(default_factory=list)

    quotes: List[str] = []

    verified_quotes: list[VerifiedQuote] = Field(default_factory=list)

    warnings: List[str] = []

    status: Literal[
        "success",
        "not_found",
        "error",
    ] = "success"

    workflow: Literal[
        "qa",
        "compare",
        "summarize",
    ] = "qa"
