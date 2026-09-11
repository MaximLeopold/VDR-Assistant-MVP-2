# VDR Assistant MVP 2 — Project Handover

**Version:** 13
**Date:** 11 September 2026
**Project:** VDR Assistant MVP 2
**Milestone:** Codex Skills Workflow
**Current status:** Completed, committed, pushed, and promoted to `Accepted-Development-Baseline`. Final v13 creation is the reserved CREATE MODE validation step.

---

## 1. Purpose of this handover

This handover closes the Codex Skills Workflow milestone and provides a starting point for the next ChatGPT, Codex, or development session.

It records the promoted repository baseline, the six accepted repo-local skills, actual validation evidence, unchanged product contracts, remaining housekeeping, and the next product milestone.

This v13 replaces earlier checkpoint descriptions for current continuation purposes. No v12 original was available during preparation, so no specific v12 contents or acceptance claims are assumed. The archive index identifies historical originals through v11; those remain historical evidence.

Current code/tests, repository governance, maintained architecture, accepted decisions, and maintained project documentation remain authoritative within their respective scopes. This handover is a dated snapshot and does not replace them.

## 2. Executive summary

The Codex Skills Workflow milestone is complete and promoted to `Accepted-Development-Baseline`.

The verified repository HEAD is:

`d0c6d855f74d4faa4aeb563a3ca149aa98f0c47b`

The accepted baseline and retained skills milestone branch point to this commit locally and on the live remote. The remote default branch is `Accepted-Development-Baseline`. At draft inspection, the working tree and index were clean.

Six repo-local skills are accepted: `grill-me`, `grilling`, `handoff`, `improve-codebase-architecture`, `update-project-documentation`, and `development-milestone-handoff`. They provide explicitly requested development workflows with clear boundaries between inspection, review, approved changes, and Git publication.

`.agents/` is development/Codex tooling only. Product runtime architecture, source code, tests, application configuration, and accepted product behavior were unchanged.

The milestone-handover skill’s static and DRAFT validation are accepted. CREATE MODE validation is reserved for creating and checking this final v13 after review. This document does not pre-claim that validation result.

Shared Team Access remains the next product milestone, followed by SharePoint integration. Architecture/design remains TBD for both. Branch cleanup is explicitly deferred to the next development session/milestone.

## 3. Source-of-truth and startup guidance

Read:

1. [AGENTS.md](../../../AGENTS.md) for governance, scope, and protected constraints.
2. [Project status](../../project-status.md) for mutable state, acceptance, limitations, and sequencing.
3. [Development guide](../../development.md) for setup, validation, and skill procedures.
4. Relevant maintained architecture and linked accepted decisions.
5. [Project history](../../project-history.md) when earlier experiments or trade-offs matter.
6. [Handover source index](README.md) for historical provenance.

Code and tests establish implemented behavior. Maintained architecture describes accepted technical behavior; decision records explain accepted rationale and trade-offs. README is the public overview.

Verify actual branch, HEAD, working tree, index, and remote synchronization before acting. Compare them with this handover. Historical prompts and old branch instructions are not active authorization.

Known documentation discrepancy: at this handover’s basis commit, project status and history still describe the skills milestone before commit/push and promotion. Git inspection and the project owner’s explicit confirmation establish that those operations are now complete. Report this discrepancy rather than treating the old pending-promotion instructions as current work. Maintained-documentation reconciliation remains a separate task.

## 4. Current authoritative Git state

Verified during DRAFT inspection on 11 September 2026:

| Item | Verified state |
| --- | --- |
| Repository | VDR-Assistant-MVP-2; paths in this handover are repository-relative |
| Current branch | `Accepted-Development-Baseline` |
| HEAD | `d0c6d855f74d4faa4aeb563a3ca149aa98f0c47b` |
| HEAD subject | `Add Codex skills workflow and development tooling` |
| Upstream | `origin/Accepted-Development-Baseline` |
| Local tracking divergence | Ahead 0; behind 0 |
| Live remote accepted branch | Same full commit as HEAD |
| Live remote default branch | `Accepted-Development-Baseline`, at the same commit |
| Working tree | Clean; no reported untracked, non-ignored files |
| Index | Clean; nothing staged |
| Retained skills branch | `Codex-Skills-Workflow-(In-Development)`, locally and remotely at the same commit |
| Promotion state | Skills commit is present on the accepted baseline locally and remotely |

The live remote was checked with a read-only reference query. No fetch, push, merge, or branch operation was performed during drafting. Equal branch pointers establish the promoted state; this handover does not infer the mechanism used to promote it.

Relevant lineage:

- `d00d26a7cf23d28f47d9bcb1dc9cabed907dbd1c`: accepted Excel and resilient-ingestion product implementation.
- `8026805`: repository development documentation foundation.
- `aec088421ee60d8e3f444554999106c62ea88cab`: README and documentation navigation.
- `d0c6d855f74d4faa4aeb563a3ca149aa98f0c47b`: accepted skills workflow and tooling.

`Repository-Documentation-(In-Development)` remains at `aec0884`. The historical `checkpoint/evidence-first-attempt` branch remains a reference for the rolled-back experiment. Neither is an instruction to switch branches or merge historical work.

Branch cleanup is deferred to the next development session/milestone and requires a separately scoped decision.

The clean state above is the pre-creation snapshot. Creating this handover inside the repository will introduce one untracked file until separately handled.

## 5. Milestone completed

The objective was to establish a reusable, controlled Codex development workflow for design discussions, inspection, documentation maintenance, continuation, and milestone handovers.

The accepted workflow set is:

| Skill | Accepted role and boundary |
| --- | --- |
| `grill-me` | Explicit wrapper loading the installed `grilling` procedure; invocation alone does not authorize edits |
| `grilling` | Design interview that develops shared understanding before action |
| `handoff` | Conversation continuation artifact in the operating system’s temporary directory |
| `improve-codebase-architecture` | Read-only architecture inspection; report in the conversation |
| `update-project-documentation` | DRAFT → human review → explicit approval → scoped APPLY → validation → STOP |
| `development-milestone-handoff` | DRAFT → human review → approval of content/version/filename/destination → create one file → validation → STOP |

Each skill has `policy.allow_implicit_invocation: false` in its `agents/openai.yaml`. An explicitly invoked wrapper may load its required dependency. The skills are not an automatically chained workflow.

The milestone commit contains 16 affected files:

- Six `.agents/skills/<skill>/SKILL.md` files.
- Six corresponding `agents/openai.yaml` files.
- `.agents/skills/THIRD_PARTY_NOTICES.md`.
- `docs/development.md`.
- `docs/project-status.md`.
- `docs/project-history.md`.

The three upstream-derived skills are attributed to `mattpocock/skills` at commit `3cca18b368ae95cdbdebbff572ccafa662551015`. The development guide and third-party notice record retained upstream content and the minimal Codex dependency adaptation in `grill-me`. The other three skills are project-specific.

See [Third-Party Notices](../../../.agents/skills/THIRD_PARTY_NOTICES.md).

The scope excluded product implementation, runtime configuration changes, product architecture changes, new live OpenAI acceptance, and implementation of future milestones.

## 6. Current accepted baseline

The product remains a local Streamlit application using the selected prepared case’s OpenAI File Search store.

Q&A follows:

Primary answer → combined support selection and verification → optional Structured evidence.

At least one verified Best excerpt is required to release the answer. Quotations are optional. The gate is answer-wide, not claim-level. Conversation history supplies context, not evidence.

Manifest-driven ingestion handles supported direct documents and deterministic worksheet search artifacts. Raw `.xlsx` files are preprocessing sources and never direct upload targets. Worksheet citations resolve through exact manifest provenance.

Returned File IDs are persisted and verified before attachment. Known-ID targets recover by exact identity without repeating File creation. Eligible no-ID targets can retry in later operator-started passes.

Publication requires 100% readiness of required searchable targets and produces sealed, frozen snapshots.

The skills milestone did not change these contracts. Product files under `app`, `src`, `tests`, and `scripts`, together with `requirements.txt` and `.env.example`, were unchanged between the accepted product implementation commit and the current HEAD.

Authoritative detail:

- [Q&A architecture](../../architecture/qa-architecture.md).
- [Ingestion architecture](../../architecture/ingestion-architecture.md).
- [Case and snapshot model](../../architecture/case-and-snapshot-model.md).

## 7. Validation and acceptance

### Verified during this DRAFT inspection

- Current branch, HEAD, upstream, local divergence, and clean working-tree/index state.
- Live remote accepted/default branch and skills branch at the same commit.
- Milestone commit contents and scope.
- Presence of the six skill definitions, six explicit-invocation policy files, and third-party notice.
- Skill boundaries and their alignment with development guidance.
- No product-file differences from the accepted implementation in the inspected runtime/test paths.
- Proposed destination absent and not ignored.
- Relative handover link targets resolve from the proposed archive directory.
- Working-tree and staged whitespace checks produced no findings.

Inspection of the committed milestone patch with `git show --check` reported 14 trailing-whitespace findings in Markdown report templates: ten in `improve-codebase-architecture/SKILL.md` and four in `update-project-documentation/SKILL.md`. These are two-space Markdown hard-break endings. They are existing committed formatting, were not changed, and must not be confused with uncommitted work or an entirely clean commit-level whitespace check.

### Documented and user-confirmed skill acceptance

The maintained status records owner acceptance on 11 September 2026:

| Skill | Acceptance evidence/status |
| --- | --- |
| `grill-me` | Accepted; dependency-loading path recorded as verified |
| `grilling` | Accepted |
| `handoff` | Accepted; successful invocation recorded |
| `improve-codebase-architecture` | Accepted; read-only validation recorded |
| `update-project-documentation` | DRAFT and APPLY workflows accepted |
| `development-milestone-handoff` | Static validation and DRAFT workflow accepted |

The project owner explicitly confirms completion and baseline promotion in the handover request. Current Git evidence independently supports the committed, pushed, and promoted repository state.

Earlier functional checks were not rerun merely to prepare this handover. No new automated skill-test count is asserted.

### Historical product acceptance

The maintained status attributes these results to the accepted v11 handover dated 10 September 2026:

- 986 offline tests passed after the attachment-timeout correction.
- 86/86 required searchable targets completed in live ingestion acceptance.
- Live Excel workbook/worksheet retrieval and citations accepted.

These are recorded historical acceptance results, not tests rerun for this tooling milestone or this draft. The repository does not contain a separate complete live-run transcript.

### Remaining validation

CREATE MODE of `development-milestone-handoff` remains reserved for creating this final v13 after explicit review approval.

Creation must be followed by readback, approved-content comparison, applicable link and whitespace validation, and confirmation that only the approved file was created. The creation report must record the actual result; this draft does not pre-certify it.

No application regression suite, manual Streamlit acceptance, or live OpenAI operation was run during DRAFT preparation.

## 8. Documentation state

The milestone updated:

- `docs/development.md`: six-skill inventory, invocation boundaries, and documentation/handover procedures.
- `docs/project-status.md`: accepted skill results and the pre-promotion finalization checkpoint.
- `docs/project-history.md`: the skills workflow milestone through final reconciliation.

The milestone did not change `AGENTS.md`, README, product architecture documents, accepted decision records, historical reports, or the archive index.

Two maintained documents lag the verified promotion:

- Project status still lists commit/push and promotion as pending.
- Project history ends the skills milestone at pre-promotion reconciliation.

These discrepancies are recorded, not silently corrected. Any later updates require their own authorized documentation scope.

The product implementation reference `d00d26a7cf23d28f47d9bcb1dc9cabed907dbd1c` remains valid. A newer tooling/documentation HEAD does not require replacing that product reference.

The archive index currently lists historical originals through v11 and states that no individual handover has been copied into the repository. If this v13 is created at the proposed archive destination, that statement will need later housekeeping. CREATE MODE does not update the index or other maintained documents.

No v12 source was available during preparation. Do not invent its metadata or contents.

## 9. Protected invariants and accepted decisions

Preserve these accepted-baseline contracts unless an explicitly scoped design decision deliberately supersedes them with corresponding validation:

- Raw VDR sources are read-only; generated artifacts remain outside the raw tree.
- File Search remains primary Q&A retrieval.
- Combined support selection follows the primary answer; optional Structured processing follows successful support.
- Release requires a verified Best excerpt; quotations are optional.
- The release gate is answer-wide, not claim-level; history is not evidence.
- Raw `.xlsx` files are never uploaded directly.
- Worksheet artifacts retain exact workbook/worksheet provenance.
- Persist and verify each returned File ID before attachment.
- Known-ID UploadTargets never call `files.create` again.
- Eligible no-ID targets may retry in later operator-started passes.
- Publication requires 100% readiness of required searchable targets.
- Published cases remain frozen/sealed snapshots.

Relevant accepted decisions:

- [File Search as primary retrieval](../../decisions/file-search-primary-qa.md).
- [Verified evidence and answer release](../../decisions/verified-evidence-and-answer-release.md).
- [Excel searchable knowledge](../../decisions/excel-searchable-knowledge.md).
- [Manifest v2 and frozen snapshots](../../decisions/manifest-v2-and-frozen-snapshots.md).
- [Resilient ingestion](../../decisions/resilient-ingestion.md).

Live OpenAI operations require explicit authorization. Offline tests must use synthetic fixtures, fake credentials, and blocked network access.

One writer per case remains an operational constraint, not an implemented lock. Development skills do not create additional runtime guarantees or authorize Git publication.

## 10. Known limitations and deferred issues

### Explicitly deferred work

- Branch cleanup: deferred to the next development session/milestone.
- Evidence formatting/whitespace preservation: source matching can flatten financial or table-like formatting.
- Claim-level grounding: the answer-wide gate does not mechanically verify every claim or main-answer table cell.
- Bounded read-only end-of-pass recovery sweep: separate ingestion/usability idea, not implemented.

### Current product limitations

- No implemented authentication, case authorization, shared deployment, or SharePoint connector.
- No ingestion lock, transactional shared persistence, background job queue, or parallel ingestion. Registry updates can race, including across cases.
- Uncertain File creation can leave unattached orphans; automatic discovery, adoption, and cleanup are absent.
- No partial publication, registered-case synchronization, or Manifest v1 migration.
- Opening a case still depends on its configured local directory and sealed manifest.
- Excel support covers bounded searchable worksheet knowledge, not recalculation, comprehensive workbook analysis, macros, chart/image interpretation, or legacy `.xls`.
- Direct documents lack the full captured-source/content-hash guarantees used for Excel artifacts.
- Compare and Summarize remain placeholders.
- Dependencies are mostly unpinned; historical model configuration does not establish the current runtime configuration or universal compatibility.

### Future candidates, not implementation commitments

Verified-evidence reuse for follow-ups, partial-answer contracts, source-derived calculation validation, richer Excel analysis, and replay/navigation improvements require separate prioritization and design. Structured-only sources and older history payloads retain documented evidence-navigation limitations.

### Historical reference

The evidence-first experiment was rolled back after live retrieval regression. Its checkpoint must not be restored wholesale. Earlier retry-proof proposals, append-only refresh/adoption workflows, and provisional shared-hosting ideas do not define the current or future architecture.

### Documentation and evidence follow-up

Promotion wording and archive housekeeping remain separate tasks. Historical handover originals still require privacy review before archival publication. No complete live acceptance ledger exists for every intermediate revision.

## 11. Lessons and milestone-specific observations

- Explicit invocation and narrow change authority make each development workflow reviewable.
- Conversation continuation, maintained-documentation updates, durable handovers, and baseline promotion are separate operations.
- Static inspection, functional skill validation, and live product acceptance establish different things.
- Repository HEAD can advance through tooling changes while the accepted product implementation reference remains unchanged.
- A committed status checkpoint can lag later Git promotion; verify actual state before repeating old continuation instructions.
- Preparing a handover should record uncertainty and remaining validation rather than imply that file creation or acceptance has already occurred.

## 12. Next phase

The immediate handover workflow is review, followed by explicitly authorized creation of one final v13 file and CREATE MODE validation.

The next development session/milestone may address the deferred branch cleanup and separately scoped documentation housekeeping.

The next product milestone is Shared Team Access. SharePoint integration follows it. Architecture/design is TBD for both.

The accepted product requirement restricts ingestion and case management to selected authorized operators rather than exposing management to the entire team. The present application does not enforce that boundary.

Shared Team Access design must establish requirements and compare options for:

- Identity and authentication.
- Case authorization and operator versus normal-user access.
- Deployment/hosting topology.
- Shared metadata persistence and storage.
- Ownership, concurrent writes, and locking.
- Background jobs/workers, if justified.

SharePoint’s connector/API approach, acquisition and synchronization strategy, and role in the future architecture remain open.

Do not begin implementation until current-system inspection, requirements/constraints, viable options, trade-offs, risks, and open questions have been reviewed and an explicit design decision obtained. Current local JSON and single-machine implementation details do not select the future architecture.

## 13. Recommended next-session sequence

1. Read `AGENTS.md`.
2. Read project status and the development guide.
3. Verify branch, HEAD, index, working tree, and relevant remote synchronization.
4. Compare actual state with this v13, including whether the handover remains untracked or has subsequently been committed.
5. Read relevant architecture and accepted decisions; consult history for earlier trade-offs.
6. Recognize the recorded pre-promotion documentation discrepancy and establish whether later housekeeping resolved it.
7. Confirm the immediate authorized task. Branch cleanup is deferred work, not automatic deletion authority.
8. For Shared Team Access, inspect the existing case, registry, ingestion, and UI boundaries; establish requirements and compare designs.
9. Obtain an explicit architecture/design decision before implementation.
10. Use repo-local skills only when explicitly requested. Do not automatically chain documentation, handover, or Git workflows.

## 14. Suggested opening prompt

Continue VDR Assistant MVP 2 from the accepted Codex Skills Workflow baseline.

At v13 inspection, `Accepted-Development-Baseline` and its live remote were at `d0c6d855f74d4faa4aeb563a3ca149aa98f0c47b`, with a clean working tree and index before handover creation. The six repo-local skills are accepted development tooling; `.agents/` is outside the product runtime. Static/DRAFT milestone-handover validation is accepted; check the subsequent creation report for CREATE MODE results.

Read AGENTS.md, project status, development guidance, relevant architecture/decisions, and v13. Verify actual Git state before acting. Account for any later handover file or documentation changes. The v13 basis documents still contained pre-promotion wording despite completed promotion.

Branch cleanup was deferred to this next session/milestone; establish its scope before changing branches or deleting anything.

The next product objective is Shared Team Access requirements and design, followed by SharePoint integration. Both architectures remain TBD. Preserve File Search primary retrieval, the answer-wide verified-Best release gate, worksheet provenance, durable File-ID recovery, and strict sealed publication.

Inspect the current system, establish requirements, compare options and trade-offs, and obtain an explicit design decision before implementation. Restrict future ingestion/case management to selected authorized operators. Do not run live OpenAI operations without explicit authorization.

## 15. Handover checklist

- [ ] Read current governance, status, development, and relevant architecture/decisions.
- [ ] Verify actual branch, HEAD, upstream, remote synchronization, working tree, and index.
- [ ] Distinguish the product implementation commit from later tooling/documentation commits.
- [ ] Confirm the six explicit-invocation skills remain present.
- [ ] Confirm the final v13 creation report before claiming CREATE MODE validation passed.
- [ ] Account for the handover file’s current tracking status.
- [ ] Check whether pre-promotion documentation wording and archive housekeeping were reconciled.
- [ ] Keep branch cleanup within separately authorized scope.
- [ ] Preserve accepted product invariants unless explicitly superseded.
- [ ] Keep Shared Team Access and SharePoint design open until accepted decisions exist.
- [ ] Keep credentials, private VDR material, local data, and live resource IDs out of Git.
- [ ] Distinguish historical acceptance from newly executed validation.

## 16. Final status

| Area | Status at this handover’s inspection basis |
| --- | --- |
| Evidence Release & UI | Accepted lineage; unchanged |
| Excel Searchable Knowledge | Accepted; unchanged |
| Resilient Ingestion & Recovery | Accepted; unchanged |
| Product implementation reference | `d00d26a7cf23d28f47d9bcb1dc9cabed907dbd1c` |
| Codex Skills Workflow | Completed, committed, pushed, and promoted |
| Accepted development/default branch | `Accepted-Development-Baseline` |
| Repository HEAD | `d0c6d855f74d4faa4aeb563a3ca149aa98f0c47b` |
| Remote synchronization | Live accepted/default and skills branches verified at HEAD |
| Working tree/index | Clean before handover creation |
| Accepted skills | Six repo-local skills; development tooling only |
| Product runtime architecture/behavior | Unchanged |
| Milestone-handover static/DRAFT validation | Accepted |
| Milestone-handover CREATE MODE validation | Reserved for final v13 creation after review; report actual result separately |
| Documentation follow-up | Promotion wording and archive housekeeping remain separate |
| Branch cleanup | Deferred to next development session/milestone |
| Next product milestone | Shared Team Access — architecture/design TBD |
| Following product milestone | SharePoint integration — architecture/design TBD |
