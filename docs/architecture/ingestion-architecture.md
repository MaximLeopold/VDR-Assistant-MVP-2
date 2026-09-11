# Ingestion architecture

Ingestion is manifest-driven and sequential. Streamlit [preparation UI](../../src/ui/new_case_setup.py) and the [operator CLI](../../scripts/upload_new_manifest_files.py) use [shared orchestration](../../src/ingestion/upload_workflow.py). See [case/snapshot model](case-and-snapshot-model.md) for inventory/provenance and [resilient-ingestion decision](../decisions/resilient-ingestion.md) for trade-offs.

## Preparation and planning

A raw VDR directory is read-only and separate from both the application repository and the assistant-managed output directory. [Scanning](../../src/ingestion/folder_scanner.py) and [classification](../../src/ingestion/file_filter.py) create the reviewed inventory.

Direct formats are PDF, DOCX, PPTX, TXT, and Markdown. Non-empty `.xlsx` sources require preprocessing; raw workbooks never enter the direct uploader. Unsupported, ignored, excluded, and erroneous entries have different meanings and are not interchangeable.

[New-case services](../../src/ingestion/new_case_setup.py) manage candidate validation and preparation. Excel preparation and coverage review occur before store association freezes content. Association checks the selected empty store and ownership constraints through [case/store services](../../src/ingestion/case_vector_store.py).

[UploadTargets](../../src/ingestion/upload_targets.py) provide a common interface for a direct document or worksheet artifact. Plan/candidate identity includes the case context and exact target; a matching relative path alone is insufficient. Local preflight checks containment, target identity, readability and size, plus proxy hashes for worksheet artifacts. Direct documents do not have Excel's complete captured-source hash contract.

## Operator-started pass

1. Reload and validate Manifest v2, ownership, association, mutable snapshot state, and reviewed candidate identity.
2. Reconcile incomplete known-ID targets before new File creation.
3. Process each eligible no-ID target once per application pass, with fresh preflight.
4. Persist individual outcomes and reassess strict readiness.

Completed targets stay unchanged. There is no automatic post-pass remote sweep, queue, or parallel worker.

For a new target the durable sequence is:

```text
final target preflight
→ persist uploading / not_started and increment logical upload_attempts
→ files.create
→ receive usable File ID
→ persist uploaded / not_started with that ID
→ reload and verify checkpoint
→ persist and verify attachment intent (in_progress)
→ attach the exact persisted ID
→ short initial polling
→ persist observed outcome
```

A failed save/readback or changed candidate stops further work. Known IDs cannot be cleared or substituted. A known-ID UploadTarget never calls `files.create` again, even if its underlying remote File is missing.

## Retry and timeout policy

[Policy helpers](../../src/ingestion/openai_policy.py) clone ingestion clients without changing Q&A policy. [The uploader](../../src/ingestion/uploader.py) separates File creation from attachment.

| Operation | SDK retries | Application behavior |
| --- | ---: | --- |
| File creation | 2 | One logical invocation per eligible target per operator-started pass; up to three HTTP attempts |
| Ingestion resource/status reads | 2 | Exact-resource checks; normally five-second request timeout |
| Attachment POST | 0 | One submission; httpx timeout configured to 30 seconds, connect timeout five seconds |
| Vector-store creation | 0 | One submission through the provisioning service |

File creation inherits the base client's timeout. The initial polling scheduling window is approximately ten seconds and starts **after** attachment returns. Polling GET timeouts are narrowed to the lesser of five seconds and remaining scheduling time. An in-flight request and retries may outlast the scheduling window; it is not a hard wall-clock deadline. Healthy `in_progress` at expiry remains pending.

There is no additional application retry loop around an exhausted SDK request. Eligible targets without a persisted ID may retry in a later operator-started pass. This can leave unattached orphan Files after uncertain remote success; only the returned, persisted, verified ID is attached.

## Exact-ID recovery

[Known-file inspection](../../src/ingestion/known_file_recovery.py) retrieves the exact attachment. If absent, it verifies the store and underlying File, then checks attachment absence again.

- Present attachment: validate its identity/status and persist the observed state without another POST.
- Confirmed absence with `not_started`: the first attachment can proceed after checkpoint checks.
- Confirmed absence after an ambiguous prior attachment: offer **Attach existing file**, which repeats fresh checks and attaches the same ID.
- Missing/inaccessible underlying resources or mismatched identity: classify and retain the known ID; never create a replacement File.

**Refresh / recover known files** excludes new no-ID uploads, but is not universally read-only: it updates checkpoints and can perform the first attachment described above. The narrow inspection helper itself performs reads only.

## Continue, pause, stop, publish

| Pass outcome | Meaning |
| --- | --- |
| Continue after durable recording | Target-local problems or pending indexing allow unrelated targets to proceed when safe |
| Paused | Service access/auth/quota problems, unavailable store/client, or three consecutive infrastructure-related failures |
| Stopped | Integrity, persistence/readback, candidate identity, containment, frozen-state, or unexpected application failures |
| Finished | The pass exhausted its work; this alone does not mean the case is ready |

[Remote error classification](../../src/ingestion/remote_errors.py) and orchestration implement these boundaries. A missing known File can be a recorded target-local failure; a mismatched returned identity is an integrity stop.

[Readiness](../../src/ingestion/case_readiness.py) requires at least one searchable target and **100%** of required direct/worksheet targets with a persisted ID, uploaded state, and completed indexing, plus valid case/preprocessing state. Unsupported/ignored sources and explicitly excluded workbooks are not required searchable targets; unresolved errors/preprocessing block publication.

[Registration](../../src/config/case_registry.py) seals the ready snapshot before updating the registry. Registration can be retried after a registry write failure without reopening ingestion. See the [snapshot model](case-and-snapshot-model.md).

One writer per case is an operational constraint only. Atomic local file replacement and readback checks are not distributed transactions or locking.

## Regression anchors

[Workflow](../../tests/test_upload_workflow.py), [recovery](../../tests/test_ingestion_recovery.py), [real-SDK fake-transport policy](../../tests/test_ingestion_retry_policy.py), [candidate context](../../tests/test_retry_authorization.py), [Excel targets](../../tests/test_excel_upload_targets.py), and [publication readiness](../../tests/test_case_readiness.py) tests cover the key boundaries.
