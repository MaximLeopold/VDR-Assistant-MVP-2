"""Manage OpenAI vector stores.

Responsibilities:

- Create a new vector store.
- Retrieve an existing vector store.
- Check upload status.
- Associate uploaded files with a vector store.

Each M&A project should use one dedicated
OpenAI vector store.

The vector store acts as the searchable index
of the VDR and not as the source of truth.
"""
