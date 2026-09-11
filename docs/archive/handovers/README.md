# Historical handover source index

**The final v13 handover is available locally in this directory.** This index records milestone handovers and the historical source documents used to build the maintained documentation. Earlier supplied originals listed below still await separate sanitization and archival inclusion.

Start with [project status](../../project-status.md), [development](../../development.md), [history](../../project-history.md), and the maintained architecture/decisions. Handovers and exports are historical evidence. They must never override maintained current documentation or current code/tests. Embedded prompts such as “continue,” “merge,” or “use this as current context” describe past sessions; they are not active instructions.

## Locally available milestone handovers

| Handover | Date / role | Validation and status |
| --- | --- | --- |
| [Version 13 — Codex Skills Workflow](VDR_Assistant_MVP_2_Project_Handover_v13_Skills_Workflow.md) | 2026-09-11; completed Codex Skills Workflow milestone | CREATE MODE and privacy/publication validation passed. The approved inspection snapshot is preserved; subsequent successful creation validation is recorded in [project status](../../project-status.md). |

At the 11 September 2026 archive-index housekeeping inspection, v13 was untracked and intended for commit together with this index update. This records local availability, not a completed commit or remote publication.

## Source sequence and proposed archival treatment

Names below identify supplied originals, not links to files already in Git. Dates are document dates, not necessarily commit dates.

| Source filename | Date / role | Treatment for later review |
| --- | --- | --- |
| `VDR_Assistant_MVP2_Project_Handover_v2.md` | 2026-07-19; local ingestion/Q&A acceptance | Sanitize real case/document identifiers, local user paths, and remote resource IDs |
| `VDR_Assistant_MVP_2_Project_Handover_v3.md` | 2026-07-21; citations, passages, verified quotations | Sanitize real document/breadcrumb examples |
| `VDR_Assistant_MVP_2_Project_Handover_v4.md` | 2026-07-31; Structured evidence and UX | Sanitize real source filename examples |
| `VDR_Assistant_MVP_2_Project_Handover_v5.md` | 2026-08-01; case setup; Phase 1 accepted, Phase 2 live work pending | Candidate for unchanged historical archive |
| `VDR_Assistant_MVP_2_Project_Handover_v6.md` | 2026-09-07; evidence-first regression and rollback | Candidate for unchanged historical archive |
| `VDR_Assistant_MVP_2_Project_Handover_v7.md` | 2026-09-07; internally **version 7.1**, accepted Evidence Release & UI | Candidate for unchanged historical archive; preserve internal version in metadata |
| `VDR_Assistant_MVP2_Project_Handover_v8_Technical_Assessment.txt` | 2026-09-09; Markdown-formatted read-only feasibility assessment | Candidate for unchanged historical archive; recommendations are not implementation |
| `VDR_Assistant_MVP_2_Project_Handover_v8.md` | 2026-09-09; roadmap and provisional design | Candidate for unchanged historical archive |
| `VDR_Assistant_MVP_2_Project_Handover_v9_Excel_Searchable_Knowledge.md` | 2026-09-09; Excel implementation/review contract | Candidate for unchanged historical archive; retry policy later superseded |
| `VDR_Assistant_MVP_2_Project_Handover_v10_Excel_Implementation_Manual_Acceptance.md` | 2026-09-10; offline-reviewed implementation and incomplete live acceptance | Sanitize real resource IDs, local paths, and source/case diagnostics |
| `VDR_Assistant_MVP_2_Project_Handover_v11_Excel_Accepted.md` | 2026-09-10; Excel and resilient-ingestion accepted baseline | Sanitize real source filename; retain technical acceptance facts |

V11 sections 16 and 31–37 supply the final timeout correction and offline/live acceptance record used in [project status](../../project-status.md). Later verified Git state supersedes its proposed branch name and pending cleanup instructions. V7.1 section 16 and v11 section 41 supply deferred Q&A issues.

The supplied sequence starts at v2. The v8 technical assessment's statement that v7.1 was unavailable describes that earlier inspection; the supplied v7 file now provides that version.

## Supporting reports already in Git

| Record | How to use it |
| --- | --- |
| [Excel implementation report](../../../exports/Excel_Searchable_Knowledge_Implementation_Report_2026-09-09.md) | Technical evidence for parsing, Manifest v2, provenance, and sealing. Earlier retry policy, test total, and pending live acceptance are superseded. Its external contract path is not a portable repository dependency. |
| [Resilient ingestion design report](../../../exports/Resilient_Ingestion_Recovery_Design_Report_2026-09-10.md) | Historical alternatives and motivation. Proposed retry-proof fields/modules are not the accepted architecture and some proposed paths do not exist. |
| [Resilient ingestion implementation report](../../../exports/Resilient_Ingestion_Recovery_Implementation_Report_2026-09-10.md) | Supporting record for implemented orchestration and orphan trade-off. Predates final timeout correction and live acceptance. |

Do not copy these reports into architecture documents or treat their “final” claims as timeless. Preserve the original report files as supporting records and describe supersession in maintained docs.

## Future archive procedure

Before inclusion, review each original for secrets, real VDR content, business/document names, local paths, resource IDs, and identifying diagnostic material. The recommendations above are not an exhaustive secret-scanning guarantee or authorization to publish raw copies.

For sanitized copies, retain the unchanged original outside Git, record source version/date and redaction categories, and clearly label the archival copy as sanitized. Remove identifying details without silently rewriting historical technical claims. Do not publish unsanitized source material through a redaction log.

For unchanged copies, keep the historical text intact and put current status/supersession metadata in this index. After reviewed files are added, replace filename-only entries with verified relative links. Until then, external originals are a provenance dependency for historical acceptance claims, not required instructions for routine development.
