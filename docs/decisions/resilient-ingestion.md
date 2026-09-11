# Decision: recover known IDs and allow later-pass no-ID retries

Status: accepted, including the final attachment-timeout correction.

## Context and decision

The conservative Excel implementation stopped on uncertain upload outcomes. A live candidate stalled before full ingestion, despite otherwise valid source preparation. Proving that a failed request had never reached the remote service was operationally restrictive.

Retain sequential orchestration and durable checkpoints, but distinguish targets by persisted identity:

- Persist and verify a returned File ID before attachment.
- Known-ID UploadTargets never repeat `files.create`; recover exact remote resources.
- Eligible no-ID targets may retry in later operator-started passes after fresh validation.
- Continue after durably recorded target-local problems; pause systemic failures and stop integrity failures.
- Keep strict 100% readiness and sealed publication.

## Superseded alternatives

The earlier session-bound safe-retry authorization and proposed durable retry-proof metadata/schema extension were superseded. The accepted implementation added no replacement proof subsystem or schema migration.

A uniform zero-retry policy was replaced with operation-specific policy: two SDK retries for File creation/reads; zero for attachment/store creation. There is no extra application retry loop around an exhausted SDK call.

Filename matching, discovering/adopting orphan Files, clearing known IDs, blind re-upload of known targets, and automatic orphan deletion were not adopted.

## Consequences and accepted trade-off

An uncertain File creation can succeed remotely without a usable response. SDK retries or a later no-ID pass can therefore leave unattached orphan Files. This is accepted; automatic orphan cleanup is not implemented.

The searchable store is protected by attaching only the returned, persisted, verified ID. This is not exactly-once remote storage and not a distributed transaction. A local persistence failure remains an integrity stop.

Exact-ID recovery distinguishes first attachment from ambiguous reattachment. The latter requires an explicit same-ID action after repeated absence/resource checks. Recovery never authorizes creating a replacement File.

Short initial polling preserves healthy pending state. The final correction separates a 30-second attachment transport timeout (five-second connect timeout) from the approximately ten-second polling scheduling window, which starts after attachment. These settings are not a hard total-duration guarantee.

Finished passes can still be unready. One writer per case remains operational policy without a technical lock; shared persistence/coordination is deferred.

## Evidence and implementation

V10 records the motivating live stall. V11 records final offline and live acceptance; totals belong in [status](../project-status.md). See [handover index](../archive/handovers/README.md).

The [design report](../../exports/Resilient_Ingestion_Recovery_Design_Report_2026-09-10.md) is historical: its retry-proof/schema proposal was not the accepted implementation. The [implementation report](../../exports/Resilient_Ingestion_Recovery_Implementation_Report_2026-09-10.md) explains the accepted orchestration but predates the final timeout correction and live acceptance. Neither overrides maintained docs or current code/tests.

How it works: [ingestion architecture](../architecture/ingestion-architecture.md). Code/tests: [workflow](../../src/ingestion/upload_workflow.py), [known-file inspection](../../src/ingestion/known_file_recovery.py), [policy](../../src/ingestion/openai_policy.py), [recovery tests](../../tests/test_ingestion_recovery.py), and [retry/timeout tests](../../tests/test_ingestion_retry_policy.py).
