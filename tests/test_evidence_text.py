import pytest

from src.presentation.evidence_text import (
    MAX_VISIBLE_EVIDENCE_CHARS,
    clean_evidence_text,
    truncate_evidence_excerpt,
)


def non_whitespace(text: str) -> str:
    return "".join(character for character in text if not character.isspace())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ""),
        (" \t\r\n \n", ""),
        ("\u00a0\u2003", ""),
        ("\n\nHeading", "Heading"),
        ("Heading\n\n", "Heading"),
        ("First\r\nSecond\rThird\nFourth", "First\nSecond\nThird\nFourth"),
        ("First  \nSecond\t\nThird", "First\nSecond\nThird"),
        ("First\n\n\n \t\nSecond", "First\n\nSecond"),
        ("  indented\n\tTabbed", "  indented\n\tTabbed"),
        ("Prose line one\nprose line two", "Prose line one\nprose line two"),
        ("• Item one\n  • Item two", "• Item one\n  • Item two"),
        ("1. First\n2. Second", "1. First\n2. Second"),
        ("H1\nShort\nSection heading", "H1\nShort\nSection heading"),
        (
            "Revenue  €42.6m\t(+11.8%)\n2026-06-30  (EUR -3.2m)",
            "Revenue  €42.6m\t(+11.8%)\n2026-06-30  (EUR -3.2m)",
        ),
        ("A\u00a0B\u2003C\n漢字 ✓", "A\u00a0B\u2003C\n漢字 ✓"),
        ("Value\u2003", "Value\u2003"),
        ("hyphen-\nated remains", "hyphen-\nated remains"),
        ("x" * 5000, "x" * 5000),
    ],
)
def test_clean_evidence_text_is_conservative(text: str, expected: str) -> None:
    cleaned = clean_evidence_text(text)

    assert cleaned == expected
    assert non_whitespace(cleaned) == non_whitespace(text)
    assert clean_evidence_text(cleaned) == cleaned


@pytest.mark.parametrize(
    "text",
    [
        "Capitalization, punctuation: unchanged!",
        "Revenue €38.1m → €42.6m (+11.8%) at 2026/06/30.",
        "Chart\n2024  -1.2%\n2025  +3.40%",
        "Label\t\tQ1\tQ2\nEBITDA  (€m)\t10.2\t11.7",
        "Unicode £ ¥ € % ± − ✓ 漢字",
    ],
)
def test_cleanup_preserves_lexical_content_exactly(text: str) -> None:
    decorated = f"\r\n\t \r\n{text}  \t\r\n\r\n"

    cleaned = clean_evidence_text(decorated)

    assert non_whitespace(cleaned) == non_whitespace(decorated)
    for token in (
        "€38.1m",
        "€42.6m",
        "+11.8%",
        "2026/06/30",
        "-1.2%",
        "+3.40%",
        "(€m)",
        "£",
        "¥",
        "±",
        "−",
    ):
        if token in text:
            assert token in cleaned


@pytest.mark.parametrize("value", [None, 42, [], object()])
def test_clean_evidence_text_rejects_non_strings(value: object) -> None:
    with pytest.raises(TypeError):
        clean_evidence_text(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "max_chars", "expected"),
    [
        ("", 10, ""),
        (" \t\n ", 10, " \t\n "),
        ("  leading", 20, "  leading"),
        ("trailing  ", 20, "trailing  "),
        ("exact text", 10, "exact text"),
        ("alpha beta gamma", 10, "alpha beta…"),
        ("abcdefghijk", 5, "abcde…"),
        ("äöüß漢字abcdef", 6, "äöüß漢字…"),
        ("first\nsecond third", 13, "first\nsecond…"),
        ("first\tsecond third", 13, "first\tsecond…"),
    ],
)
def test_truncate_evidence_excerpt(
    text: str,
    max_chars: int,
    expected: str,
) -> None:
    assert truncate_evidence_excerpt(text, max_chars) == expected


def test_long_excerpt_appends_one_ellipsis_outside_the_limit() -> None:
    excerpt = truncate_evidence_excerpt("x" * 1300)

    assert excerpt == "x" * MAX_VISIBLE_EVIDENCE_CHARS + "…"
    assert len(excerpt) == MAX_VISIBLE_EVIDENCE_CHARS + 1
    assert excerpt.count("…") == 1


def test_truncation_does_not_mutate_stored_text() -> None:
    stored = "  " + ("passage " * 300) + "  "
    original = stored[:]

    truncate_evidence_excerpt(stored)

    assert stored == original


def test_negative_excerpt_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        truncate_evidence_excerpt("passage", -1)


def test_truncation_rejects_non_strings() -> None:
    with pytest.raises(TypeError):
        truncate_evidence_excerpt(None)  # type: ignore[arg-type]
