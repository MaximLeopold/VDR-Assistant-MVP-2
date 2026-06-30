"""Build a manifest describing the VDR.

The manifest is the metadata representation of the VDR.

For every supported document it should store:

- relative folder path
- filename
- extension
- document category
- upload status
- OpenAI file ID
- OpenAI vector store ID

The manifest allows the application to preserve
the original VDR structure independently from the
OpenAI vector store.
"""
