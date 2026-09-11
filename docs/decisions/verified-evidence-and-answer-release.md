# Decision: source-verified evidence with an answer-wide release gate

Status: accepted.

## Context and decision

Citations alone did not give users inspectable support, while requiring both Best evidence and a quotation withheld otherwise useful answers. Preserve the primary provisional answer, then use one combined selection call and deterministic source checks.

Release an answer when at least one verified Best excerpt exists. Quotations are optional. Additional excerpts are context, never automatically promoted to Best. Optional Structured processing follows successful support and cannot veto it.

## Alternatives

- Primary-model quotations without independent verification were replaced by source-checked selections.
- Ranking-based first-passage display was superseded by semantic Best/Additional selection.
- Requiring quotations as an additional release condition was superseded.
- Claim schemas and evidence-first typed answers were not adopted into this accepted gate.

## Consequences and limits

Verification establishes that selected text is traceable to the identified retrieved source. Semantic support selection remains model-assisted. The gate is **answer-wide, not claim-level**: it does not prove every statement or main-answer table cell.

A cited source with no verified Best, Additional, or quotation material does not automatically block release if another cited source provides a verified Best excerpt. The gate is answer-wide, not per-source; a source lacking verified material must not be presented as having verified support.

Combined-selector failure or no verified Best withholds the provisional answer. Missing/rejected quotes alone do not. Ambiguous Structured candidates are omitted; optional processing failure preserves supported content.

Evidence formatting / whitespace preservation and claim-level grounding remain explicitly deferred Q&A issues, as recorded in [project status](../project-status.md). Whitespace normalization can flatten selected table excerpts.

Previous verified-evidence reuse, partial-answer contracts, source-derived calculation validation, and replay/navigation improvements are known limitations or future design candidates, not accepted roadmap commitments. They are not solved by the current gate.

## Evidence and implementation

Historical rationale: v3/v4 and accepted v7.1, with deferred issues retained in v11; see [history](../project-history.md) and [source index](../archive/handovers/README.md).

How it works: [Q&A architecture](../architecture/qa-architecture.md). Code/tests: [excerpt verification](../../src/validation/evidence_selection_verifier.py), [quotation verification](../../src/validation/quote_verifier.py), [release tests](../../tests/test_qa_chain_quotes.py), and [Structured tests](../../tests/test_qa_chain_presentations.py).
