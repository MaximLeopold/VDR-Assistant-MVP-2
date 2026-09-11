---
name: update-project-documentation
description: Controlled draft-review-apply workflow for maintaining the VDR Assistant project documentation after an accepted development milestone. Draft mode is read-only. Documentation changes may be applied only after explicit user approval and only to the approved files and content.
---

# Update Project Documentation

Maintain the VDR Assistant's repository documentation after an accepted
development milestone.

This skill has two modes:

1. **DRAFT MODE** — inspect the accepted implementation and current
   documentation, then propose a documentation update without modifying files.
2. **APPLY MODE** — only after explicit user approval, apply exactly the
   approved documentation changes and validate the resulting diff.

The default mode is always DRAFT MODE.

This skill does not implement product functionality and does not finalize a
development milestone.

## Core workflow

Use this sequence:

accepted implementation
→ inspect implementation and documentation
→ draft documentation update
→ STOP for human review
→ revise draft if requested
→ explicit human approval
→ apply only approved documentation changes
→ validate documentation diff
→ STOP

Never skip the review and approval step.

# Hard authority boundaries

This skill MAY:

- read source code;
- read tests;
- read Git state and history;
- read maintained repository documentation;
- propose documentation changes in the conversation;
- after explicit approval, edit only approved documentation files;
- after explicit approval, create an explicitly approved new decision record.

This skill MUST NOT:

- modify source code;
- modify tests;
- modify application configuration;
- modify `.agents/` skills;
- install dependencies;
- change branches;
- stage files;
- commit;
- push;
- merge;
- modify remote resources;
- run product implementation;
- automatically invoke another skill or workflow;
- create a development milestone handoff;
- infer that implementation is accepted when acceptance is unclear.

Do not make unrelated cleanup, formatting, wording, or style changes.

# Documentation authority

Read and respect the repository documentation hierarchy before proposing
changes.

Where present and relevant, consult:

1. `AGENTS.md`
2. current code and tests for implemented behavior
3. `docs/project-status.md`
4. `docs/development.md`
5. relevant files under `docs/architecture/`
6. relevant files under `docs/decisions/`
7. `README.md`
8. `docs/project-history.md`

Historical handovers, archived documents, exports, old prompts, legacy
branches, and dated historical reports are historical evidence only.

They must not override current code/tests or maintained documentation.

# Documentation classes and edit rules

Different documentation classes have different authority and mutability.

## A. Mutable current-state documentation

Normal candidates for an approved update:

- `README.md`
- `docs/project-status.md`
- `docs/development.md`
- files under `docs/architecture/`

Update these only when the accepted milestone materially changes the
information they own.

Do not update a document merely because it exists.

## B. Accepted decision records

Files under:

`docs/decisions/`

are historical records of accepted architectural or product decisions.

Existing decision records MUST NOT be silently rewritten to make history match
new implementation.

If an accepted milestone deliberately supersedes an earlier decision:

- identify the affected decision;
- explain why it appears superseded;
- propose a new decision record;
- identify the relationship to the previous decision;
- do not create the new record until explicitly approved.

Creating a new decision record is allowed in APPLY MODE only when the draft
explicitly proposed it and the user explicitly approved it.

## C. Project history

`docs/project-history.md`

may receive an approved addition when the milestone represents a meaningful
project-development event.

Do not add routine implementation details, minor refactors, or every commit to
project history.

Prefer concise milestone-level history.

## D. AGENTS.md

Treat `AGENTS.md` as sensitive repository governance.

The skill may identify that `AGENTS.md` appears to need an update, but MUST NOT
modify it through this workflow.

Report such changes as:

**Manual governance review required**

They must be handled separately.

## E. Historical and archived material

Do not modify:

- `docs/archive/`
- historical handovers;
- dated exports/reports;
- legacy historical material.

Do not reconcile historical documents with current behavior.

# Establish the milestone basis

Before drafting documentation changes, determine what accepted implementation
state the documentation should describe.

Record:

- current branch;
- current HEAD;
- working-tree status;
- relevant accepted commit or commit range when available;
- implementation areas changed;
- tests or validation supporting the accepted behavior;
- any explicit user acceptance available in the current context.

If it is unclear whether the implementation is accepted, STOP and ask the user
to confirm the milestone state.

Do not document experimental or unresolved implementation as accepted current
behavior.

If uncommitted implementation changes exist, distinguish them from accepted
baseline behavior and do not assume they should be documented.

# DRAFT MODE

DRAFT MODE is the default.

It is strictly read-only.

Do not modify or create repository files while drafting.

## Step 1 — Inspect accepted implementation changes

Determine what materially changed in:

- product capability;
- architecture;
- workflow or execution behavior;
- operational constraints;
- development or validation procedure;
- known limitations;
- accepted decisions;
- roadmap or current project status.

Do not document implementation trivia unless it affects maintained
documentation.

## Step 2 — Inspect maintained documentation

Review the documentation that could reasonably be affected.

For every relevant maintained document, classify it as:

- **UPDATE REQUIRED**
- **UPDATE OPTIONAL**
- **NO CHANGE REQUIRED**
- **REVIEW NEEDED**

Explain the reason.

Do not assume that every milestone requires changes to README, architecture,
development guidance, project status, and project history.

## Step 3 — Ground proposed changes in evidence

Every substantive proposed documentation change must be supported by repository
evidence such as:

- current source implementation;
- tests;
- accepted validation results;
- current architecture documents;
- accepted decision records;
- relevant Git commit/diff evidence;
- explicit user-approved milestone decisions.

Distinguish:

- observed implemented behavior;
- accepted design decision;
- inference;
- unresolved discrepancy.

Do not invent architecture, requirements, limitations, or roadmap commitments.

## Step 4 — Detect discrepancies

If current code/tests and maintained documentation disagree, do not silently
rewrite the documentation.

Classify the discrepancy.

Examples:

- implementation appears newer than documentation;
- documentation describes behavior not present in code;
- accepted decision conflicts with apparent implementation;
- ownership between documents is unclear.

If repository evidence does not establish which state is correct, mark:

**REVIEW NEEDED**

and ask for human resolution before APPLY MODE.

## Step 5 — Produce the draft

Return the draft in the conversation only.

Use this structure:

# Proposed Project Documentation Update

## 1. Milestone Basis

- Branch:
- HEAD:
- Accepted implementation basis:
- Relevant implementation areas:
- Validation/test evidence:
- Working-tree considerations:

## 2. Documentation Impact Summary

Provide a table:

| Document | Assessment | Reason |
| --- | --- | --- |
| ... | UPDATE REQUIRED / OPTIONAL / NO CHANGE / REVIEW NEEDED | ... |

Include relevant maintained documents even when no change is required if doing
so helps demonstrate that they were considered.

## 3. Proposed Changes

For every proposed file update:

### `<path>`

**Assessment:**  
**Reason for change:**  
**Implementation/documentation evidence:**  
**Proposed edit:**  

Provide concrete proposed wording or a clear patch-style description sufficient
for human review.

Do not hide substantive wording behind vague instructions such as "update this
section."

## 4. Decision-Record Impact

State one of:

- no decision-record impact;
- existing decision remains valid;
- possible superseding decision requires review;
- proposed new decision record.

Never propose rewriting historical decision records.

## 5. Project-History Impact

State whether this milestone warrants a project-history addition and why.

Provide proposed history wording when applicable.

## 6. Governance Impact

State whether `AGENTS.md` appears affected.

If so, identify the issue but mark:

**Manual governance review required**

Do not propose applying that change through this skill.

## 7. Unresolved Questions / Review Needed

List any discrepancies or decisions that must be resolved before documentation
can be safely applied.

## 8. Proposed Apply Scope

List exactly which files would be changed if the draft is approved.

For each file, summarize the approved type of change.

## 9. No-Change Confirmation

Confirm that DRAFT MODE modified or created no repository files and changed no
Git state.

Then STOP.

Do not apply the draft automatically.

# Approval gate

APPLY MODE requires explicit user approval.

Do NOT infer approval from statements such as:

- "looks good";
- "sounds right";
- "nice";
- "continue";
- "okay";
- general positive feedback.

Accept APPLY MODE only when the user clearly instructs you to apply the
documentation changes, for example:

- "Approved. Apply the documentation update."
- "Apply the approved draft."
- "Apply only the approved changes to project-status and development."
- another equally explicit instruction identifying that repository edits are
  authorized.

If approval scope is narrower than the draft, apply only the narrower approved
scope.

If approval is ambiguous, remain in DRAFT MODE and ask for clarification.

# Draft integrity before APPLY MODE

Before editing files, verify that the repository state still corresponds to the
draft basis.

Compare at minimum:

- branch;
- HEAD;
- relevant implementation state;
- working-tree changes affecting source/tests;
- documentation changes since the draft.

If implementation or relevant documentation changed materially after the draft,
STOP.

Explain that the draft may be stale and require regeneration or explicit
reconfirmation.

Do not apply a stale draft automatically.

# APPLY MODE

After explicit approval:

1. Restate the approved file scope.
2. Verify draft integrity.
3. Modify only the approved documentation files.
4. Apply only the approved substantive changes.
5. Do not introduce unrelated wording or formatting changes.
6. Do not modify source, tests, configuration, skills, or Git history.
7. Do not stage, commit, push, merge, or switch branches.

For an explicitly approved new decision record:

- create only the approved decision file;
- preserve existing decision records;
- identify superseded decisions where appropriate.

# Validation after applying

After edits:

1. inspect the documentation diff;
2. compare the resulting diff with the approved draft;
3. confirm no unapproved documentation file changed;
4. confirm no source code, test, configuration, or skill file changed;
5. run `git diff --check`;
6. use existing documented non-mutating documentation/link validation when
   available and appropriate;
7. do not install tooling merely to perform validation;
8. report any validation that could not safely be performed.

If the applied result differs materially from the approved draft, report the
difference clearly.

Do not silently broaden the update.

# APPLY MODE output

Return:

# Applied Project Documentation Update

## 1. Approved Scope
List approved files and changes.

## 2. Changes Applied
For each changed file, summarize the exact substantive update.

## 3. Validation
Report:

- diff review;
- `git diff --check`;
- documentation/link validation when performed;
- unexpected findings.

## 4. Repository Safety Check
Confirm:

- source code unchanged;
- tests unchanged;
- application configuration unchanged;
- skills unchanged;
- no staged files created by this skill;
- no commit;
- no push;
- no merge;
- branch unchanged.

## 5. Remaining Documentation Questions
List anything intentionally left unresolved.

Then STOP.

Do not create a development milestone handoff.
Do not commit or push the documentation changes automatically.