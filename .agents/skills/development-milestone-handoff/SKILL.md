---
name: development-milestone-handoff
description: Controlled draft-review-create workflow for producing the durable VDR Assistant development milestone handover used to start future ChatGPT, Codex, and development sessions. The handover must be evidence-based, consistent with prior project handovers, aligned with maintained repository documentation, and created only after explicit user approval.
---

# Development Milestone Handoff

Create the durable development-milestone handover for the VDR Assistant project.

This handover is a project continuation artifact.

It is intended to be one of the primary starting points and context providers
for a new ChatGPT conversation, Codex session, developer workflow, or future
milestone discussion.

It must accurately describe:

- where the project currently stands;
- what milestone was completed;
- what was actually validated;
- what remains intentionally unchanged;
- what remains unresolved or deferred;
- the current repository and branch state;
- what maintained documentation is authoritative;
- what the next development session should do first.

The handover does not replace the repository, current code/tests, AGENTS.md, or
maintained project documentation.

# Workflow

This skill has two modes:

1. **DRAFT MODE** — default and strictly read-only.
2. **CREATE MODE** — only after explicit user approval of the handover content,
   version, filename, and destination.

Use this sequence:

completed or reviewable milestone
→ inspect repository and maintained documentation
→ inspect prior handover structure where available
→ establish verified milestone state
→ draft new handover in the conversation
→ STOP for human review
→ revise draft if requested
→ explicit approval of content + version + destination
→ verify draft remains current
→ create exactly one approved handover file
→ validate created file
→ STOP

Never skip the review step.

# Hard authority boundaries

## DRAFT MODE

DRAFT MODE is read-only.

You MAY:

- read AGENTS.md;
- read maintained project documentation;
- read source code and tests where needed to establish current behavior;
- inspect Git branch, HEAD, status, history, remotes, and relevant diffs;
- inspect previous handovers that are available to the current workspace;
- inspect the handover archive/index;
- inspect validation/test evidence already present in the repository or current
  session;
- produce the proposed handover in the conversation.

You MUST NOT:

- modify source code;
- modify tests;
- modify maintained documentation;
- modify skills;
- modify application configuration;
- create or delete files;
- stage files;
- commit;
- push;
- merge;
- switch branches;
- modify remote resources;
- run product implementation;
- invoke another workflow automatically.

## CREATE MODE

After explicit approval, you MAY create exactly one approved handover Markdown
file at the explicitly approved destination.

You MUST NOT:

- modify any existing repository file;
- update the handover archive/index automatically;
- update project-status, development, README, architecture, decisions, history,
  or AGENTS.md;
- modify source, tests, configuration, or skills;
- stage;
- commit;
- push;
- merge;
- switch branches;
- create more than the one approved handover file.

Any maintained-documentation update belongs to the separate
`update-project-documentation` workflow.

# Documentation and source authority

Before drafting, establish the project context using the repository's authority
model.

Where present and relevant, use:

1. current code and tests for implemented behavior;
2. AGENTS.md for repository governance and protected constraints;
3. maintained architecture documents;
4. accepted decision records;
5. docs/project-status.md for mutable current state and acceptance;
6. docs/development.md for development and validation procedures;
7. docs/project-history.md for historical milestone context;
8. docs/archive/handovers/README.md for the handover archive/index;
9. previous handover documents for historical structure and milestone context;
10. dated exports/reports only when needed as supporting historical evidence.

Historical handovers are milestone snapshots.

They do not override current code, tests, maintained architecture, accepted
decisions, project status, or development documentation.

Do not reactivate instructions, prompts, architecture assumptions, branch
names, test totals, or model configurations from an older handover merely
because they appear there.

# Prior-handover consistency

The project has an established handover style.

Where previous handovers are accessible:

- inspect the most recent relevant handover;
- inspect the archive/index when available;
- preserve recognizable naming and section conventions;
- preserve the distinction between verified current state, historical context,
  deferred issues, and future work;
- preserve a concrete next-session continuation prompt;
- preserve an explicit startup/checklist section when useful.

Do not copy stale content mechanically.

The new handover should feel like the next version of the same project record,
not a new documentation style.

If the latest prior handover file is not accessible, use the canonical structure
defined by this skill.

# Version and filename rules

Preferred filename pattern:

`VDR_Assistant_MVP_2_Project_Handover_v<version>_<short_topic>.md`

A shorter existing project naming convention may be preserved if the user
explicitly prefers it.

Determine the proposed version using this order:

1. explicit version supplied by the user;
2. latest unambiguous accessible handover version;
3. handover archive/index when it clearly identifies the latest version.

Do not guess the next version if the evidence is ambiguous.

If version cannot be determined confidently, mark:

**VERSION REVIEW REQUIRED**

and require user confirmation before CREATE MODE.

The short topic should describe the milestone concisely, for example:

- Skills_Workflow
- Shared_Team_Access
- SharePoint_Integration
- Evidence_UI

Do not create the file until both version and target path are explicitly
approved.

# Destination rules

Do not silently choose a tracked repository destination.

In DRAFT MODE, propose:

- filename;
- proposed destination if an obvious project convention exists;
- whether the proposed destination appears tracked or archival.

CREATE MODE requires explicit approval of the exact target path.

If the requested destination is inside the repository, perform the publication
and privacy checks defined below before creating the file.

Do not automatically add the handover to the archive index or Git.

# Establish current Git state

Record current repository state using read-only Git inspection.

Where available, establish:

- repository root;
- current branch;
- HEAD;
- working-tree state;
- staged state;
- upstream branch;
- local/remote divergence where relevant;
- recent milestone commits;
- important retained milestone/checkpoint branches when relevant;
- whether the current milestone is committed, pushed, merged, or still only
  present in the working tree.

Never describe a change as committed, pushed, merged, accepted, or promoted
unless evidence supports that statement.

If a milestone is still uncommitted, say so explicitly.

If the handover is drafted before final commit/push, distinguish:

- accepted working-tree state;
- committed baseline;
- intended later promotion.

# Establish milestone basis

Before writing the handover, determine:

- milestone name;
- problem or objective;
- scope that was approved;
- implementation or workflow changes made;
- files or modules materially affected;
- architecture/behavior intentionally unchanged;
- automated validation performed;
- manual/live validation performed;
- user acceptance evidence;
- outstanding validation;
- documentation updates performed;
- Git/branch promotion state.

Distinguish carefully between:

- **verified now** — confirmed from current repository/tool output;
- **documented/reported** — recorded in maintained project documentation;
- **user-confirmed** — explicitly confirmed by the project owner;
- **inferred** — reasoned from evidence but not directly verified.

Do not upgrade an inference into a fact.

# Validation reporting

Never invent or refresh test totals.

Use only counts and results that are actually supported by:

- current command output;
- maintained project documentation;
- accepted milestone reports;
- explicit user confirmation.

State whether validation was:

- static inspection;
- focused offline tests;
- full offline tests;
- mocked/synthetic testing;
- manual Streamlit/product testing;
- live OpenAI testing;
- Git/diff/documentation validation.

If a relevant validation was not run for the milestone, say so.

Do not imply that old product acceptance tests were rerun merely because a
tooling/documentation milestone completed.

# Architecture and decision reporting

The handover should contain enough architecture context for a new session to
orient itself, but it should not duplicate maintained architecture documents.

Prefer:

- concise current architecture summary;
- milestone-relevant flows;
- links/paths to authoritative architecture documents;
- accepted invariants that matter to the next phase;
- explicit boundaries that must not be changed incidentally.

Do not paste large existing architecture documents into the handover.

If architecture did not change, say so.

# Deferred issues and limitations

Carry forward only issues that remain materially relevant.

Distinguish:

- explicit deferred issues;
- known implementation limitations;
- future design candidates;
- historical experiments that should not be restored wholesale;
- open decisions requiring human discussion.

Do not turn every old idea into an active roadmap commitment.

Do not silently drop explicitly deferred issues unless maintained project
documentation shows they were resolved or intentionally removed.

# Next-phase reporting

The handover must clearly separate:

- what is complete;
- what is next;
- what is still architecture/design TBD;
- what must not yet be implemented.

For the next milestone, record:

- objective/problem area;
- current sequencing decision;
- protected current baseline;
- known open questions;
- whether architecture is accepted or still TBD.

Do not pre-decide future architecture merely to make the handover more complete.

# Session-bootstrap role

A core purpose of the handover is to start a new development session safely.

The handover must tell the next session to:

1. read AGENTS.md;
2. read docs/project-status.md;
3. read docs/development.md;
4. read the relevant architecture/decision documents;
5. verify actual Git branch, HEAD, and working tree;
6. compare actual repository state with the handover;
7. treat code/tests and maintained documentation as more authoritative than the
   handover if they differ;
8. avoid implementation until the immediate task is understood and scoped.

# Privacy and publication safety

A handover may eventually be stored in or shared from a public repository.

Do not include secrets or confidential project data.

Never include:

- API keys;
- passwords;
- tokens;
- `.env` contents;
- private authentication material;
- real confidential VDR passages;
- real client data unless explicitly approved;
- unnecessary OpenAI resource IDs;
- unnecessary vector-store IDs;
- unnecessary file IDs;
- unnecessary local case/document identifiers;
- unnecessary machine-specific private paths.

Avoid copying real VDR filenames when they are not necessary to explain the
milestone.

Use generic descriptions where possible.

If an exact identifier or path is genuinely necessary for the handover, flag it
for human privacy review before CREATE MODE.

If the approved destination is inside the repository, explicitly report:

**Publication/privacy review required**

and summarize any sensitive-looking content found before creating the file.

Do not automatically sanitize facts in a way that changes technical meaning.
Instead, flag questionable content for review.

# Canonical handover structure

Use the following structure unless the milestone clearly requires an additional
section.

# VDR Assistant MVP 2 — Project Handover

**Version:** <version>
**Date:** <date>
**Project:** VDR Assistant MVP 2
**Current status:** <concise milestone/baseline status>

---

## 1. Purpose of this handover

Explain:

- why this handover exists;
- what milestone it closes or checkpoints;
- what previous handover it supersedes when known;
- that it is intended to bootstrap a new ChatGPT/Codex/development session;
- that repository code/tests and maintained documentation remain authoritative.

## 2. Executive summary

Summarize:

- current product state;
- milestone just completed;
- most important accepted changes;
- what remained unchanged;
- current validation/acceptance state;
- immediate next phase.

This section must be understandable without reading the entire handover.

## 3. Source-of-truth and startup guidance

State the documentation/repository authority hierarchy relevant to a new
session.

Tell the next session which maintained documents to read first.

State that actual Git/repository state must be verified before implementation.

## 4. Current authoritative Git state

Record as applicable:

- current branch;
- HEAD;
- working-tree state;
- staged state;
- remote/upstream state;
- committed/pushed/merged state;
- current default/canonical development branch;
- important milestone/checkpoint branches when they matter.

Do not include irrelevant branch archaeology.

## 5. Milestone completed

Describe:

- objective;
- approved scope;
- what was implemented/configured/created;
- important design choices;
- explicit exclusions;
- files/modules materially affected.

For tooling/documentation milestones, distinguish them from product/runtime
changes.

## 6. Current accepted baseline

Summarize current accepted product and development behavior.

Include only enough detail for safe continuation.

Point to maintained architecture/status documentation for deeper detail.

Explicitly identify important behavior that the completed milestone did not
change.

## 7. Validation and acceptance

Record:

- automated/static validation;
- focused/full test results when actually available;
- manual/live validation;
- diff/Git/document validation;
- user acceptance;
- unvalidated areas.

Separate current milestone validation from historical product acceptance.

## 8. Documentation state

Record:

- maintained docs updated during the milestone;
- relevant documentation now authoritative;
- docs intentionally unchanged;
- any documentation still pending;
- whether AGENTS.md changed;
- whether the handover archive/index needs later housekeeping.

## 9. Protected invariants and accepted decisions

Carry forward only the important constraints that the next session must not
change incidentally.

Point to relevant decision records or architecture docs.

## 10. Known limitations and deferred issues

List explicit unresolved items.

Distinguish:

- deferred issue;
- known limitation;
- future candidate;
- historical experiment/reference.

Avoid turning possibilities into commitments.

## 11. Lessons or milestone-specific observations

Include only when the completed milestone produced reusable development or
architecture lessons.

Omit this section when there is nothing substantive.

## 12. Next phase

State:

- immediate next objective;
- accepted sequencing;
- architecture/design status;
- what must not be implemented yet;
- key questions to resolve next.

## 13. Recommended next-session sequence

Provide a concrete ordered startup sequence for the next ChatGPT/Codex session.

It should normally begin with:

- read AGENTS.md;
- read project status/development docs;
- verify Git state;
- inspect relevant architecture/decisions;
- confirm the immediate task;
- only then inspect/design/implement as appropriate.

## 14. Suggested opening prompt

Provide a ready-to-paste prompt for the next ChatGPT or Codex session.

The prompt must include:

- current branch/baseline;
- current milestone status;
- critical protected architecture;
- immediate objective;
- explicit instruction not to implement prematurely when design remains open.

Keep it concise enough to be practical.

## 15. Handover checklist

Provide a checklist of the conditions the next session should verify.

Include only checks relevant to the current project state.

## 16. Final status

End with a compact status block summarizing:

- major accepted milestones;
- current branch/baseline;
- working-tree state;
- current milestone status;
- immediate next phase;
- next product milestone where relevant;
- architecture status where relevant.

# Handover writing principles

The handover should be:

- factual;
- concise enough to remain usable;
- detailed enough to bootstrap a new session;
- explicit about uncertainty;
- explicit about what is verified versus merely reported;
- consistent with prior project handovers;
- grounded in the repository and maintained documentation;
- free of stale continuation instructions;
- free of unnecessary duplication from architecture documents.

Prefer exact branch names, commit hashes, status labels, and validation results
when verified.

Do not use placeholders in the final approved handover unless the user
explicitly accepts them.

# DRAFT MODE output

Return:

# Proposed Development Milestone Handover

## 1. Proposed metadata
- Version:
- Date:
- Proposed filename:
- Proposed destination:
- Milestone:
- Repository basis:

## 2. Evidence basis
Summarize the sources used to construct the handover.

## 3. Privacy/publication review
Identify any content requiring review before file creation.

## 4. Proposed handover
Provide the complete proposed Markdown handover.

## 5. Open review items
List any facts, version numbers, destination choices, or wording that require
human confirmation.

## 6. No-change confirmation
Confirm that DRAFT MODE created or modified no files and changed no Git state.

Then STOP.

Do not create the handover automatically.

# Approval gate

CREATE MODE requires explicit user approval.

Approval must identify or clearly approve:

- the draft content;
- the handover version;
- the filename;
- the exact destination path.

Do not infer approval from:

- "looks good";
- "continue";
- "okay";
- "nice";
- general positive feedback.

Examples of sufficient approval:

- "Approved. Create this as v13 at <exact path>."
- "Create the approved handover using the proposed version, filename, and
  destination."
- another equally explicit instruction authorizing creation of the one
  handover file.

If version or destination remains ambiguous, stay in DRAFT MODE.

# Draft integrity before CREATE MODE

Before creating the file, recheck:

- branch;
- HEAD;
- working-tree state;
- staged state;
- relevant milestone files;
- maintained project-status/development documentation;
- validation state if it changed after the draft.

If the repository or milestone state changed materially after the draft:

STOP.

Explain that the handover draft may be stale and must be regenerated or
explicitly reconfirmed.

Do not silently update the approved handover while creating it.

# CREATE MODE

After explicit approval:

1. Restate the approved version, filename, and exact destination.
2. Perform draft-integrity verification.
3. Perform privacy/publication review.
4. Create exactly one Markdown handover file.
5. Use the approved handover content.
6. Do not modify any other file.
7. Do not update archive/index documentation automatically.
8. Do not stage, commit, push, merge, or switch branches.

# Validation after creation

After creating the approved handover:

1. read the created file back;
2. confirm its content matches the approved draft;
3. run `git diff --check` when the file is inside the repository;
4. validate relative Markdown links when applicable and safe;
5. confirm no other file changed because of this workflow;
6. report whether the file is tracked/untracked/outside the repository;
7. report any privacy/publication concerns that remain.

# CREATE MODE output

Return:

# Created Development Milestone Handover

## 1. Created artifact
- Version:
- Filename:
- Path:
- Repository/tracking status:

## 2. Source basis
Summarize the repository/documentation state captured.

## 3. Validation
Report:
- content comparison;
- whitespace/diff validation;
- link validation when applicable;
- privacy/publication review.

## 4. Repository safety check
Confirm:
- source code unchanged;
- tests unchanged;
- maintained documentation unchanged;
- skills unchanged;
- configuration unchanged;
- no staged files created by this workflow;
- no commit;
- no push;
- no merge;
- branch unchanged.

## 5. Recommended use
State that the new handover should be supplied/read at the beginning of the
next development session together with AGENTS.md and maintained project
documentation.

Then STOP.

Do not automatically begin the next milestone.