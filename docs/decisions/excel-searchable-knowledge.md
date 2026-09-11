# Decision: deterministic worksheet search artifacts

Status: accepted; final product acceptance is recorded in [project status](../project-status.md).

## Context and decision

Excel workbooks previously contributed no searchable worksheet knowledge through this application's ingestion path. Extend ingestion while preserving File Search, citation resolution, and downstream verification.

Treat raw `.xlsx` as a preprocessing source, never a direct upload target. Parse a captured workbook deterministically with openpyxl and produce one Markdown artifact per included worksheet. Upload artifacts into the same case store as other searchable documents and resolve them back to the original workbook and worksheet.

## Alternatives considered

- Merely adding `.xlsx` to the direct-upload extension list would bypass the provenance/content contract and is prohibited.
- A whole-workbook proxy would blur worksheet identity. Range-level artifacts and technical splitting were considered but not selected for this MVP.
- Direct model workbook input and execution tools are outside this searchable-knowledge decision and may be considered as part of future analytical capabilities.
- Custom OOXML parsing was not selected over the existing parser library without a concrete blocker.

## Consequences

Keep raw sources read-only; derive formula/structure and cached-result views from the same capture. Never recalculate formulas or invent missing stored values. Omit hidden content from search output and make coverage/exclusions reviewable.

Captured-source hashes, transformation/generation identity, exact artifact hashes, and all-or-none workbook generation publication support reproducibility and provenance. Artifact-level remote state allows independent worksheet recovery without re-uploading completed siblings.

Searchability is not comprehensive Excel analysis. Advanced calculations, charts/images, macros, broader formats, and claim/cell-level verification are outside this milestone.

## Evidence and supersession

V8 and its technical assessment motivated proxies; v9 established the contract; v10 documented implementation and incomplete manual acceptance; v11 recorded final live acceptance. See [source index](../archive/handovers/README.md).

The [Excel implementation report](../../exports/Excel_Searchable_Knowledge_Implementation_Report_2026-09-09.md) supports parsing, provenance, and snapshot design. Its earlier test total, pending live status, and conservative retry rules are superseded. The current retry decision is [resilient ingestion](resilient-ingestion.md).

How it works: [case/snapshot model](../architecture/case-and-snapshot-model.md). Code/tests: [preprocessing](../../src/ingestion/excel_preprocessing.py), [parser](../../src/ingestion/excel_parser.py), [Excel target tests](../../tests/test_excel_upload_targets.py), and [provenance tests](../../tests/test_excel_snapshot_provenance.py).
