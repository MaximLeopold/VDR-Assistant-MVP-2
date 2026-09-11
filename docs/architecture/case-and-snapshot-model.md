# Case and snapshot model

The case model separates source identity, searchable artifacts, remote indexing state, and publication. See [Manifest v2 decision](../decisions/manifest-v2-and-frozen-snapshots.md) and [Excel decision](../decisions/excel-searchable-knowledge.md) for rationale.

## Registry and storage ownership

[The registry](../../src/config/case_registry.py) stores a technical `case_id` and `vdr_folder`. It does not duplicate the manifest's display name, inventory, or store ID. Opening a case requires the configured directory, a valid matching manifest, and a sealed snapshot.

[Path helpers](../../src/ingestion/paths.py) and [manifest persistence](../../src/ingestion/manifest_persistence.py) derive a sibling assistant directory:

```text
external case directory/
  VDR/                         raw source tree; read-only
  VDR Assistant/
    manifest.json              current control state
    manifest.backup.json       previous saved state
    derived/excel/
      <generation_id>/
        generation.json        generation and artifact metadata
        sheet_001.md           example included worksheet artifact
```

This illustrates runtime storage outside the application repository, not directories to create in Git. Managed temporary captures/attempts also stay outside the raw VDR tree and are normally removed after an attempt; cleanup failures are reported without changing generation status.

## Manifest v2 identities

[The schema](../../src/ingestion/manifest.py) requires `schema_version: 2`. Missing, v1, or unknown versions are rejected; there is no migration path.

| Entity | Role |
| --- | --- |
| Manifest | Case name/root, vector-store association, snapshot state, timestamps, original-source inventory |
| Direct source record | Relative source identity and its own upload/indexing state |
| Excel parent record | Original workbook identity, preparation state, coverage, and child artifacts; direct remote state remains neutral |
| Worksheet artifact | Artifact ID, worksheet name/index, generation-relative proxy path, byte size/hash, and independent remote state |
| Remote state | Persisted File ID, upload/indexing status, logical attempt count, and diagnostic state |

Original paths, artifact IDs, and persisted remote IDs must be unambiguous. A completed preprocessing record includes ordered coverage of the workbook's worksheets. Each included worksheet has exactly one artifact; excluded worksheets have none.

## Excel capture and generation

[Preprocessing](../../src/ingestion/excel_preprocessing.py) captures workbook bytes in managed storage, hashes them, and derives deterministic generation/artifact identities. [The parser](../../src/ingestion/excel_parser.py) uses openpyxl views of the same capture for formula/structure and stored results. It never saves or recalculates the original workbook.

Visible worksheets with meaningful content produce Markdown search artifacts. Hidden sheets and hidden rows/columns are omitted from searchable content; worksheet coverage and exclusion reasons make the scope reviewable. Zero/False values remain meaningful. Missing stored formula results are marked rather than invented; formula text is retained. Parser resource limits reject unsupported/oversized work rather than silently claiming complete coverage.

Each included worksheet produces one artifact with coordinates/source identity. This is searchable knowledge, not a general spreadsheet execution engine or a claim of cell-level answer verification.

A workbook's generation is published as a whole after artifact validation; partial worksheet output is not a completed generation. Existing generations are not overwritten; verified equivalent output can be reused. Orphan generation directories are not discovered and adopted as authoritative state.

## Freeze, complete, seal

1. **Preparing, unassociated:** build/review inventory, prepare or explicitly exclude workbooks, and review coverage.
2. **Preparing, associated:** vector-store association freezes inventory, generation identity, coverage, exclusions, and the association itself. Only permitted remote progress and snapshot-state changes remain.
3. **Ready:** every required searchable target is uploaded and indexed with a persisted ID; no unresolved blocking errors remain.
4. **Sealed:** persist and verify the ready snapshot's seal before registry publication. Ingestion mutations are rejected.
5. **Registered/openable:** registry points to the sealed case. Registry failure after sealing permits a registration retry, not more ingestion.

[Persistence guards](../../src/ingestion/manifest_persistence.py) also prevent clearing/replacing known IDs, changing completed targets, decreasing attempt counters, and resetting uncertainty to initial upload state. [Readiness](../../src/ingestion/case_readiness.py) is a local manifest assessment, not a fresh remote scan or a fresh hash of every original file.

Published sources are a snapshot. Changes require a fresh snapshot; registered-case synchronization/replacement automation is not implemented. A sealed manifest protects application-managed changes, not out-of-band edits to OpenAI resources.

## Citation and local-source boundary

[Resolution](../../src/retrieval/citation_resolver.py) maps an exact remote artifact ID to workbook path and worksheet identity using the selected manifest. Display names do not establish identity; unknown/ambiguous IDs cannot acquire provenance by resembling a proxy filename.

Normal Q&A uses retrieved remote text and manifest mappings, without reopening raw source descendants or generated proxies. This does not remove the directory/manifest dependency for case loading, nor turn the vector store into the authoritative raw VDR.

Atomic manifest and registry replacement avoids partial file writes but does not coordinate concurrent writers. Shared persistence, portable locators, and write ownership remain future work.

## Regression anchors

[Manifest v2](../../tests/test_excel_manifest_v2.py), [preprocessing](../../tests/test_excel_preprocessing.py), [snapshot/provenance](../../tests/test_excel_snapshot_provenance.py), [structural validation](../../tests/test_excel_structural_validation.py), [manifest persistence](../../tests/test_manifest_persistence.py), and [registration](../../tests/test_case_registry_registration.py) tests establish the boundaries above.
