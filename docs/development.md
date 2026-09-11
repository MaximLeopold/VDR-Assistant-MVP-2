# Development guide

Start with [project status](project-status.md) and [AGENTS.md](../AGENTS.md). [README.md](../README.md) provides the public-facing overview and navigation; this guide owns setup, development, and validation procedures. Use architecture documents for behavior and decision records for rationale. Historical handovers and reports are not executable development instructions.

## Environment and configuration

The application entry point is [app/main.py](../app/main.py). Dependencies are declared in [requirements.txt](../requirements.txt); most are unpinned, while openpyxl is pinned. The repository does not declare a tested Python-version range or contain a dependency lockfile. The resilient-ingestion report records its historical validation environment; it is not a compatibility guarantee for every environment.

From the repository root, a Windows environment can be prepared without changing shell execution policy:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Configure an ignored local `.env` using [.env.example](../.env.example). [Settings](../src/config/settings.py) load `OPENAI_API_KEY`, `OPENAI_MODEL`, and `CASE_REGISTRY_PATH`. Existing process environment values are not overridden by the default dotenv load. Do not print or commit credentials.

The code and environment example default the model to `gpt-4o`; historical live configuration differs. A default/example is not evidence of the local runtime value or a recommendation to change it. Record the actual non-secret model configuration when conducting authorized live acceptance.

The ignored registry stores only `case_id` and `vdr_folder`. Registry-relative VDR paths resolve from the registry file's directory. The selected manifest owns the case name and vector-store ID. `VECTOR_STORE_ID` and `VDR_FOLDER` settings remain for legacy scripts, not normal case-selected chat.

The example registry is a shape example, not a ready case. Use an actual raw VDR directory outside this application repository, with its sibling `VDR Assistant` directory.

Start the local UI with:

```powershell
& .\.venv\Scripts\python.exe -m streamlit run app/main.py --server.address 127.0.0.1
```

Starting Streamlit is distinct from authorizing live Q&A, association, ingestion, or recovery. Those operations contact OpenAI and require explicit authorization for the relevant data, remote resources, and acceptance scope.

## Offline validation

Use synthetic fixtures and fake credentials. [Tests](../tests/) exercise clients through mocks and, for SDK retry behavior, `httpx.MockTransport`. Do not assume that a test is offline merely because pytest launched.

A network-blocked launcher, run from the repository root, is:

```powershell
@'
import os
import socket
import tempfile
import pytest

os.environ["OPENAI_API_KEY"] = "offline-test-key"

def deny_network(*args, **kwargs):
    raise RuntimeError("Network access is disabled for offline tests")

socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network

with tempfile.TemporaryDirectory(prefix="vdr-offline-") as scratch:
    raise SystemExit(pytest.main([
        "-q", "--tb=short", "--basetemp=" + scratch, "tests"
    ]))
'@ | & .\.venv\Scripts\python.exe -B -
```

This blocks Python socket connections in this process; it is not an OS-wide network sandbox. Keep real remote-operation scripts out of the test run. For focused validation, replace `"tests"` with the relevant test paths; retain the network guard and fake key.

Use a unique disposable writable temporary location outside the repository/raw VDR. If temporary-directory permissions prevent offline tests from executing, treat this as an environment issue; do not change production code or weaken tests to accommodate it. Do not add machine-specific ACL or permission workarounds to repository instructions unless they become a reproducible project requirement. Report blocked execution accurately rather than claiming a passing run.

| Changed behavior | Relevant tests |
| --- | --- |
| Primary retrieval and citations | [File Search](../tests/test_openai_file_search.py), [citation resolution](../tests/test_citation_resolver.py), [Q&A citations](../tests/test_qa_chain_citations.py) |
| Release, quotations, Structured | [Q&A support](../tests/test_qa_chain_quotes.py), [presentations](../tests/test_qa_chain_presentations.py), [quote verifier](../tests/test_quote_verifier.py), [selection verifier](../tests/test_evidence_selection_verifier.py) |
| Recovery and transport policy | [recovery](../tests/test_ingestion_recovery.py), [retry policy](../tests/test_ingestion_retry_policy.py), [candidate identity](../tests/test_retry_authorization.py) |
| Excel/snapshots | [preprocessing](../tests/test_excel_preprocessing.py), [parser recovery](../tests/test_excel_parser_recovery.py), [upload targets](../tests/test_excel_upload_targets.py), [snapshot provenance](../tests/test_excel_snapshot_provenance.py), [structural validation](../tests/test_excel_structural_validation.py) |
| Publication and UI | [readiness](../tests/test_case_readiness.py), [registration](../tests/test_case_registry_registration.py), [case selection](../tests/test_case_selection.py), [new-case UI](../tests/test_new_case_setup_ui.py) |

Match validation to the change. Use focused tests for scoped changes; run the full suite only when the change and regression risk justify it. Ingestion/Q&A contract changes need relevant regressions and, before product acceptance, authorized live checks where retrieval/remote behavior matters. Documentation-only changes need factual review, relative-link checks, and whitespace/diff inspection; they do not require live operations or a full runtime suite.

## Authorized live acceptance

Define acceptance from the affected behavior and the explicitly authorized case, data, remote resources, operations, and questions. Use synthetic or explicitly authorized real acceptance material.

- **Ingestion / case-lifecycle changes:** validate the relevant end-to-end lifecycle where affected, including preparation and coverage, association, ingestion/recovery, readiness, sealing/registration, and Q&A/provenance where relevant.
- **Q&A / retrieval changes:** an already prepared, explicitly authorized case may be used. A new vector store or fresh ingestion is not required merely to validate Q&A behavior.
- **Remote recovery / transport-policy changes:** exercise the relevant explicitly authorized remote path without requiring unrelated lifecycle stages.
- **Documentation-only changes:** no live OpenAI operations are required.

Retrieval-quality changes should include representative live questions, including a broad compound question where appropriate. Offline mocks cannot establish retrieval recall.

Record the tested commit, environment/model, scope, outcomes, and unresolved failures. Do not copy credentials, private source content, private document names, live resource IDs, or private paths into public repository documentation or fixtures. Keep necessary private acceptance details in controlled local records. Do not infer that every edge case was live-tested from one successful corpus run.

## Ingestion operations and local data

Read [ingestion architecture](architecture/ingestion-architecture.md) before operating [the upload CLI](../scripts/upload_new_manifest_files.py) or the preparation UI. The CLI's UPLOAD, RECOVER, and ATTACH actions share orchestration with Streamlit. RECOVER can attach a known file whose first attachment never started; it is not a blanket read-only operation.

Keep raw VDR sources read-only and assistant outputs in their separate sibling location. Hydrating a cloud placeholder can occur when a local readability probe opens it. Ensure approved source files are available locally before ingestion.

Do not clear IDs, reset upload state, rewrite sealed manifests, or use legacy refresh/adoption/reconciliation scripts as a repair shortcut. One writer per case is an operational rule; atomic manifest/registry replacement provides no multi-user lock.

[.gitignore](../.gitignore) is not a complete data-protection boundary: arbitrary spreadsheets and Markdown/text proxies outside the designated managed location are not universally ignored. Inspect proposed Git content.

## Change and documentation workflow

1. Inspect the branch, HEAD, and working tree before editing. Respect the user's selected branch and preserve unrelated changes.
2. Identify the current architecture contract and its regression tests. Separate retrieval, model/synthesis, verification, and rendering problems when diagnosing Q&A.
3. Make the scoped change. Preserve existing encoding/line endings; avoid unrelated normalization or generated artifacts.
4. Review the diff and validate the affected behavior. New untracked documents need direct review too; ordinary `git diff` does not include them.
5. Verify relative repository links and distinguish code-backed behavior from reported acceptance.
6. Update architecture for how the current system works, decisions for accepted trade-offs and rationale, history for milestone transitions, and status for mutable state and dated acceptance.
7. Report the changes, checks, and uncertainty. Commit, push, and branch/resource operations require authorization within the user's task.

Shared Team Access is next, followed by SharePoint integration. Their implementation architectures remain TBD and require dedicated options analysis, trade-off evaluation, and explicit design decisions. Current-baseline procedures do not prescribe future implementation choices.

This workflow does not prescribe a particular Codex model, hosting platform, automatic task configuration, or fixed sequence across Codex desktop, VS Code, and ChatGPT. The repo-local skills below support explicitly requested development tasks. Project status records the current skills/workflow milestone and its validation progress.

## Repo-local Codex skills

`.agents/` contains development/Codex tooling only. It is not part of the VDR application runtime and does not change application configuration or behavior.

The currently installed skills are:

| Skill | Purpose and boundary |
| --- | --- |
| `grill-me` | Minimal explicit wrapper that reads and follows the installed `grilling` procedure. Invocation alone does not authorize repository edits. |
| `grilling` | Design interview procedure that establishes shared understanding before action. |
| `handoff` | Produces a continuation document in the operating system’s temporary directory when requested. It does not finalize a development milestone. |
| `improve-codebase-architecture` | VDR-specific, read-only architecture inspection. Returns its report in the conversation and does not implement recommendations. |
| `update-project-documentation` | VDR-specific documentation workflow: read-only DRAFT → human review → explicit approval → scoped APPLY → validation → STOP. |
| `development-milestone-handoff` | Durable milestone handover for future development sessions: read-only DRAFT → human review → explicit approval of content, version, filename, and exact destination → create one approved file → validation → STOP. |

All six skills set `policy.allow_implicit_invocation: false` in their respective `agents/openai.yaml` files. Request the intended skill explicitly. An explicitly invoked wrapper may load its required dependency; `grill-me` reads `.agents/skills/grilling/SKILL.md`, relative to the repository root.

Detailed instructions remain in each skill’s `SKILL.md`. The three upstream-derived skills were sourced from `mattpocock/skills` at commit `3cca18b368ae95cdbdebbff572ccafa662551015`. `grilling` and `handoff` retain their upstream content. `grill-me` replaces only the dependency instruction with a Codex-compatible file reference and invocation boundary.

### Documentation review and application

`update-project-documentation` starts in DRAFT MODE. It inspects the accepted implementation and maintained documentation, returns concrete proposed changes in the conversation, and stops without creating or modifying files.

APPLY MODE requires an explicit instruction to apply the reviewed changes. Before editing, recheck the draft’s branch, HEAD, relevant implementation, and documentation basis. Apply only the approved files and content, validate the diff, and stop.

Existing decision records must be preserved. A superseding decision requires a separately proposed and explicitly approved new record. `AGENTS.md` changes require separate governance review and cannot be applied through this skill. Source code, tests, application configuration, skills, and historical archives are outside its edit scope.

The documentation skill does not finalize a milestone or create its handoff. These skills do not authorize staging, committing, pushing, merging, or changing branches.

### Development milestone handover

`handoff` produces a conversation continuation document in the operating system’s temporary directory. `development-milestone-handoff` produces a durable project milestone record intended to help start future development sessions.

`development-milestone-handoff` starts in read-only DRAFT MODE. It inspects the current repository, maintained documentation, available prior handover structure, and acceptance evidence; returns the complete proposed handover in the conversation; and stops. The draft distinguishes verified repository state, reported results, user-confirmed acceptance, and inference.

CREATE MODE requires explicit approval of the handover content, version, filename, and exact destination path. Before creation, recheck the repository and milestone basis and perform the required privacy/publication review. A materially stale draft must be regenerated or explicitly reconfirmed.

Create exactly one approved Markdown handover file, read it back, compare it with the approved draft, validate applicable links and whitespace, and report its repository/tracking status. Do not modify other files or automatically update maintained documentation or the handover archive/index.

Maintained-documentation reconciliation and milestone-handover creation are separate, explicitly requested workflows. Neither automatically invokes the other or authorizes staging, committing, pushing, merging, changing branches, or starting the next milestone. A handover records the verified milestone and promotion state; creating it does not itself promote the baseline.

The next session should read the handover together with `AGENTS.md` and maintained documentation, verify actual Git state, and resolve differences using the repository’s authority hierarchy. Current validation results and outstanding milestone checks belong in [project status](project-status.md).

Validate tooling changes through content and diff review, metadata checks, and scoped functionality tests. Static validation and runtime testing establish different things; record their actual outcomes and remaining checks in project status.
