"""Schema representing a response returned by the VDR Assistant."""

from typing import List, Literal

from pydantic import BaseModel


class VDRAnswer(BaseModel):
    """Standard response object used throughout the application."""

    answer: str

    source_files: List[str] = []

    quotes: List[str] = []

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
