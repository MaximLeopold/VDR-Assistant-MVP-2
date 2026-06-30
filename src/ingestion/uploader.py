"""Upload supported VDR files to an OpenAI vector store.

Responsibilities:

- Upload supported files.
- Upload files in batches when necessary.
- Monitor upload progress.
- Return OpenAI file IDs.
- Update the VDR manifest.

This module should never change the original
folder structure or filenames.
"""
