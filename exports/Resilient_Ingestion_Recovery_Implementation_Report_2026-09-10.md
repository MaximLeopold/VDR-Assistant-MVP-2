# Resilient Ingestion & Recovery — Implementation Report

Date: 2026-09-10

Repository: VDR-Assistant-MVP-2

Implementation basis: the supplied “VDR Assistant MVP 2 — Codex Implementation Handoff: Resilient Ingestion & Recovery.” This implementation follows its accepted no-ID/orphan trade-off and supersedes the earlier durable retry-proof design for this milestone.

## A. Summary

Implemented manifest-driven, sequential ingestion that continues after durably recorded target-local failures. Later operator-started passes can retry eligible targets without persisted OpenAI File IDs. Targets with persisted IDs are recovered through exact remote reads and never return to File creation.

Streamlit and the CLI now share the same orchestration and recovery behavior. Streamlit exposes **Continue ingestion**, **Refresh / recover known files**, and **Attach existing file** after confirmed attachment absence. Results distinguish **Finished**, **Paused**, and **Stopped**, independently of publication readiness.

The old session-bound safe-retry authorization was removed. There is no replacement retry-proof subsystem, Manifest schema extension, migration, job queue, or ingestion lock.

**Final validation: 981 offline tests passed in 57.11 seconds. No live OpenAI acceptance testing was performed.**

## B. Architecture confirmation

Each normal operator-started pass:

1. Reloads the persisted Manifest v2 and validates ownership, mutable snapshot state, association, frozen candidate identity, and exact UploadTargets.
2. Reconciles known-ID incomplete targets before any new File creation.
3. Processes each eligible no-ID target once, with a fresh local preflight.
4. Reloads the manifest and assesses the unchanged strict readiness rules. There is no automatic post-pass remote sweep.

The new-upload sequence remains:

```text
final target preflight
→ increment upload_attempts; persist uploading / not_started
→ files.create()
→ receive a usable File ID
→ persist that ID with uploaded / not_started
→ reload and verify the complete checkpoint
→ persist and verify in_progress attachment intent
→ attach the exact persisted ID once
→ short initial status polling
→ persist completed, in_progress, or failed
→ continue unrelated targets when safe
```

Checkpoints verify persisted content against the intended manifest and candidate identity. State is checked again before remote mutations. A failed save, a silently ineffective save, a failed readback, or a stale candidate stops further work. These checks do not constitute an atomic multi-writer lock.

Initial polling starts with an immediate GET, then uses increasing intervals within an approximately ten-second scheduling window. An executing SDK request and its retries can outlast that window. Window expiry preserves healthy `in_progress`; it is not an indexing failure or a hard wall-clock deadline.

## C. Effective retry configuration

Validated against the locally installed OpenAI Python SDK **2.44.0**, Python **3.14.3**, and httpx **0.28.1**.

| Operation | SDK max_retries | Maximum HTTP attempts per logical request | Application behavior |
| --- | ---: | ---: | --- |
| `files.create()` | 2 | 3 | One logical invocation per eligible target per operator-started pass |
| Vector-store retrieve | 2 | 3 | Read-only validation |
| Vector-store attachment retrieve/status | 2 | 3 | Exact File ID and vector-store ID |
| Vector-store file listing, including pagination | 2 | 3 per page request | Existing association checks retain listing support |
| Underlying File retrieve | 2 | 3 | Exact persisted ID; no filename matching |
| Initial polling GETs | 2 | 3 per scheduled GET | No repeated attachment POST |
| `vector_stores.files.create()` | 0 | 1 | Initial attachment or explicitly permitted same-ID recovery |
| `vector_stores.create()` | 0 | 1 | Existing provisioning behavior retained |

The policy helpers clone actual SDK clients; they do not modify the shared Q&A client. Ingestion reads use a five-second request timeout, narrowed to the remaining scheduling window during initial polling. File creation inherits the base client's timeout. The attachment request is also bounded by the configured initial-wait timeout.

There is no application retry loop around an exhausted SDK request. Repeated status observations and the two absence checks are deliberate read operations, not retries of failed SDK calls. No combined upload-and-attach convenience helper bypasses the ID checkpoint.

## D. Continue, pause, and stop behavior

| Result | Conditions |
| --- | --- |
| Continue after verified persistence | Missing/unreadable local target, reviewed-size mismatch, worksheet proxy hash/size mismatch, local open failure, isolated exhausted upload/attachment/status request, missing/blank returned File ID, pending indexing, remote failed/cancelled status, or a missing underlying known File |
| Pause immediately | Authentication, service permission, rate/quota/billing access failures, inaccessible vector store, or unavailable client access |
| Pause at threshold | Three consecutive infrastructure-related target failures, including exhausted connection/timeout/5xx/protocol failures |
| Stop immediately | Manifest persistence/readback failure, stale or invalid candidate/target identity, structural inconsistency, sealed/frozen snapshot violation, unsafe containment/root collision, mismatched remote resource identity, or unexpected application failure |

Local preflight/source failures neither increment nor reset the infrastructure streak. Successfully established `completed` or `in_progress` remote state resets it. The streak exists only for the current pass and never affects later upload eligibility.

Planning now separates candidate-wide blockers from target-local issues. A missing file or corrupt proxy is visible in its row and is durably recorded during execution; it does not globally block unrelated targets.

## E. No-ID retry behavior

For recognized, consistent target states, absent `openai_file_id` plus `indexing_status = not_started` permits upload when `upload_status` is `not_uploaded`, `uploading`, or `failed`. Final preflight and candidate validation still apply. Incompatible state tuples remain blocked.

Each pass uses a fixed work list and invokes File creation at most once logically per target. SDK retries happen inside that invocation. The existing `upload_attempts` counts logical invocations and is never reset; a local preflight failure before invocation does not increment it.

An unresolved target without an ID can be tried in a later operator-started pass after process or Streamlit session loss. No saved session proof, exception-history token, or newly persisted retry field is required.

Accepted risk: a request whose response was lost may have created an unused File. With two SDK retries, one logical invocation can make up to three upload requests. If the last request returns the only known ID, up to two earlier File objects could be orphaned; if all responses are lost, up to three could be unknown. Repeated operator passes add further possible orphans.

The application does not discover or attach those unknown IDs. Under the checkpoint and one-writer assumptions, upload retries therefore do not introduce additional searchable File identities through those orphan objects. This is not a promise of exactly-once server execution, nor protection against external mutation or multiple writers.

## F. Known-ID reconciliation

| Exact remote observation | Result |
| --- | --- |
| Attachment completed | Persist `uploaded / completed`, retain ID, clear obsolete error |
| Attachment in progress | Persist `uploaded / in_progress`; a normal recovery pass makes one status observation when the attachment is present |
| Attachment failed/cancelled | Persist `uploaded / failed`, retain ID and failure diagnostics |
| Attachment absent; local indexing `not_started` | Verify store and underlying File, recheck exact absence, persist attachment intent, attach the same ID once, poll briefly |
| Attachment absent after prior ambiguous/in-progress or failed state | Verify store/File and repeat the absence read; expose explicit recovery without automatically attaching |
| Explicit **Attach existing file** | Reload candidate/target, repeat fresh exact reads and resource checks, verify absence and checkpoint intent, then make at most one same-ID attachment POST |
| Attachment appears during repeated checks | Reconcile the observed status; do not send an attachment POST |
| Underlying File missing | Preserve its ID, record failure, continue unrelated work; never create a replacement File |
| Wrong File/store identity | Stop further mutation |

Recovery resolves logical UploadTarget identity without requiring the original source or indexed proxy to remain locally readable. New uploads still require final containment, metadata, and applicable proxy-hash checks.

The explicit refresh action processes only known-ID targets. It never attempts no-ID uploads. A fresh Streamlit session can rediscover an absent attachment and offer recovery again; prior UI state is not authority. Explicit same-ID reattachment remains the accepted recovery mutation rather than a claim of exactly-once attachment execution.

CLI usage remains `python scripts/upload_new_manifest_files.py`. After selecting the folder, choose `UPLOAD` for a normal pass, `RECOVER` for known files only, or `ATTACH <known target number>` for an explicitly requested same-ID recovery. All mutation conditions are rechecked by the shared workflow.

## G. Safety invariants

- **Known-ID no-reupload:** a valid known ID routes only to completion/recovery; incompatible known-ID tuples stop. The persisted ID is not cleared or replaced.
- **Checkpoint before attachment:** the returned ID is saved and reloaded/verified before attachment intent and POST.
- **Raw VDR read-only:** production ingestion only reads source files. Raw `.xlsx` and `.xls` remain prohibited upload inputs.
- **Excel sibling isolation:** worksheet recovery mutates only that artifact's existing remote-state fields. Completed siblings, workbook provenance, proxy content/hashes, artifact IDs, and generation IDs remain unchanged.
- **Strict publication:** 85/86 completed remains preparing and not ready. Exact known-ID recovery can reach 86/86; existing registration/sealing gates still govern publication.
- **Manifest compatibility:** no change to Manifest v2, its persisted fields, `generation.json`, or migration requirements.
- **Protected Q&A:** no production changes to `app/main.py`, QA chains, prompts, File Search retrieval, evidence/quotation verification, citation resolution, or the three-call architecture. Existing regressions passed.

## H. Production files changed

| File | Change |
| --- | --- |
| `src/ingestion/openai_policy.py` — new | Explicit SDK policy helpers for File creation, reads, and mutations |
| `src/ingestion/known_file_recovery.py` — new | Exact attachment observations and store/underlying-File checks |
| `src/ingestion/remote_errors.py` — new | Small structured failure classifier and sanitized messages |
| `src/ingestion/upload_workflow.py` | Manifest-based eligibility, continuation, checkpoints, reconciliation orchestration, pass results; removed session retry authority |
| `src/ingestion/upload_targets.py` | Logical target resolution and distinction between target preflight failure and candidate integrity failure |
| `src/ingestion/uploader.py` | Selective retries, attachment identity checks, short opportunistic polling |
| `src/ingestion/vector_store_manager.py` | Apply explicit read and mutation policies |
| `src/ui/new_case_setup.py` | Ingestion/recovery actions, status counts, clear pending/paused/stopped results |
| `scripts/upload_new_manifest_files.py` | Same shared normal-pass, refresh, and explicit reattachment behavior in the CLI |

## I. Tests and validation

New test modules:

- `tests/test_ingestion_retry_policy.py`: real SDK with fake HTTP transport; operation-specific attempt counts; multipart body replay; base-client policy unchanged; only the returned, persisted ID is attached; exhausted middle upload does not prevent the third target.
- `tests/test_ingestion_recovery.py`: known-ID paths, resource/identity errors, no-create guards, fresh reattachment checks, missing local source during recovery, all checkpoint boundaries, middle-target continuation, infrastructure pause/reset, short-poll scheduling, healthy pending messaging, and 85/86 to 86/86 readiness.

Modified test modules:

- `tests/test_upload_workflow.py`: manifest-state eligibility matrix, checkpoint ordering, local issues, continuation, later-pass retry, and stale-state refusal.
- `tests/test_retry_authorization.py`: replaced obsolete proof assertions with no-ID retry, candidate binding, restart, UI-context clearing, and recovery-diagnostic checks. Its historical filename does not imply retained retry authorization.
- `tests/test_excel_upload_targets.py`: direct/worksheet boundaries, checkpoint faults, callback isolation, actual SDK mutation counts, middle-sibling failure/hash corruption and recovery, immutable siblings/content, and polling.
- `tests/test_uploader.py`: exact attachment IDs in the fake response.
- `tests/test_upload_new_manifest_files.py`: CLI lifecycle/checkpoints, local versus structural preflight failures, refresh, and explicit same-ID attachment.
- `tests/test_new_case_setup_ui.py`: existing preparation/registration flows plus recovery after session loss, explicit reattachment, and subsequent completion of untouched no-ID targets.
- `tests/test_excel_snapshot_provenance.py`: attachment fixture now returns exact File and store IDs; existing publication/provenance/replay assertions retained.

Focused checkpoints during implementation:

| Scope | Result |
| --- | --- |
| Initial SDK policy, uploader, vector-store and Excel upload tests | 85 passed |
| Eligibility/workflow, uploader and retry policy | 75 passed |
| Expanded workflow/recovery/restart/policy group | 121 passed |
| UI and CLI regression group | 23 passed |
| SDK/recovery/UI/CLI integration group | 68 passed |
| Final focused Excel provenance/upload and recovery/retry group | 118 passed |
| **Final complete `tests` suite** | **981 passed in 57.11 seconds** |

These focused counts are overlapping checkpoints, not additional tests to add to the final total. Intermediate full-suite failures exposed incomplete fake attachment responses and loss of the specific sealed-snapshot error message. Both were corrected; the final suite passes without weakening the protected assertions.

The full suite ran through `.venv/Scripts/python.exe -B` with `pytest.main(['-q', '--tb=short', '--basetemp=<unique disposable path>, 'tests'])`. The launcher set a fake `OPENAI_API_KEY` and replaced socket connection methods with functions that raise immediately. Real SDK requests used `httpx.MockTransport`; no live File/store creation, attachment, deletion, or ingestion was performed.

Windows Python 3.14's private temporary-directory ACLs initially prevented sandbox fixture access. The test launcher used unique disposable directories, redirected its own temporary files there, and made `os.mkdir` inherit ACLs only inside that disposable tree. No production ACL/persistence behavior or repository test assertions were changed for this workaround.

`git diff --check` passed with exit code 0. Git emitted only its ordinary LF-to-CRLF conversion notices.

## J. Git state

- Branch: `Excel-Feasibility-MVP-(In-Development)`.
- Starting HEAD: `c8e7383b5bc5b5a6278c89f3d7f411c35c111508`.
- Finishing HEAD: unchanged.
- Tracked implementation/test diff: **13 files changed, 1,258 insertions, 1,413 deletions**.
- New untracked code/test files are additional to that Git diff statistic: three production modules and two test modules, totaling **844 lines**.
- Total implementation scope: **nine production files and nine test files**, plus this report.
- `exports/Resilient_Ingestion_Recovery_Design_Report_2026-09-10.md` was already untracked at the start and remains untouched.
- This implementation report is a new, untracked export.
- No staging, commit, push, branch switch, reset, rebase, merge, or cleanup was performed.

The protected production paths for Q&A, Manifest/schema/persistence, Excel parsing/preprocessing, and readiness/registration have no implementation diff.

## K. Remaining limitations

- Unknown/orphan OpenAI Files are an explicitly accepted consequence of retrying File creation. They may consume remote storage; discovery, deletion, and expiration management are not implemented.
- One writer per candidate is an operational rule. Checkpoint checks detect observed stale state but do not provide distributed mutual exclusion or protect against every concurrent write race.
- Two absence observations cannot prove permanent absence in a distributed service. Ambiguous same-ID reattachment remains an explicit operator action with fresh validation.
- Polling is opportunistic. Remote indexing may require later passes; an in-flight SDK call may exceed the ten-second scheduling window.
- Remote failures are classified conservatively. Unknown application exceptions stop instead of being treated as routine target failures.
- Missing underlying known Files and structural/candidate integrity failures still require investigation; the workflow never replaces a known ID by uploading again.
- Publication remains all-or-nothing. No partial-ready mode was added.
- Live acceptance remains a separate, explicitly authorized step after review: small PDF, fault-injected multi-file, restart recovery, Excel-only, mixed case, realistic VDR, and final live Q&A checks.
