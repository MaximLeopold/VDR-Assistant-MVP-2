"""Citation schema for VDR source references.

The Citation model should represent file citations returned by
OpenAI File Search.
"""

from pydantic import BaseModel


class Citation(BaseModel):
    """Identity of one file citation returned by OpenAI File Search."""

    file_id: str | None = None
    filename: str | None = None
