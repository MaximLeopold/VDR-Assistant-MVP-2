"""Q&A workflow for the VDR Assistant.

This module orchestrates the full Q&A flow:

1. Build conversation context.
2. Load the Q&A prompt.
3. Search the active OpenAI vector store.
4. Extract answer text, citations, and retrieved passages.
5. Resolve and validate cited source files.
6. Attach supplementary evidence to successful answers.
7. Select and locally verify concise source quotations.
8. Return a VDRAnswer object.
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
    build_quote_evidence_scope,
    select_quote_candidates,
)
from src.retrieval.search_result_extractor import extract_search_results
from src.schemas.answer import VDRAnswer
from src.validation.answer_validator import validate_answer
from src.validation.quote_verifier import verify_quote_candidates


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "qa.md"


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
        source_files = resolve_citations(
            citations=extracted["citations"],
            manifest=manifest,
        )

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
            source_files=source_files,
            search_results=search_results,
        )
        validated_answer = validated_answer.model_copy(
            update={"sources": sources}
        )

        quote_sources = build_quote_evidence_scope(sources)
        if not quote_sources:
            return validated_answer

        candidates = select_quote_candidates(
            answer=validated_answer.answer,
            quote_sources=quote_sources,
        )
        verified_quotes = verify_quote_candidates(
            candidates=candidates,
            quote_sources=quote_sources,
        )
        if verified_quotes:
            validated_answer = validated_answer.model_copy(
                update={"verified_quotes": verified_quotes}
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
