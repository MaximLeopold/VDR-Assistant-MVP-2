"""Operation-specific ingestion retries; the shared Q&A client is unchanged."""

from openai import OpenAI


def mutation_client(client):
    """Attachment and store creation submit once; recovery inspects known IDs."""
    return client.with_options(max_retries=0) if isinstance(client, OpenAI) else client


def file_create_client(client):
    """One logical upload may use the SDK's two retries (unattached orphans accepted)."""
    return client.with_options(max_retries=2) if isinstance(client, OpenAI) else client


def read_client(client):
    """Bound each read request, allowing the SDK's two transient retries."""
    return (
        client.with_options(max_retries=2, timeout=5.0)
        if isinstance(client, OpenAI)
        else client
    )
