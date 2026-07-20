from types import SimpleNamespace

from openai.types.responses.response_output_text import AnnotationFileCitation

from src.retrieval.citation_extractor import extract_response_data
from src.schemas.citation import Citation


def response_with(*annotations):
    return SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(
                        type="output_text",
                        text="Supported answer",
                        annotations=list(annotations),
                    )
                ],
            )
        ]
    )


def file_citation(file_id: str, filename: str, index: int = 0):
    return AnnotationFileCitation(
        file_id=file_id,
        filename=filename,
        index=index,
        type="file_citation",
    )


def test_file_id_and_filename_survive_extraction() -> None:
    extracted = extract_response_data(
        response_with(file_citation("file-A", "report.pdf"))
    )

    assert extracted == {
        "answer": "Supported answer",
        "citations": [Citation(file_id="file-A", filename="report.pdf")],
        "quotes": [],
    }


def test_same_file_id_is_deduplicated_in_first_seen_order() -> None:
    extracted = extract_response_data(
        response_with(
            file_citation("file-B", "second.pdf", 0),
            file_citation("file-A", "first-name.pdf", 1),
            file_citation("file-B", "renamed.pdf", 2),
        )
    )

    assert extracted["citations"] == [
        Citation(file_id="file-B", filename="second.pdf"),
        Citation(file_id="file-A", filename="first-name.pdf"),
    ]


def test_different_file_ids_with_same_filename_both_survive() -> None:
    extracted = extract_response_data(
        response_with(
            file_citation("file-A", "report.pdf", 0),
            file_citation("file-B", "report.pdf", 1),
        )
    )

    assert [citation.file_id for citation in extracted["citations"]] == [
        "file-A",
        "file-B",
    ]


def test_non_file_citations_are_ignored() -> None:
    extracted = extract_response_data(
        response_with(
            SimpleNamespace(
                type="url_citation",
                url="https://example.test",
            ),
            file_citation("file-A", "report.pdf"),
        )
    )

    assert extracted["citations"] == [
        Citation(file_id="file-A", filename="report.pdf")
    ]


def test_missing_filename_is_retained_safely() -> None:
    extracted = extract_response_data(
        response_with(SimpleNamespace(type="file_citation", file_id="file-A"))
    )

    assert extracted["citations"] == [
        Citation(file_id="file-A", filename=None)
    ]


def test_missing_file_id_deduplicates_by_filename() -> None:
    annotation = SimpleNamespace(type="file_citation", filename="report.pdf")
    extracted = extract_response_data(response_with(annotation, annotation))

    assert extracted["citations"] == [
        Citation(file_id=None, filename="report.pdf")
    ]


def test_missing_identity_uses_one_stable_neutral_key() -> None:
    annotation = SimpleNamespace(type="file_citation")
    extracted = extract_response_data(response_with(annotation, annotation))

    assert extracted["citations"] == [
        Citation(file_id=None, filename=None)
    ]
