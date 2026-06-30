"""Extract answer text and file citations from OpenAI responses.

This module converts the raw OpenAI response into answer text,
citation objects, and source filenames used by the app.
"""

"""Extract useful information from an OpenAI Responses API object.

This module converts the raw OpenAI response into simple Python
objects that the rest of the application can understand.

It hides the complexity of the OpenAI response structure from the
rest of the codebase.
"""


def extract_response_data(response):
    """Extract answer text, source files and quotes.

    Args:
        response:
            Raw OpenAI Responses API response.

    Returns:
        Dictionary containing:

        - answer
        - source_files
        - quotes
    """

    answer = ""
    source_files = []
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

                filename = getattr(annotation, "filename", "")

                if not filename:
                    filename = getattr(
                        annotation,
                        "file_id",
                        "Unknown file",
                    )

                if filename not in seen:
                    seen.add(filename)
                    source_files.append(filename)

    return {
        "answer": answer,
        "source_files": source_files,
        "quotes": quotes,
    }
