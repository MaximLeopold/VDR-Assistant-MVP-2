# General Description

A reference implementation of a modular VDR RAG assistant using the OpenAI Responses API, File Search, and workflow-based architecture.

# VDR-Assistant-MVP-2

Improved local-first VDR RAG assistant for M&A due diligence.

## Current Scope

- One active VDR project at a time
- One OpenAI vector store connected to the app
- Vector store ID configured through `.env` or entered in the UI
- English app and codebase
- Q&A mode first
- Compare mode second
- Summarize mode third
- Conversation-aware follow-up retrieval
- Answers only from VDR documents
- Citations required for every answer
- Fallback if unsupported:
  `I can not find this information in the VDR documents`

## Not Included Yet

- Multi-case session registry
- Excel processing
- Folder upload from the app
- Zip ingestion from the app
- SharePoint integration
- Online deployment
- Persistent database

## Setup

Create a local `.env` file based on `.env.example`.

## Run the App

```bash
streamlit run app/main.py
