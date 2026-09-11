# Project status

Reviewed: 11 September 2026.

This document owns mutable project state and dated acceptance results. Read the [development guide](development.md), [architecture](architecture/qa-architecture.md), and [history](project-history.md) for procedures, behavior, and rationale.

## Accepted baseline

| Item | Accepted state |
| --- | --- |
| Development/default baseline | `Accepted-Development-Baseline` |
| Codex Skills Workflow | Complete; all six repo-local skills accepted, including milestone-handover CREATE MODE |
| Accepted implementation commit | `d00d26a7cf23d28f47d9bcb1dc9cabed907dbd1c` |
| Excel Searchable Knowledge | Accepted |
| Resilient Ingestion & Recovery | Accepted |
| Authoritative final offline acceptance | **986 tests passed**, after the attachment-timeout correction |
| Full live ingestion acceptance | **86/86 required searchable targets** |
| Live Excel Q&A acceptance | Workbook/worksheet retrieval and citations accepted |
| Next product milestone | **Shared Team Access** — architecture/design TBD |
| Following milestone | **SharePoint integration** — architecture/design TBD |

The accepted implementation commit identifies the product baseline. Later tooling and documentation commits may advance repository HEAD without changing this accepted implementation reference.

The acceptance results are recorded in the accepted v11 milestone handover, dated 10 September 2026, sections 16 and 31–37; the branch and commit reflect subsequently verified Git state. The documentation review did not rerun the offline suite, live ingestion, or live Excel Q&A acceptance. These records are not a continuously monitored remote count or a claim that every workbook feature has been live-tested. Handover identifiers and archival status are listed in the [source index](archive/handovers/README.md).

The resilient-ingestion implementation report records an earlier 981-test state. After the attachment-timeout correction and its additional validation, the authoritative final offline suite recorded in v11 was 986 passing tests. Earlier Excel and handover totals describe earlier revisions.

## Codex Skills Workflow — complete, 11 September 2026

The Codex Skills Workflow milestone is complete. Commit `d0c6d855f74d4faa4aeb563a3ca149aa98f0c47b` (`Add Codex skills workflow and development tooling`) was committed, pushed, and promoted to `Accepted-Development-Baseline`. The project owner confirmed final milestone completion on 11 September 2026.

Six skills are installed under `.agents/skills/`. This directory contains development/Codex tooling only and is not part of the VDR application runtime. The [development guide](development.md#repo-local-codex-skills) owns the inventory and workflow procedures.

| Skill | Accepted result |
| --- | --- |
| `grill-me` | Accepted |
| `grilling` | Accepted |
| `handoff` | Accepted |
| `improve-codebase-architecture` | Accepted |
| `update-project-documentation` | DRAFT and APPLY workflows accepted |
| `development-milestone-handoff` | Static validation, DRAFT workflow, and CREATE MODE accepted |

Earlier validation records establish skill discovery, the `grill-me` dependency-loading path, successful `handoff` invocation, read-only architecture-skill validation, and documentation-skill validation. These checks were not rerun during this final documentation reconciliation.

CREATE MODE passed by creating the approved [Version 13 milestone handover](archive/handovers/VDR_Assistant_MVP_2_Project_Handover_v13_Skills_Workflow.md). The creation report confirmed that readback matched the approved draft exactly, all 14 relative links resolved, whitespace validation found no errors, privacy/publication review found no sensitive content requiring removal, and only the approved handover file was created. No staging, commit, push, merge, branch switch, or archive-index update occurred during creation.

The final v13 preserves its approved inspection snapshot, including statements reserving CREATE MODE validation for subsequent creation. The successful creation report and this status update record that subsequent result; the historical handover is not rewritten.

At the final reconciliation inspection, `Accepted-Development-Baseline` remained at `d0c6d855f74d4faa4aeb563a3ca149aa98f0c47b`, with no tracked changes and nothing staged. The final v13 handover was the sole untracked file. This is a dated inspection state, not a claim that the handover or subsequent documentation changes have been committed or pushed.

Branch cleanup remains explicitly deferred to the next development session/milestone. Archive-index housekeeping requires a separate scope; it is not performed by the documentation skill. These follow-ups do not reopen the accepted skills milestone.

Product runtime architecture, behavior, configuration, the accepted product implementation reference, and dated product acceptance results remain unchanged. No application regression suite, manual Streamlit acceptance, or live OpenAI acceptance was rerun for this reconciliation. Shared Team Access remains the next product milestone, followed by SharePoint integration; architecture/design remains TBD for both.

## Accepted behavior

- Local Streamlit Q&A uses the selected case's OpenAI File Search store.
- Primary answer → combined support selection → optional Structured evidence. At least one verified Best excerpt releases the answer; quotations are optional. The gate is answer-wide.
- Direct supported documents and generated worksheet artifacts share manifest-driven ingestion. Raw `.xlsx` files are never direct upload targets.
- Eligible no-ID targets can retry in later operator-started passes. Known-ID targets use exact-ID recovery and never repeat File creation.
- Publication requires all required searchable targets to complete. Published cases are sealed snapshots.

Details belong in [Q&A architecture](architecture/qa-architecture.md), [ingestion architecture](architecture/ingestion-architecture.md), and the [case/snapshot model](architecture/case-and-snapshot-model.md).

## Known limitations

- No implemented authentication, case authorization, shared deployment, or SharePoint connector. The future architecture remains open, as described below.
- One writer per case is an operational rule only. There is no ingestion lock, transactional shared persistence, background job queue, or parallel ingestion. Registry updates can also race, including between different cases.
- Uncertain File creation can leave unattached orphan Files. Automatic discovery, adoption, and cleanup of these orphans are not implemented.
- No partial publication, registered-case synchronization, or Manifest v1 migration. Missing/unsupported schema versions require case recreation under v2.
- Ordinary Q&A does not reopen raw source documents, but case loading still requires the configured local directory and sibling sealed manifest.
- Excel support is bounded searchable knowledge: visible worksheet content, stored formula results and formula text, without recalculation or comprehensive workbook analysis. Hidden content is omitted from searchable output; coverage/exclusions must be reviewed. Legacy `.xls`, chart/image interpretation, macros, and advanced calculations are outside this milestone.
- Direct-document preflight does not provide the full captured-source/content-hash guarantees used for Excel artifacts.
- Compare and Summarize have placeholders, not implemented product workflows.
- Model configuration is runtime-dependent. Historical manual acceptance used a particular configuration; this does not establish today's local setting or universal model compatibility. Dependencies are mostly unpinned; see [development](development.md).

## Upcoming milestones: design TBD

Shared Team Access is next, followed by SharePoint integration. Neither milestone has an accepted technical architecture or implementation design. Ingestion and case-management capabilities must be restricted to a small number of selected authorized operators rather than exposed to the full team. This is an accepted product requirement, not a choice of implementation.

Open design dimensions include authentication and identity provider, authorization model, operator versus normal-user UI separation, deployment/hosting model and topology, shared metadata persistence and database/storage technology, case ownership/write coordination/locking, and whether background jobs or workers are needed. SharePoint's API/connector approach, source acquisition/synchronization strategy, and whether its role is limited to ingestion or extends elsewhere in the future architecture also remain open.

Both milestones require current-system inspection, requirements and options analysis, and an explicit design decision before implementation. Current local MVP constraints and single-machine/local-JSON details do not select the future architecture.

## Explicitly deferred Q&A issues

The accepted v11 milestone handover explicitly carries forward these two deferred Q&A issues. Excel and resilient ingestion did not resolve them:

1. **Evidence formatting / whitespace preservation:** `_source_derived_match()` can flatten financial/table-like formatting or whitespace.
2. **Claim-level grounding:** the current answer-wide Best-excerpt release gate does not mechanically verify every factual claim, sentence, bullet, or main-answer table cell.

## Other known Q&A limitations / future design candidates

These implementation observations are not accepted roadmap commitments. Addressing them requires separate prioritization and design:

1. Previously verified passages are stored for replay but are not reused as structured evidence for follow-ups; follow-ups perform fresh retrieval with conversational context.
2. A supported/unsupported partial-answer contract and source-derived calculation validation need separate designs compatible with the current retrieval path.
3. Structured-only sources can lack a Best/Additional-associated original-passage navigation entry.
4. Older raw-only history payloads may have different central evidence visibility under current UI filtering.

## Deferred ingestion / usability idea

A bounded read-only end-of-pass recovery sweep remains a separate deferred ingestion/usability idea. It is not implemented.

## Documentation status and unresolved evidence

The maintained foundation is in place. The [README](../README.md) has been modernized as the public-facing overview. Detailed current behavior remains governed by code/tests, maintained architecture, decision records, and development guidance. The [exports](../exports/) remain supporting historical records. Historical handover originals listed in the source index still await separate sanitization and archival review. The final v13 handover has been created locally and passed its privacy/publication review; its untracked status and the separate archive-index housekeeping are recorded above.

Current implementation facts are grounded in source and tests. Full acceptance is recorded in the accepted v11 milestone handover; the repository does not include a separate live-run transcript. The handover sequence also lacks a complete live acceptance ledger for every intermediate commit.

Do not resolve these gaps by inferring successful live runs from passing mocks. Update this document when acceptance, limitations, or the next milestone change.
