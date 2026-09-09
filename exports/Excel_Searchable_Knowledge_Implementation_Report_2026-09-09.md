# Excel Searchable Knowledge MVP — implementation report

Date: 2026-09-09  
Contract: `C:\Users\luet087\Downloads\Codex Implementation Contract — Excel Searchable Knowledge MVP.md`

## A. Executive result

**Implementation complete pending manual retrieval acceptance.** The implementation and offline validation are complete. The final full offline run passed **881 tests in 40.20 seconds**. Actual Excel retrieval through a live OpenAI File Search store remains a manual acceptance step; the milestone is not yet claimed as retrieval-accepted.

The resumed working tree was preserved. Recovered branch: `Improved-Q&A-Functionalities-(in-development)`. HEAD: `3640f762a82e77b933221e7728b3dc084f079989` (`Improve evidence release and source UI`). The existing implementation was present as 45 tracked files with content changes and 11 new files before this report. No implementation changes were made after the successful final test run. This report is the twelfth new file.

No reset, revert, stash, commit, push, or staging was performed. The existing OpenAI configuration was retained, including the configured `gpt-5.6-terra` model. Credentials were not printed or replaced. No live ingestion or production VDR/vector-store mutation was performed.

## B. Files changed

Paths are relative to the repository. There are **45 modified files with content changes, 12 new files including this report, and no deleted files**. Disabled scripts remain present and return explicit rejection messages.

### Modified application and configuration files

| File | Purpose |
|---|---|
| `.gitignore` | Ignore assistant-managed Excel output/attempts; remove blanket workbook-extension ignores. |
| `requirements.txt` | Pin `openpyxl==3.1.5`. |
| `scripts/adopt_existing_vector_store.py` | Disable populated-store adoption for Manifest v2 snapshots. |
| `scripts/create_case_manifest.py` | Create v2 manifests through shared services. |
| `scripts/reconcile_existing_vector_store_files.py` | Disable filename/size reconciliation and mutable snapshot append. |
| `scripts/refresh_case_manifest.py` | Disable refresh of fixed snapshots. |
| `scripts/test_folder_scanner.py` | Include preprocessable workbook counts in scanner output. |
| `scripts/upload_new_manifest_files.py` | Use the shared v2 upload plan and structured retry keys. |
| `src/chains/qa_chain.py` | Pass resolved SourceReference objects through the existing answer flow. |
| `src/config/case_registry.py` | Seal before registration, verify persistence, protect registry paths, and require sealed cases on opening. |
| `src/ingestion/active_manifest.py` | Reject preparing snapshots as active published cases. |
| `src/ingestion/case_readiness.py` | Assess direct and worksheet targets plus preprocessing/exclusion states. |
| `src/ingestion/case_vector_store.py` | Freeze content at association; enforce empty/unowned association and reject permissive adoption. |
| `src/ingestion/file_filter.py` | Classify `.xlsx` as preprocess and retain `.xls` as unsupported. |
| `src/ingestion/manifest.py` | Define v2 source, preprocessing, coverage, artifact, and snapshot models with structural validation and derived counts. |
| `src/ingestion/manifest_builder.py` | Build v2 inventories without stored absolute paths or counters. |
| `src/ingestion/manifest_persistence.py` | Reject old versions; guard paths, ownership, freeze/seal boundaries, and state transitions; retain atomic persistence. |
| `src/ingestion/new_case_setup.py` | Allow Excel-only inventories and reject colliding local snapshot locations. |
| `src/ingestion/upload_workflow.py` | Route checkpoints, retry authorization, progress, and recovery to exact direct/worksheet owners. |
| `src/ingestion/uploader.py` | Reject raw workbook uploads, disable ingestion SDK retries, prove local-open failures, and bound initial indexing polling. |
| `src/ingestion/vector_store_manager.py` | Disable automatic SDK retries for vector-store creation. |
| `src/retrieval/citation_resolver.py` | Resolve exact file IDs to original workbook/worksheet provenance; use Unknown source for unresolved or ambiguous IDs. |
| `src/schemas/evidence.py` | Add optional Excel provenance to SourceReference without changing verified-excerpt schemas. |
| `src/ui/chat.py` | Render Excel-derived excerpts and external provenance captions while retaining existing evidence behavior. |
| `src/ui/new_case_setup.py` | Add workbook preparation, coverage review, retry/exclusion, target-aware upload results, and sealed registration resume. |

### New implementation files

| File | Purpose |
|---|---|
| `src/ingestion/excel_parser.py` | Extract captured workbooks deterministically with openpyxl, visibility policies, formula/cache views, bounded sections, and resource guards. |
| `src/ingestion/excel_preprocessing.py` | Capture/hash source bytes, build and publish immutable generations, and checkpoint preparation/retry/exclusion. |
| `src/ingestion/local_io.py` | Retry transient Windows permission failures on local atomic operations only. |
| `src/ingestion/paths.py` | Share safe relative-path, root-disjointness, and resolved containment checks. |
| `src/ingestion/upload_targets.py` | Define immutable UploadTargetKey, owner-aware targets, deterministic enumeration, and proxy preflight. |

### Modified regression tests

| File | Purpose |
|---|---|
| `tests/test_active_manifest.py` | Use v2 sealed active-case fixtures. |
| `tests/test_adopt_existing_vector_store_script.py` | Assert the deprecated adoption command rejects mutation. |
| `tests/test_case_readiness.py` | Align readiness fixtures with v2 and unsupported legacy workbook handling. |
| `tests/test_case_registry.py` | Use sealed published-manifest fixtures. |
| `tests/test_case_registry_registration.py` | Validate registration with v2 persistence and sealing. |
| `tests/test_case_selection.py` | Align selectable cases with sealed snapshots. |
| `tests/test_case_vector_store.py` | Exercise v2 ownership, preparation, and guarded association behavior. |
| `tests/test_citation_resolver.py` | Check resolved source objects and fail-closed unknown-source labels. |
| `tests/test_manifest.py` | Assert v2 schema/classification and removal of persisted absolute paths/counters. |
| `tests/test_manifest_persistence.py` | Exercise strict v2 persistence and root ownership using explicit corrupt-fixture setup. |
| `tests/test_new_case_setup.py` | Align setup eligibility and location checks with v2. |
| `tests/test_new_case_setup_ui.py` | Retain setup UI regression coverage and add an Excel-only preparation/exclusion/registration AppTest. |
| `tests/test_qa_chain_citations.py` | Update the fixture to the v2 citation contract. |
| `tests/test_qa_chain_presentations.py` | Align unresolved-source expectations without weakening presentation verification. |
| `tests/test_qa_chain_quotes.py` | Align source-resolution fixtures while retaining quote checks. |
| `tests/test_reconcile_existing_vector_store_files.py` | Replace obsolete mutable-reconciliation expectations with explicit command rejection. |
| `tests/test_refresh_case_manifest.py` | Replace obsolete refresh expectations with explicit command rejection. |
| `tests/test_upload_new_manifest_files.py` | Test CLI behavior through shared v2 target/preflight services. |
| `tests/test_upload_workflow.py` | Use structured retry keys and require ID persistence before cosmetic progress callbacks. |
| `tests/test_uploader.py` | Test the one-attachment-create polling adapter. |

### New tests and report

| File | Purpose |
|---|---|
| `tests/test_excel_manifest_v2.py` | Test v2 round trips, version rejection, paths, duplicate identities, and exclusion requirements. |
| `tests/test_excel_preprocessing.py` | Test capture determinism, visibility/values, resource limits, source immutability, and commit recovery. |
| `tests/test_excel_parser_recovery.py` | Test caches/errors, wide/long/sparse sheets, parser access, publication failures, interrupted retries, and allocation guards. |
| `tests/test_excel_upload_targets.py` | Test direct/worksheet checkpoint parity, callbacks, real SDK fake-transport retry behavior, sibling isolation, timeouts, and raw-workbook rejection. |
| `tests/test_excel_snapshot_provenance.py` | Test readiness/sealing/registry recovery, original-source provenance, evidence rendering, and independent replay. |
| `tests/test_excel_structural_validation.py` | Test invalid manifest structures, counts, round trips, and real temporary Windows junction containment. |
| `exports/Excel_Searchable_Knowledge_Implementation_Report_2026-09-09.md` | Record implementation, verification, limitations, and manual acceptance instructions. |

### Additional working-tree status entries

Git status also reports the following 13 paths as modified, but `git diff --name-only` reports no content changes for them. Their contents were compared with HEAD and match after CRLF/LF normalization. They were left untouched on resume; no index refresh or revert was used:

`tests/test_citation_extractor.py`, `tests/test_create_case_manifest_script.py`, `tests/test_evidence_presentation_schema.py`, `tests/test_evidence_selection_verifier.py`, `tests/test_evidence_selector.py`, `tests/test_evidence_text.py`, `tests/test_evidence_verifier.py`, `tests/test_openai_file_search.py`, `tests/test_parallel_series_verifier.py`, `tests/test_quotation_schema.py`, `tests/test_quote_verifier.py`, `tests/test_search_result_extractor.py`, `tests/test_vector_store_manager.py`.

## C. Architecture delivered

1. **Manifest v2:** loading requires version 2; v1, absent, and unknown versions receive a recreate-case error. Source paths are relative, counters are derived, and workbook parents retain neutral remote state. Structural validation distinguishes invalid identities/relationships from recoverable incomplete remote states.
2. **Capture and preprocessing:** raw source bytes are copied to a unique assistant-managed attempt. The completed copy is closed, hashed, and parsed. Formula/structure and cached-value views use the same captured file. No source workbook is saved or recalculated.
3. **Worksheet proxies:** each visible meaningful worksheet produces one deterministic Markdown artifact in original tab order. Coverage records hidden, very hidden, blank, and chart-only exclusions. Hidden rows/columns are omitted. Coordinates, stored values, formula metadata, cache-unavailable markers, errors, and merge anchors remain explicit. Wide sheets use bounded column windows; long sheets use sections; sparse dimensions are not expanded into a full rectangle.
4. **Immutable generations:** source-relative identity, captured SHA, and transformation version determine generation identity; worksheet index determines child identity within that generation. Outputs are validated before publication. Attempts and unreferenced outputs are ineligible. Existing generation reuse requires complete equivalence checks after explicit preprocessing; no automatic orphan adoption is provided.
5. **UploadTarget:** a structured `(source_relative_path, artifact_id)` key identifies each target. Direct files own their existing state; worksheet artifacts own independent state. Display labels are separate from identity. Derived preflight verifies the completed generation path, regular file, size, and hash without rehashing the original workbook.
6. **Freeze and seal:** vector-store association freezes source/generation content. Readiness requires all searchable targets complete, no blocking preprocessing/classification errors, and at least one searchable target. Sealing is persisted and verified before registry publication. Registry failure leaves a sealed, unregistered snapshot that can be registered again. Opening a published case requires a structurally valid sealed manifest without opening source workbooks or proxies.
7. **Provenance and replay:** exact file-ID resolution creates SourceReference objects with optional original workbook path and worksheet name. Unknown/ambiguous IDs never inherit trusted proxy filenames. Worksheets remain separate sources and passage spaces. Stored answer JSON includes provenance and renders without current manifests, workbooks, proxies, resolvers, File Search, or a new OpenAI client.
8. **Recovery protections:** the existing conservative upload-state sequence is retained for each owner. Known IDs and uncertain uploads cannot cause blind file creation. Callback errors cannot prevent returned-ID persistence. Failure diagnostics identify the manifest, vector store, source, artifact, worksheet, known file ID, failed checkpoint, and last persisted owner state.

## D. Important deviations and limitations

No protected-architecture deviation or scope expansion was required. The following implementation details and limits are explicit:

- Before the two extraction views, a preliminary read-only openpyxl streaming pass guards cell/range materialization, including compact files with enormous merged ranges. It uses pinned openpyxl 3.1.5 internal interfaces (`WorkSheetParser`, read-only worksheet internals, and `_cells`). An engine upgrade requires revalidation. Production code contains no custom OOXML extraction helper or second spreadsheet engine. Test-only ZIP/XML fixture manipulation supplies stored formula caches.
- A small `generation.json` sidecar supports full collision/equivalence checks when a deterministic generation directory already exists. It is not an upload target.
- Transient Windows sharing/permission failures observed during atomic backup replacement are handled by five local attempts with 0.05/0.1/0.2/0.4-second delays. These retries apply only to local atomic operations and never repeat a remote mutation.
- Default preprocessing guards are 50 MiB captured input, 256 MiB expanded ZIP size, 1,000,000 traversal-budget units, 1,000 worksheets, 16 MiB per proxy, 64 MiB total output, and 120 seconds. Section target size is 8,000 bytes and column-window width is 12. The traversal budget counts multiple passes and expansion work, so it is not a promise to accept one million populated cells. Timing is cooperative; there is no separately isolated worker or hard operating-system memory limit.
- Initial indexing polling defaults to a 120-second deadline with individual SDK timeouts capped by the remaining wait and 30 seconds. HTTP connection/read/write phases retain SDK timeout semantics; this is not a hard process-wide wall-clock guarantee. Timeout preserves known-ID/in-progress state and does not introduce general indexing recovery.
- A genuinely encrypted/password-protected workbook fixture was not constructed. Corrupt/non-ZIP inputs and workbook-open failures are covered; representative encrypted input remains a manual failure-path check where practical. Decryption is unsupported.
- Full Excel display fidelity and real File Search retrieval quality were not established by synthetic offline tests. Formula caches may be stale because the application never recalculates them.

## E. Test results

Commands below run from the repository root in PowerShell. Tests use temporary case trees outside the repository/OneDrive because setup intentionally rejects raw VDRs inside the application tree. Remote operations use fake clients or OpenAI SDK `httpx.MockTransport`; no real ingestion requests are sent.

### Final full suite — authoritative result for final code

```powershell
& .\.venv\Scripts\python.exe -m pytest tests -q --tb=short --basetemp="$env:TEMP/vdr-excel-release-full"
```

**Result: 881 passed in 40.20s; exit code 0.** The run was resumed from its existing process after the usage interruption. It was not restarted or substituted with a smaller suite.

### New Excel-focused tests

The final full run includes **128 passing Excel-focused tests**: the six new Excel test modules plus the Excel-only Streamlit AppTest in `test_new_case_setup_ui.py`.

The preceding dedicated focused run used:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_excel_manifest_v2.py tests/test_excel_preprocessing.py tests/test_excel_parser_recovery.py tests/test_excel_upload_targets.py tests/test_excel_snapshot_provenance.py tests/test_excel_structural_validation.py tests/test_new_case_setup_ui.py::test_excel_only_streamlit_preparation_exclusion_and_registration -q --tb=short --basetemp="$env:TEMP/vdr-excel-release-focused"
```

**Result: 126 passed in 54.61s.** This focused execution preceded the final `.xlsx`/`.xls` direct-uploader rejection guard and its two parameterized tests. Those two tests, together with the prior 126, passed in the final 881-test run. The 128 count is not presented as a second independent focused execution.

Final collection accounting was checked without rerunning tests:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_excel_manifest_v2.py tests/test_excel_preprocessing.py tests/test_excel_parser_recovery.py tests/test_excel_upload_targets.py tests/test_excel_snapshot_provenance.py tests/test_excel_structural_validation.py tests/test_new_case_setup_ui.py::test_excel_only_streamlit_preparation_exclusion_and_registration --collect-only -q 2>&1 | Select-String 'collected|PermissionError'
```

**Result: 128 tests collected in 1.38s.** An initial sandboxed collection completed with exit code 0 but emitted a temporary-directory cleanup PermissionError at interpreter exit; repeating collection with permitted temporary-directory access produced the clean result above. This was a collection-environment issue, not a failed test in the full suite.

### Existing regression tests

The other **753 tests passed in the same final full-suite execution** (`881 − 128`). This includes the existing direct-document, Q&A, evidence, schema, case setup, registry, and ingestion regressions after required v2 interface/fixture updates. This count is a partition of the full run, not a separately timed regression command.

Obsolete v1/refresh/reconcile/adoption expectations were replaced only where the contract explicitly changes those behaviors. Protected evidence/verification assertions were retained. Earlier failures exposed obsolete schema/interface assumptions, inappropriate in-repository test VDR locations, transient Windows local locks, and setup-state/checkpoint defects; these were addressed before the final successful run. No tests were silently skipped to obtain that result.

### Additional verification

```powershell
& .\.venv\Scripts\python.exe -m compileall -q src scripts
& 'C:\Users\luet087\AppData\Local\GitHubDesktop\app-3.6.4\resources\app\git\cmd\git.exe' diff --check
```

Both returned **exit code 0**. Git emitted an informational LF-to-CRLF warning for `manifest.py`, with no whitespace errors. A separate local comparison found all 13 protected files listed below unchanged against HEAD after line-ending normalization. `git diff --cached --name-only` returned no staged paths.

## F. Protected architecture verification

| Protected component | Verification/result |
|---|---|
| `search_vector_store()` and OpenAI File Search | Unchanged in `src/retrieval/openai_file_search.py`; no new retrieval path. |
| Primary answer prompt | `src/prompts/qa.md` unchanged. |
| Responses API request and answer-first generation | Existing request construction unchanged; `qa_chain.py` only carries resolved source objects and derives their display names. |
| GPT-5.6 Terra | Existing configured model retained; settings module unchanged. |
| Citation and search-result extraction | Both extractor modules unchanged; provenance resolution is downstream. |
| Combined support selector and quote selector | `src/retrieval/quote_selector.py` unchanged. |
| Quote verifier and `_source_derived_match()` | `src/validation/quote_verifier.py` unchanged. |
| Evidence-selection verifier | `src/validation/evidence_selection_verifier.py` unchanged. |
| Evidence selector and evidence verifier | `src/presentation/evidence_selector.py` and `src/presentation/evidence_verifier.py` unchanged. |
| Best-passage release gate | Existing verification/release logic retained; worksheet provenance does not bypass it. |
| Structured verification | Presentation/evidence/parallel-series verification and schemas unchanged. |
| Three-model-call ceiling | No additional ordinary Q&A model invocation introduced; existing regression coverage passes. |
| Source/passage/quote limits | Existing six-source selector limit, passage limits, and quote limits retained. |
| One vector store per published snapshot | Association freezes the candidate; seal/registration guards preserve one fixed association. |

The 13 files checked directly against HEAD were: `src/retrieval/openai_file_search.py`, `src/prompts/qa.md`, `src/retrieval/quote_selector.py`, `src/validation/quote_verifier.py`, `src/validation/evidence_selection_verifier.py`, `src/presentation/evidence_selector.py`, `src/presentation/evidence_verifier.py`, `src/presentation/parallel_series_verifier.py`, `src/schemas/quotation.py`, `src/schemas/evidence_presentation.py`, `src/retrieval/citation_extractor.py`, `src/retrieval/search_result_extractor.py`, and `src/config/settings.py`.

`VerifiedQuote`, `VerifiedEvidenceExcerpt`, and Structured schemas remain unchanged. Verified quotes are partitioned by exact source ID for rendering as ordinary quotations or Excel-derived excerpts; no additional quotes are selected. Raw retrieved text is retained exactly, with Excel provenance rendered outside it. Only primary-answer citation members appear as sources.

## G. Safety/recovery verification

| Invariant | Offline evidence |
|---|---|
| Raw VDR write protection | Temporary source-tree comparisons across success/failure/retry/exclusion/cleanup; parser spy confirms captured-copy access and no workbook save; disjoint-root/traversal/drive-relative and actual temporary Windows junction checks. |
| No raw workbook upload | `.xlsx` is a preprocess classification; parent state must remain neutral; direct uploader rejects `.xlsx` and `.xls` before remote file creation. |
| Atomic preparation | Fault injection at processing checkpoint, capture/hash/open/parse/serialization/write/validation/publication/completed-save/post-save/cleanup boundaries; partial and unreferenced outputs remain ineligible. |
| Immutable generations | Existing generation is not overwritten; reuse requires exact equivalence; association prevents replacement; interrupted processing can be explicitly retried before association. |
| SDK mutation retry behavior | Real installed SDK with fake HTTP transport verifies one HTTP attempt on errors/timeouts for file creation, attachment, and vector-store creation. Ingestion clients use `max_retries=0`; Q&A client policy is unchanged. |
| Returned-ID persistence boundary | File ID is saved and reloaded/verified before attachment and before the file-uploaded progress callback; injected persistence and callback failures retain conservative recovery behavior. |
| No blind reupload | Direct and worksheet tests cover uncertain failures, unusable/missing IDs, known-ID incomplete states, checkpoint failures, attachment interruption, timeout, and restart/refusal. Only proved pre-remote failures are eligible for explicit safe retry. |
| Sibling isolation | Completed Revenue/Customer children remain byte/state-identical when the Headcount child is safely retried; uncertain and known-ID-incomplete Headcount variants issue no file creation. Parent-path authorization cannot authorize a child retry. |
| Local lock recovery | Parameterized direct/worksheet tests inject a transient backup replacement lock after remote file creation and verify completion with the original ID and no second upload. |
| Seal enforcement | Preparing/sealed state guards, association freeze, readiness, registry failure after seal, registration retry, and sealed case opening are tested. |
| Replay independence | Excel/mixed serialized answers render while manifest lookup, source resolution, workbook/proxy access, File Search, and OpenAI client creation are forbidden by test instrumentation. |

No real OpenAI ingestion, resource adoption, remote deletion, raw production-source mutation, or production registry publication was performed. Test fixtures and fake identifiers were used. No general recovery service, remote cleanup, or distributed locking was added.

## H. Deferred items

- Manifest v1 migration and `.xls` support.
- A custom OOXML helper; a second spreadsheet engine; formula recalculation; workbook execution; macros/VBA; Excel write-back; workbook repair; password removal/decryption.
- Chart interpretation, Power Query refresh, external-link/workbook resolution, pivot refresh, semantic table/financial-model interpretation, and a full Excel formatting/rendering engine.
- General indexing recovery, unknown remote-ID recovery, remote orphan matching, automatic remote cleanup, and remote garbage collection.
- Incremental snapshot synchronization, refresh of published snapshots, and replacement of artifacts inside published vector stores. Changed source information requires a new snapshot at a distinct case-root location.
- Distributed/multi-operator ingestion locking, completed-generation garbage collection, and automatic orphan-generation adoption.
- Durable chat archives, an independent history viewer, SharePoint integration, shared hosted/team deployment, and a central state store.
- Evidence whitespace redesign and claim-level grounding redesign.
- Real File Search retrieval-quality acceptance, capacity-miss characterization, and a representative encrypted-workbook failure check.

## I. Manual Streamlit acceptance checklist

Use fresh local test cases and test vector stores. These instructions describe the remaining user-run acceptance work; no live steps below were executed by Codex.

### Prepare representative files

Create distinct case roots outside the repository, for example `%TEMP%\ExcelAcceptance\ExcelOnly\VDR` and `%TEMP%\ExcelAcceptance\Mixed\VDR`. Each gets its own sibling `VDR Assistant` state directory. Do not reuse production folders or previously published snapshot stores.

- In the Excel-only case, place `Finance\model.xlsx` and `People\model.xlsx` with intentionally different facts. Include multiple visible worksheets, such as Revenue Build, Customer KPIs, and Headcount, so duplicate filenames and separate worksheet identities are exercised.
- Include blank, hidden, and very hidden tabs; hidden rows and columns; zero, False/True, plain text, dates, percentages, internal blanks/empty strings where representable, duplicate headers, and merged headings.
- Save representative formula workbooks in Excel so they contain cached results. Record expected stored results, including any cached error. Include a formula without a stored result and an external-reference formula where practical; neither should be recalculated or resolved by the application.
- Include a wide sheet (for example 100 columns), a long sheet (for example 1,500 rows), and a sparse sheet with isolated cells far apart. Put recognizable facts around adjacent row-section/column-window boundaries and record their coordinates.
- Include a disposable corrupt `.xlsx` for failure/retry/exclusion checks and, where practical, an encrypted workbook to verify a clear failure without repair/decryption. Keep a legacy `.xls` to confirm unsupported classification.
- In the mixed case, include representative Excel files plus a PDF with distinct, known facts. Record file hashes and modification times before preparation; compare them afterwards if independently checking source immutability.

### Run and prepare each case

```powershell
& .\.venv\Scripts\streamlit.exe run app/main.py
```

1. Start new-case preparation, select the test VDR directory, supply a unique case ID, and review the scan. Confirm an Excel-only case is eligible, `.xlsx` is preprocessable, and `.xls` remains unsupported.
2. Create the v2 manifest. In **Prepare Excel knowledge**, choose **Prepare workbook** for each pending workbook. Review original tab ordering, included sheets, exclusions, and reasons. Confirm raw source files remain unchanged and generated data is under the sibling assistant directory.
3. For the corrupt workbook, inspect the failure and use **Retry preprocessing** while still before association. Supply a nonblank reason and choose **Exclude workbook** to proceed without it. Confirm a failed/unresolved workbook blocks progress and a valid exclusion permits it. Do not edit a sealed snapshot to repair it.
4. Choose **Continue to vector-store association** only after coverage is satisfactory. Following the existing UI instructions, manually create a fresh empty test vector store and associate its exact ID. Verify a populated or already owned store is rejected. Content preparation/exclusion must no longer be mutable after association.
5. Choose **Continue case preparation**, inspect the upload preview, then **Upload and index all eligible files**. Expect separate worksheet targets and Markdown proxy uploads; expect no raw workbook upload. Completed worksheet siblings must remain completed when another target fails. Use only an explicitly offered safe retry; preserve displayed IDs and recovery details for uncertain/known-ID failures.
6. When readiness succeeds, choose **Continue to registration**, then **Register prepared case**. Confirm the snapshot becomes sealed and appears in case selection. Reopening it should use the published manifest and existing vector store. A source update belongs in a new case-root snapshot.
7. Repeat for the mixed Excel/PDF case. Automated tests already cover seal-before-registry failure and retry; do not deliberately corrupt a live test registry to reproduce those faults.

### Ask and inspect representative questions

1. Ask a factual question whose stored answer occurs in one worksheet, then another worksheet of the same workbook. Confirm distinct `VDR → folder → workbook.xlsx → worksheet` labels and separate evidence groups.
2. Ask questions distinguishing `Finance\model.xlsx` from `People\model.xlsx`. Attribution must follow the exact cited file ID, without collapsing duplicate workbook filenames.
3. Ask about saved formula results, zero/False values, dates, and percentages. Compare against the expected stored value. Missing caches must not become fabricated calculated results; hidden content must not be represented as included worksheet data.
4. Ask about facts near the ends of wide/long sheets, isolated sparse cells, and section/window boundaries. Record retrieval misses and capacity limitations separately. Do not raise selector/passages/model-call limits to make these questions pass.
5. In the mixed case, ask one PDF-only question, one Excel-only question, and one question supported by both. Inspect Sources, **Best supporting passage**, **Additional retrieved context**, any existing Structured presentation, **Verified quotations**, and **Excel-derived excerpts**. The new terminology must not imply that verification or selection rules changed.
6. Expand raw retrieval. Confirm workbook/worksheet captions are outside the raw passage, and the passage is the exact stored retrieval text. Check for `sheet_001.md` or other proxy-name leakage in trusted user-facing source labels. Do not treat raw provider text itself as a trusted provenance lookup.
7. Review an earlier answer after further interactions. Its stored provenance and evidence should remain stable. Self-contained serialized replay is covered offline; durable cross-session history is not part of this milestone.

For **every manual question**, record:

| Field | Record |
|---|---|
| Question | Exact submitted wording. |
| Expected workbook | Original relative path, including its folder. |
| Expected worksheet | Exact worksheet name. |
| Expected factual result | Stored fact/value and useful cell coordinates. |
| Answer usefulness | Correct/useful, partial, or incorrect, with a short reason. |
| Source attribution | Correct workbook/worksheet and citation membership. |
| Best passage quality | Whether the released passage actually supports the answer. |
| Additional context quality | Relevance and usefulness of additional retrieved passages. |
| Raw passage readability | Readability of the unchanged retrieved representation. |
| Proxy-name leakage | Where any proxy filename appears in trusted source labels. |
| Retrieval miss | Missing fact, section/window boundary, or apparent capacity issue. |
| Model-call count | Observed count from available diagnostics/logs; mark unknown if unavailable. Ordinary Q&A must remain within three calls. |

## J. Recommended next action

**Ready for manual local acceptance testing.** Review this uncommitted diff and run the checklist with representative disposable cases and fresh test vector stores using the existing key configuration. Record actual retrieval outcomes before accepting the milestone. No further code correction is indicated by the final offline suite; retrieval-quality findings should be assessed against this contract without broadening the protected Q&A architecture.
