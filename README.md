# VDR Assistant MVP 2

VDR Assistant MVP 2 is a local-first Streamlit application for querying M&A and due-diligence Virtual Data Room (VDR) documents through natural language.

The system combines:

- a local VDR folder as the document source of truth;
- a persistent case manifest as the operational control layer;
- an OpenAI vector store as the searchable document index;
- the OpenAI Responses API with File Search for retrieval;
- a Streamlit interface for source-backed Q&A.

The current MVP supports one active VDR case and one OpenAI vector store at a time.

## Current status

The core end-to-end workflow has been implemented and validated:

```text
Local VDR document
        ↓
Recursive scan and classification
        ↓
Case manifest
        ↓
Manifest refresh
        ↓
OpenAI file upload
        ↓
Vector-store attachment and indexing
        ↓
Streamlit File Search retrieval
        ↓
Grounded answer with source reference
```

A newly added PDF has been discovered locally, appended to the manifest, uploaded to an existing vector store, indexed successfully, and queried through the Streamlit application.

The latest validated automated test result is:

```text
100 passed
```

## Current functionality

### Q&A application

- Ask natural-language questions about the active VDR.
- Retrieve relevant content using OpenAI File Search.
- Display source filenames for supported answers.
- Maintain short conversation context for follow-up questions.
- Validate that answers contain supporting sources.
- Return a fixed fallback when the VDR does not support an answer.
- Reset the chat session from the sidebar.

### Ingestion administration

- Recursively scan nested local VDR folders.
- Classify files as supported, unsupported, ignored, or error.
- Preserve each document's relative VDR path.
- Create and persist a case manifest.
- Adopt an existing OpenAI vector store.
- Reconcile files that were uploaded before the manifest workflow existed.
- Refresh an existing manifest when new local files are added.
- Upload only supported files that do not already have an OpenAI file ID.
- Validate local paths, file existence, and file size before upload.
- Persist OpenAI file IDs before attachment and indexing.
- Prevent duplicate uploads after successful remote file creation.

## Fallback behavior

If the answer cannot be supported by retrieved VDR documents, the application returns:

```text
I can not find this information in the VDR documents
```

## Core architecture principle

> The OpenAI vector store is not the VDR. It is the searchable index of the VDR.

The original VDR folder remains the source of truth for document presence and hierarchy. The manifest connects local files to their OpenAI identities and processing states.

```text
Local VDR folder
        ↕
     manifest.json
        ↕
OpenAI vector store
```

## User model

### Business users

Once documents are indexed, business users only need the Streamlit browser interface. They do not need VS Code, Python, terminal commands, OpenAI file IDs, or vector-store administration knowledge.

### Technical operator or case administrator

In the current MVP, ingestion is managed through PowerShell scripts. VS Code is convenient but not required; any terminal with the repository, Python environment, and credentials can run the workflows.

A future version can expose the same tested ingestion functions through an administration page in Streamlit.

## Local setup

### 1. Clone the repository

```powershell
git clone <repository-url>
cd VDR-Assistant-MVP-2
```

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

### 3. Activate the virtual environment

```powershell
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate the environment again.

### 4. Install dependencies

```powershell
pip install -r requirements.txt
```

### 5. Create a local `.env` file

Create `.env` in the repository root.

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1
VECTOR_STORE_ID=your_vector_store_id_here
```

Notes:

- `OPENAI_API_KEY` is required.
- `OPENAI_MODEL` is optional if the application defines a default.
- `VECTOR_STORE_ID` can be configured in `.env` or entered in the Streamlit sidebar for Q&A.
- Ingestion uses the vector-store ID stored in the case manifest.
- Never commit `.env`, API keys, real VDR files, or confidential client materials.

### 6. Run the automated tests

```powershell
pytest
```

### 7. Start the Streamlit application

```powershell
streamlit run app/main.py
```

The application should open in the browser.

## Ingestion workflows

All ingestion commands should be run from the repository root with the virtual environment active.

### Create a manifest for a new case

```powershell
python scripts/create_case_manifest.py
```

Use this for a new VDR case. Do not recreate an existing manifest merely to discover newly added files.

### Adopt an existing vector store

```powershell
python scripts/adopt_existing_vector_store.py
```

Use this when the case should connect to a vector store that already exists.

### Reconcile files already uploaded remotely

```powershell
python scripts/reconcile_existing_vector_store_files.py
```

The workflow previews matches and requires the exact confirmation token:

```text
RECONCILE
```

It does not upload files.

### Refresh an existing manifest

After adding documents to the local VDR, run:

```powershell
python scripts/refresh_case_manifest.py
```

Enter the VDR root folder, not the path to `manifest.json`.

Review the preview and type:

```text
REFRESH
```

The workflow appends newly discovered records without replacing existing records.

### Upload newly registered documents

```powershell
python scripts/upload_new_manifest_files.py
```

Enter the same VDR root folder used for the manifest.

Review the preview and type:

```text
UPLOAD
```

Only records satisfying both conditions are eligible:

```text
classification_status = supported
openai_file_id = null
```

After a successful upload, rerunning the workflow should report:

```text
No supported manifest files require upload.
```

This is the expected duplicate-prevention behavior.

## Upload safety and recovery

For each eligible document, the upload workflow:

1. increments the upload attempt and saves the `uploading` state;
2. uploads the local file to OpenAI;
3. immediately persists the returned OpenAI file ID;
4. attaches the file to the case vector store;
5. waits for indexing;
6. saves the terminal result.

Persisting the OpenAI file ID before attachment protects against duplicate uploads if connectivity, polling, or a later local save is interrupted.

If a file is already visible as **Ready** in the OpenAI Platform but the terminal appears blocked, do not immediately rerun the upload script. First inspect the active manifest and confirm whether `openai_file_id` has already been stored.

## Project structure

```text
VDR-Assistant-MVP-2/
|-- app/
|   |-- main.py
|
|-- scripts/
|   |-- create_case_manifest.py
|   |-- adopt_existing_vector_store.py
|   |-- reconcile_existing_vector_store_files.py
|   |-- refresh_case_manifest.py
|   |-- upload_new_manifest_files.py
|
|-- src/
|   |-- chains/
|   |-- config/
|   |-- context/
|   |-- ingestion/
|   |   |-- folder_scanner.py
|   |   |-- manifest.py
|   |   |-- manifest_builder.py
|   |   |-- manifest_persistence.py
|   |   |-- uploader.py
|   |   |-- vector_store_manager.py
|   |-- prompts/
|   |-- retrieval/
|   |-- schemas/
|   |-- ui/
|   |-- validation/
|
|-- tests/
|-- docs/
|-- .env.example
|-- .gitignore
|-- README.md
|-- requirements.txt
```

## Testing approach

- OpenAI operations are mocked or faked in automated tests.
- Automated tests do not make real OpenAI API calls.
- Important persistence and recovery boundaries are tested.
- Live API validation is performed separately and deliberately.

Run the full suite with:

```powershell
pytest
```

## Current scope

### Implemented

- Local Streamlit Q&A workflow.
- OpenAI Responses API and File Search integration.
- Source filename display.
- Answer validation and fallback behavior.
- Short conversation context.
- Reset chat button.
- Recursive VDR folder scanning.
- File classification.
- Manifest schema, creation, and persistence.
- Vector-store lifecycle and adoption.
- Existing-file reconciliation.
- Incremental manifest refresh.
- Manifest-driven sequential uploads.
- Upload state tracking and duplicate prevention.
- End-to-end ingestion and retrieval validation.

### Not implemented yet

- Browser-based ingestion administration.
- User-friendly multi-case selection.
- Automatic rename, move, removal, or replacement synchronization.
- Automatic retries, background workers, or concurrent uploads.
- Excel-specific analysis.
- Compare, summarize, red-flag, or investment-committee workflows.
- User authentication and case-level authorization.
- Hosted deployment and enterprise secrets management.
- Production audit logging, data-retention, and deletion controls.

## Recommended next steps

1. Build a controlled Q&A evaluation set and measure answer quality.
2. Improve citation transparency, source excerpts, and page or section references.
3. Add named case selection instead of manual vector-store-ID management.
4. Expose refresh and upload workflows through a Streamlit administration page.
5. Add remote indexing-status refresh for interrupted polling scenarios.
6. Add specialized M&A and due-diligence workflows after Q&A quality is proven.
7. Define security, access control, hosting, and retention requirements before production use.

## Security and confidentiality

The current system is a working internal MVP, not yet a production-ready confidential deal platform.

Before broader use with sensitive VDRs, define and approve:

- authentication and authorization;
- case-level access controls;
- deployment environment;
- API-key and secrets management;
- logging and auditability;
- data retention and deletion;
- OpenAI project and account separation;
- internal legal, security, and compliance requirements.

## Project documentation

Detailed project documentation should be stored under `docs/`:

- `docs/VDR_Assistant_MVP2_Executive_Overview_v2.md`
- `docs/VDR_Assistant_MVP2_Project_Handover_v2.md`

These documents provide the management overview, completed milestone history, detailed architecture, recovery lessons, operating instructions, and recommended continuation sequence.
