# VDR Assistant MVP 2

VDR Assistant MVP 2 is a local Streamlit application for asking questions against documents indexed in an OpenAI vector store.

The current MVP supports one active VDR project at a time and one OpenAI vector store ID at a time.

## Current functionality

- Ask questions about VDR documents
- Retrieve answers using OpenAI File Search
- Display source files for supported answers, including VDR folder breadcrumbs
  when the active case manifest is configured
- Display concise, source-verified quotations beneath successful answers
- Expand retrieved File Search passages beneath their cited sources in chat,
  with Readable and Raw text views
- Display an optional Structured view for locally verified key figures,
  row-oriented evidence tables, and explicit horizontal financial series
- Return a fallback response when information is not found in the VDR documents
- Maintain short conversation history for follow-up questions
- Reset the chat session from the sidebar

Each cited source displays up to two retrieved evidence excerpts, ordered by
the relevance score returned by File Search and capped in length for
readability. Full retrieved passages remain available internally, while the
scores themselves are not displayed. Quote candidates are selected from cited
retrieved evidence, and every displayed quotation is checked locally against
the corresponding source text. Unverifiable candidates are omitted, and quote
selection failure does not invalidate an otherwise supported answer. This
verification establishes that the displayed wording occurs in retrieved
evidence; it does not prove the broader answer is correct. Broader retrieved
evidence remains available in expanders, while the sidebar stays citation-only.
When a retrieved passage supports locally verified key figures, a row-oriented
table, or explicit horizontal financial series, its evidence expander also
provides a Structured view. Horizontal series are converted into the existing
row-oriented verified table only after the category and every value sequence
have been matched locally to distinct, contiguous source lines. Values and
financial period or scenario markers remain exact strings. Ambiguous,
incomplete, or fully flattened horizontal structures are omitted.
Displayed labels, values, periods, units, headers, and cells remain exact source
strings. Ambiguous relationships are omitted, and the Structured view does not
claim to reproduce the original PDF or slide layout. Readable and Raw text
views remain available alongside it. Without verified structured content, the
existing Readable and Raw tabs are unchanged. The Readable view applies
deterministic whitespace and line-layout cleanup only; it does not change
document wording, values, punctuation, capitalization, or ordering. The Raw
view retains the original retrieved passage for the same bounded excerpt.
No charts are generated from structured evidence yet. Chart-compatible numeric
parsing and chart generation remain deferred to Phase 3.
Retrieval and ranking tuning remain outside Milestone 1C.

## Fallback behavior

If the answer cannot be supported by retrieved VDR documents, the app returns:

```text
I can not find this information in the VDR documents
```

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

Create a file called `.env` in the project root.

Example:

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1
VECTOR_STORE_ID=your_vector_store_id_here
# Optional: local VDR root used to resolve folder-aware citations
VDR_FOLDER=
```

`VDR_FOLDER` is optional. Set it to the local VDR root whose sibling
`VDR Assistant/manifest.json` belongs to the selected vector store. If the
folder, manifest, or vector-store association is unavailable, Q&A continues
with filename-only citations.

Do not commit `.env` to GitHub.

### 6. Run the Streamlit app

```powershell
streamlit run app/main.py
```

The app should open in the browser.

## Project structure

```text
VDR-Assistant-MVP-2/
|-- app/
|   |-- main.py
|-- src/
|   |-- chains/
|   |-- config/
|   |-- context/
|   |-- ingestion/
|   |-- presentation/
|   |-- prompts/
|   |-- retrieval/
|   |-- schemas/
|   |-- ui/
|   |-- validation/
|-- tests/
|-- .env.example
|-- .gitignore
|-- README.md
|-- requirements.txt
```

## Notes for team members

The OpenAI vector store is the searchable index used by the application. It is not the original VDR folder.

Each team member needs:

- Access to the GitHub repository
- A valid OpenAI API key
- The correct OpenAI vector store ID
- A local `.env` file

## Current scope

Implemented:

- Local Streamlit Q&A workflow
- OpenAI File Search integration
- Source file display
- Basic answer validation
- Basic error handling
- Reset chat button

Not implemented yet:

- VDR ingestion from local folders
- Folder structure preservation
- Compare workflow
- Summarize workflow
- User authentication
- Deployment
