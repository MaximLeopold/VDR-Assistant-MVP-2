from types import SimpleNamespace

from src.config.settings import OPENAI_MODEL
from src.retrieval import openai_file_search


def test_search_request_includes_results_without_other_retrieval_changes(
    monkeypatch,
) -> None:
    raw_response = object()
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return raw_response

    client = SimpleNamespace(responses=FakeResponses())
    monkeypatch.setattr(
        openai_file_search,
        "get_openai_client",
        lambda: client,
    )

    returned = openai_file_search.search_vector_store(
        question="Question with context",
        vector_store_id="vs-test",
        instructions="Keep the prompt unchanged",
    )

    assert returned is raw_response
    assert captured == {
        "model": OPENAI_MODEL,
        "input": "Question with context",
        "instructions": "Keep the prompt unchanged",
        "tools": [
            {
                "type": "file_search",
                "vector_store_ids": ["vs-test"],
            }
        ],
        "include": ["file_search_call.results"],
    }

    tool = captured["tools"][0]
    assert "max_num_results" not in tool
    assert "filters" not in tool
    assert "ranking_options" not in tool
    assert "ranker" not in tool
    assert "score_threshold" not in tool
