# Decision: retain File Search as primary Q&A retrieval

Status: accepted. This records the September Q&A baseline decision; see [current status](../project-status.md) for milestone state.

## Context and decision

The established answer-first path produced useful answers using OpenAI File Search. Preserve that primary retrieval mechanism and improve support verification/presentation downstream. Current execution is documented in [Q&A architecture](../architecture/qa-architecture.md).

## Alternatives and evidence

An evidence-first checkpoint replaced primary retrieval with one direct vector-store search, then selected typed evidence before generation. Mocked tests passed, but a representative live compound KPI question lost relevant categories. Restoring the prior File Search path recovered the better answer.

A later File Search/typed-output spike was unsuccessful in its tested setup. It did not establish that such combinations are universally impossible.

The tested direct-search replacement was rolled back. It should not be reintroduced as an incidental refactor or merged wholesale from the checkpoint.

## Consequences

Retrieval coverage, generation quality, deterministic evidence checking, and UI presentation must be evaluated separately. A stricter verifier cannot recover facts absent from its evidence scope. Retrieval-changing work requires representative live comparison as well as offline regressions.

Claim-level grounding, partial answers, evidence reuse, and calculations remain possible future goals; this decision rejects the tested replacement, not those goals.

## Evidence and implementation

Historical rationale: v6 and v7.1 in the [handover index](../archive/handovers/README.md); synthesized in [project history](../project-history.md).

Current code: [retrieval service](../../src/retrieval/openai_file_search.py) and [chain](../../src/chains/qa_chain.py). Regression evidence: [File Search tests](../../tests/test_openai_file_search.py) and [Q&A support tests](../../tests/test_qa_chain_quotes.py).
