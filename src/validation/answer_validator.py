"""Validate VDR answers before rendering.

This module should enforce the rule that every answer needs at least
one citation, otherwise the fallback sentence is returned.
"""

"""Validate extracted VDR answers.

This module is responsible for deciding whether an extracted
answer satisfies the application's quality requirements.
"""

from src.config.constants import FALLBACK_ANSWER
from src.schemas.answer import VDRAnswer


def validate_answer(
    answer: str,
    source_files: list[str],
    quotes: list[str],
    workflow: str = "qa",
) -> VDRAnswer:
    """Validate an extracted answer.

    Rules:

    - Every answer must have at least one source file.
    - Empty answers are treated as not found.
    - Unsupported answers return the fallback message.

    Returns:
        A validated VDRAnswer object.
    """

    if not answer.strip():
        return VDRAnswer(
            answer=FALLBACK_ANSWER,
            source_files=[],
            quotes=[],
            warnings=["No answer returned by the model."],
            status="not_found",
            workflow=workflow,
        )

    if len(source_files) == 0:
        return VDRAnswer(
            answer=FALLBACK_ANSWER,
            source_files=[],
            quotes=[],
            warnings=["Answer contains no supporting citations."],
            status="not_found",
            workflow=workflow,
        )

    return VDRAnswer(
        answer=answer,
        source_files=source_files,
        quotes=quotes,
        warnings=[],
        status="success",
        workflow=workflow,
    )
