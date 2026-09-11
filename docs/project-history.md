# Project history

This history synthesizes the supplied v2–v11 handovers and separate v8 technical assessment, checked against the accepted implementation, and records subsequent user-confirmed development milestones grounded in repository evidence. It records why the project changed; current procedures belong in [development](development.md), while current state and limitations belong in [project status](project-status.md) and the architecture documents.

The [source index](archive/handovers/README.md) identifies each original. Historical instructions, model choices, branch names, test totals, and roadmaps are dated evidence, not current operating facts.

## July: from a local Q&A prototype to controlled ingestion

Before v2, a working local Q&A application used an existing vector store. Repeatable ingestion required a local inventory, exact document identity, and recoverable progress. The July 19 v2 milestone added recursive scanning/classification, manifest persistence, store association/adoption, reconciliation, append-only refresh, and sequential upload.

Live checks demonstrated reconciliation, idempotent reruns, a newly uploaded PDF, indexing, and document-specific Q&A. A network interruption left local indexing state behind remote completion. This established the importance of persisting a returned File ID before further work: remote success and local certainty are different things.

The local end-to-end slice was accepted. Filename/size-based reconciliation and append-only refresh were later superseded by the Manifest v2 snapshot contract. Their old operator commands should not be revived as current procedures.

## July: inspectable evidence without replacing retrieval

V3 (July 21) addressed the gap between a cited answer and evidence a user could inspect. Manifest-derived folder breadcrumbs, retrieved passages, and separately selected quotations were implemented and manually validated across factual, numerical, multi-source, history, and fallback examples.

Local source-text verification became the trust boundary for displayed quotations. A model proposal alone was insufficient. V4 (July 31) extended this to figures, row-oriented tables, and horizontal financial series, with Evidence, Structured, and Raw views. Ambiguous table relationships were omitted.

V4 records offline validation and manual product review, but not a complete itemized live acceptance ledger. These features entered the accepted lineage. Their lasting distinction is between synthesized main answers and independently checked source displays; the original ranking-based passage layout was later superseded.

## Late July/August: case isolation and publication

The single-case workflow needed controlled case preparation and selection. V5 (August 1) introduced a minimal registry, case-specific chat state, and a guided workflow backed by reusable services. The registry located a case; its manifest remained authoritative for metadata and remote mappings.

Phase 1—scan, manifest creation, empty-store association, and resumption—was manually accepted. Phase 2—upload, readiness, and registration—was implemented and offline-tested, but live ingestion/registration and second-case isolation were still pending in v5. Do not retroactively describe that document as full Phase 2 live acceptance.

The implementation retained explicit publication after readiness and made registration independently retryable. Later commits improved downstream Q&A; the handovers are not a complete acceptance record for each intervening commit.

## September 7: an evidence-first experiment was rolled back

The evidence-first redesign sought stronger grounding, partial answers, evidence reuse, and controlled calculations. It replaced the established primary retrieval path with a single direct vector-store search, then built a typed evidence packet before answer generation.

Mocked tests passed. A live compound KPI question nevertheless lost useful financial/customer coverage because the candidate set emphasized another category. Downstream selection could not recover missing evidence. Restoring the File Search answer-first baseline recovered the materially better result on the representative question.

V6 records the rollback and preservation of the experiment at `checkpoint/evidence-first-attempt`. This is historical reference, not a source to merge wholesale. A subsequent attempt to combine mandatory File Search with typed selection did not establish working compatibility in that setup. It does not prove a universal API restriction.

The tested retrieval replacement was rejected. Stronger claim-level grounding remains explicitly deferred, while evidence reuse, partial-answer handling, and calculations remain possible future design directions, not accepted roadmap commitments. The rollback did not reject those underlying goals. The lasting lesson is to evaluate live retrieval breadth independently from schema correctness and deterministic verification. See [the File Search decision](decisions/file-search-primary-qa.md).

## September 7: Evidence Release & UI was accepted

The supplied v7 file identifies itself as version 7.1. It records an accepted narrower improvement to the restored architecture: at least one verified Best excerpt releases an answer; quotations are optional. Best/Additional selection and evidence presentation replaced overly restrictive release rules and awkward central displays.

Offline checks and live Q&A/UI review supported acceptance. A local model configuration change also improved observed answers, without constituting an architecture change. That historical configuration is not a permanent repository default.

This deliberately remained an answer-wide gate. Evidence formatting / whitespace preservation and claim-level grounding remain explicitly deferred Q&A issues. Previous verified-evidence reuse, partial-answer handling, source-derived calculation validation, and replay/navigation improvements are known limitations or future design candidates, not accepted roadmap commitments. Optional Structured failure must not suppress an otherwise supported answer. See [the evidence-release decision](decisions/verified-evidence-and-answer-release.md).

## September 9: roadmap assessment became an Excel snapshot contract

V8 and the separate technical assessment explored possible approaches to Excel, Shared Team Access, and SharePoint. These were design/inspection records, not implementation or live acceptance. Their shared hosting, persistence, write-coordination, and SharePoint acquisition proposals were exploratory, not accepted future architecture. They distinguished remote searchable evidence from the local manifest/registry still required to locate and open cases.

The accepted sequence became Excel Searchable Knowledge → Shared Team Access → SharePoint. Deterministic worksheet proxies preserved the existing File Search and citation path. Advanced workbook execution remained outside the searchable-knowledge scope and may be considered as part of future analytical capabilities.

V9 converted that direction into a detailed contract. Once recreating older cases was acceptable, Manifest v2 became a clean break rather than a backward-compatible extension. Captured workbook bytes, deterministic worksheet artifacts, hashes, coverage, immutable generations, frozen inventory, and sealing established snapshot provenance.

One artifact per included worksheet replaced broader suggestions of range-level artifacts or invisible technical splitting for this MVP. V9 was an implementation/review contract, not evidence of completed live retrieval. See [Excel](decisions/excel-searchable-knowledge.md) and [snapshot](decisions/manifest-v2-and-frozen-snapshots.md) decisions.

## September 10: live uncertainty changed the recovery policy

V10 records the implemented Excel feature and a fix binding retry authorization to the exact candidate context, rather than a relative path alone. Offline validation supported proceeding to manual acceptance.

A real workbook produced eight worksheet targets within an 86-target plan. An early upload returned no usable ID and stopped the candidate under the conservative uncertainty policy. Excel live acceptance was still incomplete.

The subsequent resilient-ingestion design report proposed durable retry proofs and extra metadata. The implemented contract instead accepted possible unattached orphans and removed session-bound retry proofs. Eligible no-ID targets could retry in later operator-started passes; known-ID targets reconciled exact resources without repeating File creation. Target-local problems could be recorded while unrelated work continued.

A final correction separated attachment transport timeouts from the short polling scheduling window. V11 records final offline acceptance, full live ingestion completion through known-ID recovery and a later no-ID retry, and successful Excel workbook/worksheet Q&A and citation. Exact acceptance totals live in [project status](project-status.md).

The [resilient-ingestion decision](decisions/resilient-ingestion.md) preserves the central trade-off: protect the searchable corpus while accepting that uncertain remote File creation cannot be made exactly-once by local JSON checkpoints.

## September 11: Codex Skills Workflow reached final reconciliation

The project established six explicitly invoked repo-local skills for design interviews, conversation continuation, read-only architecture inspection, controlled documentation updates, and durable development milestone handovers. The workflow separates inspection and drafting from approved file changes and leaves Git publication and baseline promotion to separately authorized work.

The project owner accepted `grill-me`, `grilling`, `handoff`, `improve-codebase-architecture`, and the documentation skill’s DRAFT/APPLY workflows. Static validation and DRAFT validation of `development-milestone-handoff` were also accepted, with CREATE MODE validation reserved for creation of the final v13 handover.

This brought the tooling milestone to final documentation reconciliation before commit/push and baseline promotion. Product runtime behavior and architecture were unchanged. [Project status](project-status.md) owns the dated acceptance and outstanding finalization work; [development](development.md#repo-local-codex-skills) owns the procedures.

## Accepted boundaries and future work

The v8 shared-instance suggestion to disable ingestion was provisional. V11 narrowed the operating assumption toward a small number of selected authorized ingestion operators rather than team-wide management access. The milestone sequence and selected-operator requirement are accepted, while the implementation architecture remains open and requires dedicated options analysis and an explicit design decision. Earlier hosting, persistence, and write-coordination proposals do not select technologies or mechanisms. SharePoint integration is a later milestone whose role in the future architecture remains to be designed.

Explicitly superseded approaches include the tested direct-search replacement, mandatory quotations, Manifest v1 compatibility, old append-only refresh/adoption workflows, and durable/session-bound retry-proof designs.

- **Explicitly deferred Q&A issues:** evidence formatting / whitespace preservation and claim-level grounding.
- **Known limitations / future design candidates:** partial-answer handling/contracts, verified evidence reuse, source-derived calculations, richer Excel analysis, replay/navigation improvements, and a bounded read-only end-of-pass recovery sweep (the separately deferred ingestion/usability idea).
- **Planned product milestones:** Shared Team Access next, followed by SharePoint integration; architecture/design TBD for both.

Future design candidates are neither approved implementation commitments nor permanently rejected ideas.

Recurring lessons are to protect proven retrieval quality, distinguish offline correctness from live acceptance, preserve exact identity across failures, separate completion from publication, and document changes in guarantees rather than only additions to features.
