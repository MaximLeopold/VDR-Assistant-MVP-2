# VDR Assistant MVP 2

VDR Assistant MVP 2 is a local Streamlit application for asking questions against documents indexed in an OpenAI vector store.

The current MVP lists a small set of prepared VDR cases and opens one active
case at a time. Each prepared case uses its own manifest and OpenAI vector
store.

## Current functionality

- Ask questions about VDR documents
- Retrieve answers using OpenAI File Search
- Display source files for supported answers, including VDR folder breadcrumbs
  when the active case manifest is configured
- Display concise, source-verified quotations beneath successful answers
- Expand retrieved File Search passages beneath their cited sources in chat,
  with an Evidence view and a Raw retrieval audit view
- Display an optional Structured tab for locally verified key figures,
  row-oriented evidence tables, and explicit horizontal financial series
- Return a fallback response when information is not found in the VDR documents
- Maintain short conversation history for follow-up questions
- Reset the chat session from the sidebar
- Select one prepared case when the application starts
- Close the active case and safely return to case selection
- Prepare an unregistered new case by scanning a local VDR, creating its
  manifest, and associating a manually created empty OpenAI vector store

Successful main answers are synthesized from cited VDR evidence. A Markdown
table in the main answer is not automatically verified cell by cell. The UI
discloses this distinction and separately identifies when independently
verified source figures are available under Structured.

Each cited source displays up to two retrieved passages, ordered by the
relevance score returned by File Search. Evidence is the default business-user
view. A single passage appears directly; when a second passage is available,
the best-ranked passage is selected first and the second remains available as
additional retrieved context. Evidence cleans display whitespace, applies only
conservative soft-wrap reflow, and uses boundary-aware excerpts with a
1,800-character hard maximum. Ambiguous fragmented or table-like extractions
remain preformatted and carry a layout notice rather than being reconstructed.
Raw retrieval preserves the complete exact stored File Search strings for the
same first two passages as an audit fallback. Scores and internal identifiers
are not displayed. Table-like content is converted to a table only when it is
independently verified for Structured; otherwise Structured remains absent.

Quote candidates are selected from cited retrieved evidence, and every
displayed quotation is checked locally against the corresponding source text.
Unverifiable candidates are omitted, and quote selection failure does not
invalidate an otherwise supported answer. This verification establishes that
the displayed wording occurs in retrieved evidence; it does not prove the
broader answer is correct. The sidebar stays citation-only.
When a retrieved passage supports locally verified key figures, a row-oriented
table, or explicit horizontal financial series, its evidence expander also
provides a Structured view. Horizontal series are converted into the existing
row-oriented verified table only after the category and every value sequence
have been matched locally to distinct, contiguous source lines. Values and
financial period or scenario markers, including compact Budget suffix `B`,
remain exact strings. Ambiguous, interleaved, incomplete, competing, or fully
flattened horizontal structures are omitted.
Displayed labels, values, periods, units, headers, and cells remain exact source
strings. Ambiguous relationships are omitted, and the Structured view does not
claim to reproduce the original PDF or slide layout. Phase 2 intentionally does
not reconstruct every source table. No charts are generated yet; future chart
construction must consume verified tables only.
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
CASE_REGISTRY_PATH=cases.local.json
```

`CASE_REGISTRY_PATH` may be absolute or relative to the repository root. The
real registry is local and ignored by Git. Copy `cases.example.json` to
`cases.local.json` and configure each prepared case with only a stable
`case_id` and its local `vdr_folder`:

```json
{
  "cases": [
    {
      "case_id": "example-case",
      "vdr_folder": "./prepared-cases/example-case/VDR"
    }
  ]
}
```

Relative VDR paths are resolved from the registry file. Absolute paths are
also supported in the ignored local registry. The selected case manifest must
exist in the VDR folder's sibling `VDR Assistant/manifest.json` and must
contain a usable case name and vector-store ID. The manifest remains the
source of truth for case metadata, document mappings, and ingestion state.

The application blocks incomplete prepared cases instead of silently mixing a
VDR folder, manifest, and vector store. The vector-store ID is not editable in
normal chat.

Do not commit `.env` to GitHub.

### 6. Run the Streamlit app

```powershell
streamlit run app/main.py --server.address 127.0.0.1
```

The app should open in the browser and remain bound to the local machine.

## Phase 1 new-case preparation

From the startup case selector, choose **Prepare new case** to:

1. enter an existing local VDR folder and a non-confidential technical case
   ID;
2. run and review a read-only file-metadata scan;
3. explicitly create the local manifest; and
4. validate and associate an empty vector store that you created manually in
   the OpenAI Platform.

Phase 1 does not upload documents and does not add the case to
`cases.local.json`. The incomplete case therefore remains unavailable in
normal case selection. Bulk ingestion and registration belong to Phase 2.

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
|-- cases.example.json
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
- Access to each prepared case's local VDR folder and manifest
- A local ignored case registry
- A local `.env` file

## Current scope

Implemented:

- Prepared-case selection with isolated chat state
- Local Streamlit Q&A workflow
- OpenAI File Search integration
- Folder-aware citations and ranked retrieved evidence
- Verified quotations and structured evidence
- Manifest-driven ingestion operator scripts
- Reset chat button

Not implemented yet:

- Case creation or ingestion administration in Streamlit
- Compare workflow
- Summarize workflow
- User authentication
- Deployment
