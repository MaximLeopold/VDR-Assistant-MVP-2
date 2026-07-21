"""Deterministic, presentation-only handling of retrieved evidence text."""


MAX_VISIBLE_EVIDENCE_PASSAGES = 2
MAX_VISIBLE_EVIDENCE_CHARS = 1200


def clean_evidence_text(text: str) -> str:
    """Clean whitespace layout without changing non-whitespace content."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(" \t") for line in normalized.split("\n")]

    first_content = 0
    while first_content < len(lines) and not lines[first_content].strip():
        first_content += 1

    last_content = len(lines)
    while last_content > first_content and not lines[last_content - 1].strip():
        last_content -= 1

    cleaned_lines: list[str] = []
    previous_was_blank = False
    for line in lines[first_content:last_content]:
        is_blank = not line.strip()
        if is_blank:
            if not previous_was_blank:
                cleaned_lines.append("")
        else:
            cleaned_lines.append(line)
        previous_was_blank = is_blank

    return "\n".join(cleaned_lines)


def truncate_evidence_excerpt(
    text: str,
    max_chars: int = MAX_VISIBLE_EVIDENCE_CHARS,
) -> str:
    """Return one bounded raw excerpt without mutating stored evidence."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if max_chars < 0:
        raise ValueError("max_chars must not be negative")
    if len(text) <= max_chars:
        return text

    prefix = text[: max_chars + 1]
    boundary = max(
        (
            index
            for index, character in enumerate(prefix)
            if character.isspace()
        ),
        default=-1,
    )

    if boundary > 0:
        excerpt = text[:boundary]
    else:
        excerpt = text[:max_chars]

    return excerpt.rstrip() + "…"
