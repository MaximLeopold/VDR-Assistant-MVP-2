"""Q&A workflow for the VDR Assistant.

This module orchestrates the full Q&A flow:

1. Build conversation context.
2. Load the Q&A prompt.
3. Search the active OpenAI vector store.
4. Extract answer text and source files.
5. Validate the answer.
6. Return a VDRAnswer object.
"""

from pathlib import Path

from src.config.constants import FALLBACK_ANSWER
from src.context.conversation_context import build_conversation_context
from src.retrieval.openai_file_search import search_vector_store
from src.retrieval.citation_extractor import extract_response_data
from src.schemas.answer import VDRAnswer
from src.validation.answer_validator import validate_answer


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

        validated_answer = validate_answer(
            answer=extracted["answer"],
            source_files=extracted["source_files"],
            quotes=extracted["quotes"],
            workflow="qa",
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