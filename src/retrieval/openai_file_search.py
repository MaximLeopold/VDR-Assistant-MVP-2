"""OpenAI File Search service.

This module is responsible for communicating with the OpenAI
Responses API using the File Search tool.

The rest of the application should never call the OpenAI API directly.
Instead, all retrieval requests should go through this module.
"""

from openai import OpenAI

from src.config.settings import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
)


def get_openai_client() -> OpenAI:
    """Create and return an OpenAI client."""

    return OpenAI(api_key=OPENAI_API_KEY)


def search_vector_store(
    question: str,
    vector_store_id: str,
    instructions: str,
):
    """Search the active OpenAI vector store.

    Args:
        question:
            The user's current question.

        vector_store_id:
            The OpenAI vector store to search.

        instructions:
            System instructions guiding the model.

    Returns:
        The raw OpenAI Responses API object.

    Notes:
        This function intentionally returns the raw OpenAI response.
        Parsing the response is the responsibility of
        citation_extractor.py.
    """

    client = get_openai_client()

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=question,
        instructions=instructions,
        tools=[
            {
                "type": "file_search",
                "vector_store_ids": [vector_store_id],
            }
        ],
    )

    return response
