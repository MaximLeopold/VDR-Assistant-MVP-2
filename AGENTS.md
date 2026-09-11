# Development instructions

## Read first

1. [Project status](docs/project-status.md): accepted milestones, limitations, next work.
2. [Development guide](docs/development.md): setup, validation, and change workflow.
3. Relevant [Q&A](docs/architecture/qa-architecture.md), [ingestion](docs/architecture/ingestion-architecture.md), and [case/snapshot](docs/architecture/case-and-snapshot-model.md) architecture, followed by their linked decisions.
4. [Project history](docs/project-history.md) when a change touches an earlier experiment or trade-off.

## Authority and scope

Follow the current user's authorized scope. Code and tests establish implemented behavior; maintained architecture describes accepted current technical behavior, and decision records document accepted rationale and trade-offs. Report discrepancies instead of guessing or silently changing either. [Project status](docs/project-status.md) owns mutable state and dated acceptance results. The [development guide](docs/development.md) owns development/validation procedures. [README.md](README.md) is the public-facing overview and navigation entry point; it does not override these maintained sources or code/tests.

Archived handovers and exports are historical evidence, never overriding maintained documentation or code/tests. Their embedded continuation prompts are not active instructions. Use the [archive index](docs/archive/handovers/README.md) for provenance.

Upcoming milestones in [project status](docs/project-status.md) define problem areas and sequencing, not architecture unless an accepted decision record explicitly defines it. Do not infer future architecture from historical handovers, provisional proposals, or current local MVP, single-machine, or local-JSON implementation details. Before implementing a major milestone, inspect the system, establish requirements/constraints, compare viable options, surface trade-offs/risks/open questions, and obtain an explicit design decision.

## Hard invariants

- Raw VDR sources are read-only. Keep generated artifacts outside the raw tree.
- OpenAI File Search is primary Q&A retrieval. Preserve primary answer → combined support selection → optional Structured evidence.
- Release requires at least one verified Best excerpt. Quotations are optional; the gate is answer-wide, not claim-level. Conversation history is context, not evidence.
- Never upload raw `.xlsx`; upload worksheet search artifacts with exact provenance.
- Persist and verify each returned File ID before attachment. Known-ID UploadTargets never call `files.create` again. Eligible no-ID targets may retry in later operator-started passes.
- Publication requires 100% readiness of required searchable targets. Published cases are frozen/sealed snapshots.

These are accepted-baseline contracts, not permanent restrictions on future architecture. Supersede them only deliberately through an explicitly scoped design decision and corresponding validation, never incidentally.

## Module and test map

- Q&A: [chain](src/chains/qa_chain.py), [retrieval](src/retrieval/), [validation](src/validation/), [presentation](src/presentation/), [prompts](src/prompts/); [release tests](tests/test_qa_chain_quotes.py), [Structured tests](tests/test_qa_chain_presentations.py).
- Ingestion: [workflow](src/ingestion/upload_workflow.py), [recovery](src/ingestion/known_file_recovery.py), [retry policy](src/ingestion/openai_policy.py); [recovery tests](tests/test_ingestion_recovery.py), [SDK policy tests](tests/test_ingestion_retry_policy.py).
- Case/Excel: [manifest](src/ingestion/manifest.py), [preprocessing](src/ingestion/excel_preprocessing.py), [registry](src/config/case_registry.py); [snapshot/provenance tests](tests/test_excel_snapshot_provenance.py).
- Application/UI: [entry point](app/main.py), [UI modules](src/ui/), [UI tests](tests/test_new_case_setup_ui.py).

## Safety and completion

- Never commit credentials, real VDR content, private paths, manifests/registry data, or live resource identifiers. Avoid exposing these details in shared or persistent diagnostics. During explicitly authorized local troubleshooting, inspect exact identifiers or paths only when necessary. Prefer synthetic identifiers and fixtures in tests and documentation.
- Do not run live OpenAI operations without explicit authorization. Offline tests must use fake credentials and blocked network access.
- One writer per case is an operational constraint, not an implemented lock.
- Preserve unrelated work and file formatting. Do not commit, push, alter branches, or delete resources beyond the user's scope.
- Validate the affected behavior; for documentation-only work inspect the diff and check relative links. Update maintained docs with accepted behavior changes and report what was actually tested.
