"""Q&A workflow for the VDR Assistant.

This module orchestrates the full Q&A flow:

1. Build conversation context.
2. Load the Q&A prompt.
3. Search the active OpenAI vector store.
4. Extract answer text, citations, and retrieved passages.
5. Resolve and validate cited source files.
6. Treat the validated primary answer as provisional.
7. Select and locally verify quotations and supporting excerpts.
8. Release the answer when at least one verified Best excerpt exists.
9. Select and locally verify structured evidence presentations.
10. Return a VDRAnswer object.
"""

from pathlib import Path

from src.config.constants import FALLBACK_ANSWER
from src.context.conversation_context import build_conversation_context
from src.ingestion.manifest import VDRManifest
from src.retrieval.citation_extractor import extract_response_data
from src.retrieval.citation_resolver import (
    build_source_references,
    resolve_citations,
)
from src.retrieval.openai_file_search import search_vector_store
from src.retrieval.quote_selector import (
    build_recent_selector_context,
    build_quote_evidence_scope,
    select_quote_candidates,
)
from src.retrieval.search_result_extractor import extract_search_results
from src.presentation.evidence_selector import (
    build_evidence_presentation_scope,
    select_evidence_presentations,
)
from src.presentation.evidence_verifier import (
    attach_verified_presentations,
    verify_evidence_presentations,
)
from src.schemas.answer import VDRAnswer
from src.validation.answer_validator import validate_answer
from src.validation.evidence_selection_verifier import (
    verify_evidence_selection,
)
from src.validation.quote_verifier import verify_quote_candidates


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "qa.md"
BEST_SUPPORT_MISSING_ANSWER = (
    "I could not find a directly supporting source passage in the retrieved "
    "results, so I cannot provide a supported answer."
)
SUPPORT_PROCESSING_FAILED_ANSWER = (
    "I could not validate the supporting material because evidence processing "
    "failed. Please try again."
)
STRUCTURED_PROCESSING_FAILED_WARNING = (
    "Structured evidence could not be displayed. The answer and verified "
    "source excerpts remain available."
)


def _withheld_answer(
    message: str,
    *,
    processing_failed: bool = False,
) -> VDRAnswer:
    """Return a safe result containing none of the provisional answer state."""

    return VDRAnswer(
        answer=message,
        source_files=[],
        sources=[],
        quotes=[],
        verified_quotes=[],
        warnings=[],
        status="error" if processing_failed else "not_found",
        workflow="qa",
    )


def load_qa_prompt() -> str:
    """Load the Q&A workflow prompt from disk."""
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_qa_input(
    question: str,
    conversation_context: str,
) -> str:
    """Combine conversation context and the current user question."""

    if conversation_context.strip():
        return f"""
Conversation history:
{conversation_context}

Current user question:
{question}
""".strip()

    return question


def run_qa_chain(
    question: str,
    vector_store_id: str,
    messages: list[dict] | None = None,
    manifest: VDRManifest | None = None,
) -> VDRAnswer:
    """Run the Q&A workflow against the active VDR vector store."""

    if messages is None:
        messages = []

    conversation_context = build_conversation_context(messages)

    qa_input = build_qa_input(
        question=question,
        conversation_context=conversation_context,
    )

    try:
        instructions = load_qa_prompt()

        raw_response = search_vector_store(
            question=qa_input,
            vector_store_id=vector_store_id,
            instructions=instructions,
        )

        extracted = extract_response_data(raw_response)
        search_results = extract_search_results(raw_response)
        resolved_sources = resolve_citations(
            citations=extracted["citations"],
            manifest=manifest,
        )
        source_files = [source.display_name for source in resolved_sources]

        validated_answer = validate_answer(
            answer=extracted["answer"],
            source_files=source_files,
            quotes=extracted["quotes"],
            workflow="qa",
        )

        if validated_answer.status != "success":
            return validated_answer

        sources = build_source_references(
            citations=extracted["citations"],
            resolved_sources=resolved_sources,
            search_results=search_results,
        )
        try:
            support_scope = build_quote_evidence_scope(sources)
            selector_context = build_recent_selector_context(
                messages,
                question,
            )
            selection = select_quote_candidates(
                question=question,
                provisional_answer=validated_answer.answer,
                recent_context=selector_context,
                passages=support_scope,
            )
            if selection is None:
                return _withheld_answer(
                    SUPPORT_PROCESSING_FAILED_ANSWER,
                    processing_failed=True,
                )

            verified_quotes = verify_quote_candidates(
                candidates=selection.candidates,
                quote_sources=sources,
            )
            evidence_verification = verify_evidence_selection(
                selection=selection,
                sources=sources,
            )
        except Exception:
            return _withheld_answer(
                SUPPORT_PROCESSING_FAILED_ANSWER,
                processing_failed=True,
            )

        has_best_support = evidence_verification.best_support_count > 0
        if not has_best_support:
            return _withheld_answer(BEST_SUPPORT_MISSING_ANSWER)

        sources = evidence_verification.sources
        validated_answer = validated_answer.model_copy(
            update={
                "sources": sources,
                "verified_quotes": verified_quotes,
            }
        )

        # Structured output is optional; keep normal support intact on failure.
        try:
            presentation_scope = build_evidence_presentation_scope(sources)
            if not presentation_scope:
                return validated_answer

            presentation_selection = select_evidence_presentations(
                presentation_scope
            )
            presentations_by_file_id = verify_evidence_presentations(
                selection=presentation_selection,
                sources=sources,
                passage_scope=presentation_scope,
            )
            if presentations_by_file_id:
                sources = attach_verified_presentations(
                    sources=sources,
                    presentations_by_file_id=presentations_by_file_id,
                )
                validated_answer = validated_answer.model_copy(
                    update={"sources": sources}
                )
        except Exception:
            validated_answer = validated_answer.model_copy(
                update={
                    "warnings": [
                        *validated_answer.warnings,
                        STRUCTURED_PROCESSING_FAILED_WARNING,
                    ]
                }
            )

        return validated_answer

    except Exception as error:
        return VDRAnswer(
            answer=FALLBACK_ANSWER,
            source_files=[],
            quotes=[],
            warnings=[
                "The Q&A workflow failed while searching the VDR.",
                str(error),
            ],
            status="error",
            workflow="qa",
        )
