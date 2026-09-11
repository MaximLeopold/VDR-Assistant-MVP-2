# Decision: Manifest v2 and frozen published snapshots

Status: accepted.

## Context and decision

Worksheet artifacts create a one-source-to-many-search-target relationship. Mutable inventory and filename-based reconciliation could no longer provide the required provenance contract.

Use explicit Manifest v2 with separate original-source and worksheet-artifact identities. Recreate older cases instead of migrating v1. Freeze content at vector-store association, permit controlled remote progress until readiness, then seal before registry publication.

The registry remains a minimal locator; the manifest owns case metadata and mappings.

## Alternatives rejected or superseded

- V8's proposed backward-compatible metadata extension was superseded after recreating older cases became acceptable.
- Missing/unknown schema versions are rejected rather than inferred or silently upgraded.
- Old append-only refresh, filename/size adoption, and reconciliation workflows are not current repair/update mechanisms.
- In-place mutation of published snapshots and partial publication were not adopted.

## Consequences

A published case represents a fixed searchable snapshot. Source changes require a fresh snapshot; automated replacement/synchronization remains unimplemented. An included worksheet has one exact artifact identity and remote-state owner.

Strict readiness means 100% of required searchable targets, not 100% of every raw file: unsupported/ignored sources and explicitly excluded workbooks are outside that target set. Unresolved classification/preprocessing errors still block readiness.

Seal-before-registry preserves publication integrity across registration failure. It allows registration retry without reopening ingestion. Known IDs and completed targets cannot be reset to simulate a fresh upload.

Atomic replacement is not transactional multi-user persistence. Current local paths and the operational one-writer-per-case assumption are limitations of the present implementation that the Shared Team Access design must evaluate; they do not prescribe the future architecture.

## Evidence and implementation

Historical sources: v2/v5 for the original registry/manifest model; v8/v9 for the change in design; v11 for acceptance. See [history](../project-history.md) and [source index](../archive/handovers/README.md).

Supporting record: [Excel implementation report](../../exports/Excel_Searchable_Knowledge_Implementation_Report_2026-09-09.md), interpreted with the later [resilient-ingestion decision](resilient-ingestion.md).

How it works: [case/snapshot architecture](../architecture/case-and-snapshot-model.md). Code/tests: [manifest guards](../../src/ingestion/manifest_persistence.py), [registration](../../src/config/case_registry.py), and [snapshot tests](../../tests/test_excel_snapshot_provenance.py).
