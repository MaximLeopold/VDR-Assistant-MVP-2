# VDR Assistant MVP 2

VDR Assistant is a local Streamlit application for asking natural-language questions about Virtual Data Room (VDR) documents in M&A and due diligence. It combines case-based OpenAI File Search with citations and inspectable, source-verified evidence.

This README is the project entry point. The [maintained documentation](docs/project-status.md) owns detailed current behavior, acceptance records, and development guidance; historical handovers and exports provide supporting evidence.

## Current capabilities

- **Case-based Q&A:** select a prepared case from the local registry, ask questions, and use recent conversation context for follow-ups. Switching cases resets chat state.
- **Verified supporting evidence:** answers include citations and require at least one verified **Best** excerpt. Quotations are optional; verified Additional context and optional Structured figures/tables may also be shown.
- **Controlled publication:** prepared cases use Manifest v2. Publication/registration requires 100% readiness of required searchable targets and produces a sealed, frozen snapshot.

## High-level architecture

Q&A follows **primary answer through OpenAI File Search → combined support selection and verification → optional Structured evidence**. A failed combined support stage or absence of verified Best evidence withholds the provisional answer. Optional Structured processing cannot veto an otherwise supported answer.

The release gate is **answer-wide, not claim-level**. One cited source's verified Best can satisfy it; this does not establish verified support for every source or claim. Main-answer tables are not automatically verified cell by cell.

The original VDR remains the document source of truth. The manifest records snapshot provenance and remote identities; the OpenAI vector store is the searchable index for that prepared snapshot. Normal Q&A uses retrieved text, while opening a case still requires its configured local directory and sealed manifest. See [Q&A architecture](docs/architecture/qa-architecture.md) and the [case/snapshot model](docs/architecture/case-and-snapshot-model.md).

## Excel searchable knowledge

`.xlsx` workbooks contribute searchable knowledge through deterministic Markdown artifacts, one per included worksheet, in the same case vector store. Raw workbooks are preprocessing sources and are never directly uploaded through this ingestion path. Citations preserve **Workbook → Worksheet** provenance.

Artifacts derive from captured workbook bytes and include visible content, stored formula results, and formula text. Hidden content is omitted, with coverage and exclusions available for review. This is bounded searchable knowledge, not unrestricted spreadsheet execution or analysis: formula recalculation, macros, charts/images, legacy `.xls`, and advanced calculations remain outside the accepted milestone. See the [Excel decision](docs/decisions/excel-searchable-knowledge.md).

## Case preparation and ingestion

Operators prepare and register cases through the preparation UI. Ingestion and recovery are also available through the [upload/recovery CLI](scripts/upload_new_manifest_files.py). Users of prepared cases select a case and ask questions through the browser.

The raw VDR tree stays read-only and outside the application repository; managed artifacts and manifests live in a separate sibling directory. Ingestion is sequential and manifest-driven. A returned File ID is persisted and verified before attachment. Known-ID targets recover by exact ID and never repeat File creation; eligible no-ID targets may retry in later operator-started passes.

Uncertain File creation can leave unattached orphan OpenAI Files. This is an accepted trade-off, without automatic orphan discovery or cleanup. Publication still requires every required searchable target to complete; unsupported/ignored sources and explicitly excluded workbooks are outside that target set, while unresolved errors block readiness.

Read the [ingestion architecture](docs/architecture/ingestion-architecture.md) and [development guide](docs/development.md) before operating ingestion or recovery.

## Recorded acceptance

The accepted Excel Searchable Knowledge and Resilient Ingestion & Recovery milestones are recorded in the **10 September 2026** v11 handover:

- **986 offline tests passed** after the attachment-timeout correction.
- **86/86 required searchable targets completed** in full-VDR live ingestion acceptance.
- **Live Excel workbook/worksheet retrieval and citations accepted.**

These are dated milestone results, not continuously rerun guarantees. [Project status](docs/project-status.md) owns the authoritative acceptance record and identifies `Accepted-Development-Baseline` as the accepted product baseline.

## Local setup and run

From the repository root on Windows, create the environment and install [requirements](requirements.txt):

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create an ignored local `.env` using [.env.example](.env.example). Set `OPENAI_API_KEY` locally and review `OPENAI_MODEL` and `CASE_REGISTRY_PATH`. Model/runtime behavior depends on the local environment; examples and historical acceptance do not establish the active configuration.

Use the ignored registry selected by `CASE_REGISTRY_PATH` (default `cases.local.json`). New cases enter it through registration in the preparation workflow. For existing prepared cases, configure technical case IDs and actual external VDR directories with their sibling sealed manifests; relative VDR paths resolve from the registry file's directory. Normal case-selected chat obtains the vector-store ID from the manifest.

Start the application:

```powershell
& .\.venv\Scripts\python.exe -m streamlit run app/main.py --server.address 127.0.0.1
```

Select a registered case, or use **Prepare new case** for operator preparation. Q&A, store association, uploads, and remote recovery contact OpenAI; use only explicitly authorized data, resources, and operations. Keep credentials, real VDR material, private paths, resource IDs, and local manifest/registry data out of Git.

## Current limitations

- Shared Team Access, authentication/case authorization, and SharePoint integration are not implemented.
- One writer per case is an operational assumption, not a technical lock. Atomic local JSON replacement does not provide multi-user transactions.
- No partial publication or automatic synchronization of registered snapshots; source changes require a fresh snapshot.
- Claim-level grounding and evidence-formatting/whitespace preservation remain explicitly deferred Q&A issues.
- Compare and Summarize remain placeholders. Other known limitations and future design candidates are tracked in [project status](docs/project-status.md).

## Roadmap

1. **Shared Team Access — architecture/design TBD.**
2. **SharePoint integration — architecture/design TBD.**

The accepted product requirement restricts ingestion and case management to selected authorized operators rather than the whole team. The current local application does not enforce that access boundary. Both milestones require options analysis and explicit design decisions; technologies, deployment, persistence, coordination, and SharePoint's integration role remain open.

## Documentation

| Document | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Standing development instructions and accepted-baseline safeguards |
| [Project status](docs/project-status.md) | Current mutable state, acceptance, limitations, and next milestones |
| [Development guide](docs/development.md) | Setup, operational boundaries, and validation procedures |
| [Q&A architecture](docs/architecture/qa-architecture.md) | How retrieval, evidence verification, and answer release work |
| [Ingestion architecture](docs/architecture/ingestion-architecture.md) | How upload, recovery, and readiness work |
| [Case and snapshot model](docs/architecture/case-and-snapshot-model.md) | How manifests, worksheet provenance, and publication work |
| [Decision records](docs/decisions/) | Why the accepted architecture was chosen |
| [Project history](docs/project-history.md) | Evolution, lessons, and rejected or superseded approaches |

## Development and testing

Use the [development guide's network-blocked offline launcher](docs/development.md) with fake credentials and a disposable temporary directory. Choose focused tests for scoped changes; run the full suite when regression risk justifies it. Live acceptance is separately authorized and does not follow automatically from passing offline tests.
