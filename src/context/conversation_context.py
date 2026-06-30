"""Build compact conversation context for follow-up questions.

This module helps the assistant understand references like "that report"
or "these risks" by passing recent chat history into the retrieval flow.
"""

"""Build conversation context for follow-up questions.

This module prepares a compact conversation history that helps the
assistant understand references in follow-up questions.

The conversation history is only used to resolve context.
It must never be treated as factual evidence.
"""


def build_conversation_context(
    messages: list[dict],
    max_messages: int = 6,
) -> str:
    """Build a compact conversation history.

    Args:
        messages:
            Streamlit chat history.

        max_messages:
            Maximum number of recent messages to include.

    Returns:
        A formatted conversation string.
    """

    recent_messages = messages[-max_messages:]

    context = []

    for message in recent_messages:

        role = message.get("role", "unknown").upper()

        content = message.get("content", "").strip()

        if content:
            context.append(f"{role}: {content}")

    return "\n\n".join(context)
