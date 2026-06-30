"""VDR ingestion package.

This package is responsible for preparing a Virtual Data Room (VDR)
for use with the OpenAI File Search API.

The ingestion pipeline is responsible for:

- scanning the original VDR folder structure
- preserving folder hierarchy and metadata
- building a manifest of all supported files
- filtering unsupported file types
- uploading supported documents to an OpenAI vector store

The vector store is treated as the searchable index of the VDR,
not the source of truth.
"""
