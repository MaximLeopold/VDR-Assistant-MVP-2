"""Extract answer text and file citations from OpenAI responses.

This module converts the raw OpenAI response into answer text,
citation identities, and quotes used by the app.
"""

"""Extract useful information from an OpenAI Responses API object.

This module converts the raw OpenAI response into simple Python
objects that the rest of the application can understand.

It hides the complexity of the OpenAI response structure from the
rest of the codebase.
"""

from src.schemas.citation import Citation


def _optional_text(value: object) -> str | None:
    """Return a trimmed non-empty string when one is available."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def extract_response_data(response):
    """Extract answer text, citation identities and quotes.

    Args:
        response:
            Raw OpenAI Responses API response.

    Returns:
        Dictionary containing:

        - answer
        - citations
        - quotes
    """

    answer = ""
    citations = []
    quotes = []

    seen = set()

    for block in response.output:

        if block.type != "message":
            continue

        for content in block.content:

            if content.type != "output_text":
                continue

            answer = content.text

            for annotation in content.annotations:

                if getattr(annotation, "type", "") != "file_citation":
                    continue

                file_id = _optional_text(
                    getattr(annotation, "file_id", None)
                )
                filename = _optional_text(
                    getattr(annotation, "filename", None)
                )

                if file_id is not None:
                    identity = ("file_id", file_id)
                elif filename is not None:
                    identity = ("filename", filename)
                else:
                    identity = ("unknown", None)

                if identity in seen:
                    continue

                seen.add(identity)
                citations.append(
                    Citation(file_id=file_id, filename=filename)
                )

    return {
        "answer": answer,
        "citations": citations,
        "quotes": quotes,
    }
