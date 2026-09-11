# Q&A architecture

Current contract: **primary answer → combined support selection → optional Structured evidence**. OpenAI File Search remains primary retrieval. See [status](../project-status.md) for acceptance and limitations; [File Search](../decisions/file-search-primary-qa.md) and [evidence release](../decisions/verified-evidence-and-answer-release.md) decisions explain why.

## Case selection and primary answer

[The application](../../app/main.py) allows one prepared case to be active at a time per Streamlit session. Users can switch cases; [case selection](../../src/ui/case_selection.py) resets chat history and last-answer state when cases change and provides the active store and sealed manifest. [Active-manifest validation](../../src/ingestion/active_manifest.py) checks the selected store/manifest relationship.

[Q&A orchestration](../../src/chains/qa_chain.py) builds bounded recent conversational text, loads [the Q&A prompt](../../src/prompts/qa.md), and calls [the retrieval service](../../src/retrieval/openai_file_search.py). That service invokes Responses with the configured model, the selected vector store in a `file_search` tool, and inclusion of File Search results.

[Response extraction](../../src/retrieval/citation_extractor.py) and [search-result extraction](../../src/retrieval/search_result_extractor.py) separate answer text, citations, and passages. [Citation resolution](../../src/retrieval/citation_resolver.py) maps exact IDs through the selected manifest. Normal manifest-backed chat does not infer worksheet provenance from a proxy filename.

The primary validator rejects an unusable answer or absent resolved sources. A successful primary answer is still provisional; it has not passed the support gate.

## Combined support selection and release

Despite its historical filename, [quote_selector.py](../../src/retrieval/quote_selector.py) makes one combined selection call for quotations, Best support, and Additional context. It receives the current question, provisional answer, bounded recent context, and bounded retrieved passages from cited sources. Uncited search hits are not promoted into this scope.

[Quotation verification](../../src/validation/quote_verifier.py) and [excerpt verification](../../src/validation/evidence_selection_verifier.py) check source identity and source-text matching. Best/Additional candidates retain their identified passage index. Exact or whitespace-normalized source matching is permitted; model paraphrases are not accepted as verified source excerpts.

The release rule is:

- At least one verified Best excerpt across the answer's sources is required.
- Quotations are optional; missing/rejected quotations do not veto valid Best support.
- Additional-only sources do not veto another source's Best, and Additional is not automatically promoted to Best.
- A failed combined selector/verification stage withholds the provisional answer. No verified Best also withholds it.

The gate is answer-wide, not per-source: a cited source with no verified Best, Additional, or quotation material does not automatically block release if another cited source supplies at least one verified Best excerpt. A source lacking verified material must not be presented as having verified support.

The verifier retains at most one Best and three Additional excerpts per source. Semantic choice of what supports the answer is model-assisted; local matching establishes source traceability, not logical entailment of every claim. **This is an answer-wide gate, not claim-level validation.**

## Optional Structured evidence

After support succeeds, [presentation selection](../../src/presentation/evidence_selector.py) can make one additional model call for eligible source material. [Presentation verification](../../src/presentation/evidence_verifier.py) and [parallel-series verification](../../src/presentation/parallel_series_verifier.py) validate figures, tables, and explicit series against retrieved text.

Ambiguous relationships are omitted. Failure of optional Structured processing preserves the supported answer and ordinary verified evidence. A table synthesized in the main answer is not automatically verified cell by cell.

There are at most three application-level model stages on this path. That count excludes SDK retries and hosted-tool internals and does not mean every request runs every optional stage.

## Display, replay, and provenance

[Chat rendering](../../src/ui/chat.py) retains source/evidence payloads for replay. [The source sidebar](../../src/ui/source_panel.py) lists citations, while central evidence focuses on useful verified excerpts or Structured content. For sources with completed support selection, original/raw passage navigation shows stored passages mapped to selected verified Best/Additional excerpts; it does not guarantee that every retrieved search passage is surfaced in the UI. Normalization of selected excerpts can still affect whitespace and table/line-break formatting.

Excel citations map the remote artifact ID back to original workbook path and worksheet identity, as described in the [case/snapshot model](case-and-snapshot-model.md). Raw workbook bytes and local proxies are not reopened to verify a normal Q&A answer. The local directory and sealed manifest are nevertheless still needed to open the case.

[Conversation context](../../src/context/conversation_context.py) helps resolve follow-ups but is not evidence. Previous verified payloads are not reused as structured evidence in the next retrieval turn. Current navigation/replay limitations are tracked in [status](../project-status.md).

## Regression anchors

- [Primary File Search](../../tests/test_openai_file_search.py) and [citation resolution](../../tests/test_citation_resolver.py).
- [Release/selector tests](../../tests/test_qa_chain_quotes.py): provisional answer, fail-closed support, optional quotations, exact passage identity, cited-only scope.
- [Structured tests](../../tests/test_qa_chain_presentations.py): optional failure and independently verified presentation.
- [Excel provenance/replay](../../tests/test_excel_snapshot_provenance.py) and [chat UI](../../tests/test_chat_ui.py).
