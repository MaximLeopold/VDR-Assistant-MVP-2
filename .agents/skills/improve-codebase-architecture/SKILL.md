---
name: improve-codebase-architecture
description: Read-only architecture inspection for the VDR Assistant repository. Use only when explicitly invoked to inspect current architecture, identify evidence-backed improvement opportunities, compare implementation with maintained architecture and decisions, and produce recommendations without modifying the repository.
---

# Improve Codebase Architecture

Perform a read-only architecture inspection of the VDR Assistant repository.

This skill analyzes and recommends. It does not implement.

If the user provides an argument, treat it as the requested inspection scope.
If no argument is provided, inspect the repository architecture broadly.

## Hard read-only contract

You MUST NOT:

- modify source code;
- modify tests;
- modify documentation;
- modify configuration;
- create or delete files;
- create temporary reports;
- install dependencies;
- run formatters or code generators;
- create or switch branches;
- stage files;
- commit;
- push;
- merge;
- modify remote resources;
- automatically invoke another implementation or documentation workflow.

Do not run commands that are expected to mutate the repository or filesystem.

The final architecture report must be returned in the conversation only.

## Establish project context first

Before judging the architecture, read and respect the repository's documentation authority.

Read, where present and relevant, in this order:

1. `AGENTS.md`
2. `docs/project-status.md`
3. `docs/development.md`
4. relevant files under `docs/architecture/`
5. relevant files under `docs/decisions/`
6. current implementation code
7. current tests
8. relevant read-only Git history and change hotspots

Current code and tests remain authoritative for implemented behavior.
Maintained architecture documents and accepted decision records provide the
intended design and rationale.

Historical handovers, archived material, exports, old prompts, and legacy
branches are historical evidence only unless the user explicitly asks for them.

Do not treat a generic architecture preference as more authoritative than an
accepted project decision.

## Inspection method

Build an evidence-based view of the current architecture before making
recommendations.

Inspect:

- major modules and responsibilities;
- important interfaces and seams;
- dependency directions;
- orchestration versus domain logic;
- important execution and data flows;
- persistence and external-system interactions;
- testing seams and testability;
- areas of repeated change where Git history provides useful evidence;
- alignment between implementation and maintained documentation.

Use repository evidence rather than assumptions.

## Architecture lenses

Apply these design principles where useful.

### Module depth

A useful module provides meaningful behavior behind an interface that callers
can understand without learning unnecessary implementation detail.

Ask:

- Can the interface be smaller?
- Can parameters or required caller knowledge be simpler?
- Is meaningful complexity being hidden behind the module?
- Is a module merely forwarding calls without providing locality or leverage?

Do not judge depth by implementation line count.

### Locality

Prefer designs where related behavior, knowledge, change, bugs, and verification
are concentrated rather than scattered across unrelated callers or modules.

Identify scattered responsibility only when repository evidence supports it.

### Seam placement

A seam is a place where behavior can vary without modifying the caller.

Assess whether existing seams correspond to real variation.

Do not recommend speculative abstractions merely because a second implementation
could theoretically exist.

One implementation alone is not sufficient evidence that another seam is needed.

### Testability through interfaces

Callers and tests should normally exercise behavior through the intended module
interface.

Repeated need to reach deeply into implementation details may indicate an
architecture issue, but do not assume that difficult tests automatically imply
bad architecture.

Explain the actual architectural consequence.

### Deletion test

For a suspicious abstraction, consider what happens if it disappears.

If deleting it makes complexity disappear, it may be a shallow pass-through.

If deleting it causes the same complexity to reappear across multiple callers,
the abstraction is probably providing useful locality or leverage.

### Change hotspots

Read-only Git history may be used to identify:

- frequently co-changing files;
- repeatedly modified modules;
- recurring bug-fix areas;
- modules touched by many unrelated changes.

Treat change frequency as a signal, not proof of poor architecture.

## Avoid architecture theater

Do not recommend restructuring merely because another design is aesthetically
cleaner or more fashionable.

A recommendation should address a concrete issue such as:

- duplicated complexity;
- weak locality;
- excessive caller knowledge;
- unclear responsibility;
- difficult testing caused by module shape;
- repeated cross-module changes;
- inconsistent or misplaced seams;
- architecture/documentation drift;
- material operational or maintenance risk.

Prefer the smallest architectural improvement that addresses the demonstrated
problem.

## Respect accepted architecture

Explicitly identify accepted architecture and invariants that should be preserved.

If an implementation matches an accepted decision, do not label it an issue
merely because a different architecture is possible.

If code and maintained documentation disagree, report the mismatch. Do not
silently decide whether the implementation or the documentation is wrong unless
repository evidence clearly establishes the answer.

## Finding classifications

Classify findings as one of:

- **Confirmed architecture issue**
- **Improvement opportunity**
- **Documentation / implementation mismatch**
- **Open architectural question**
- **Intentional design — preserve**

For substantive findings, provide:

- **Impact:** High / Medium / Low
- **Confidence:** High / Medium / Low

Impact describes importance.
Confidence describes strength of evidence.

## Evidence requirements

Every substantive finding must identify its basis, such as:

- source file/module/function;
- test file or test behavior;
- maintained architecture document;
- accepted decision record;
- relevant Git-history evidence.

Distinguish observation from inference.

Do not invent project requirements that are not supported by code, tests,
maintained documentation, or explicit user instructions.

## Output

Return the report in the conversation using this structure:

# Architecture Inspection Report

## 1. Scope
State the inspection scope, current branch and HEAD when available, documentation
consulted, code/test areas inspected, and Git-history range considered.

## 2. Executive Summary
Summarize the architecture and the most important findings. State whether
meaningful architecture work appears warranted.

## 3. Observed Architecture
Describe the major modules, responsibilities, interfaces/seams, and important
flows relevant to the inspection.

## 4. Alignment With Documented Architecture

### Aligned
### Deviations
### Unclear / Undocumented

## 5. Findings

For each substantive finding include:

### Finding N — <title>

**Classification:**  
**Impact:**  
**Confidence:**  

**Observation:**  
**Evidence:**  
**Relevant documented context:**  
**Why it matters:**  
**Potential direction:**  
**Trade-offs / risks:**  
**Validation required before implementation:**  

## 6. Improvement Candidates
Provide a prioritized summary of credible improvement candidates, including
expected benefit, complexity, risk, and suggested priority.

## 7. Intentional Architecture to Preserve
Identify important accepted architecture and invariants that should not be
casually changed.

## 8. Open Questions
List issues requiring human/product/architecture decisions rather than further
code inspection.

## 9. Recommended Discussion Order
Recommend which findings or questions the user should examine first and why.

## 10. No-Change Confirmation
Explicitly confirm that the inspection did not modify repository files, Git
state, documentation, source code, tests, configuration, or remote resources.

Stop after the report.

Do not implement recommendations automatically.