from pathlib import Path

from scripts import adopt_existing_vector_store as script


def test_redaction_hides_full_id() -> None:
    value = "vs_synthetic_123456"

    redacted = script.redact_vector_store_id(value)

    assert value not in redacted
    assert redacted.startswith("vs_s")
    assert redacted.endswith("3456")


def test_non_explicit_confirmation_aborts_before_client_creation(
    monkeypatch,
) -> None:
    fake_manifest = type("Manifest", (), {"case_name": "Project Falcon"})()
    monkeypatch.setattr(script, "load_manifest", lambda path: fake_manifest)
    monkeypatch.setattr(script, "VECTOR_STORE_ID", "vs_synthetic")
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    client_factory_called = False

    def client_factory():
        nonlocal client_factory_called
        client_factory_called = True
        raise AssertionError("must not create a client")

    monkeypatch.setattr(script, "get_openai_client", client_factory)

    assert script.main([str(Path("synthetic-vdr"))]) == 2
    assert client_factory_called is False


def test_explicit_confirmation_calls_adoption_not_creation(
    monkeypatch,
) -> None:
    fake_manifest = type("Manifest", (), {"case_name": "Project Falcon"})()
    fake_result = type(
        "Result",
        (),
        {"action": "adopted", "remote_name": "Historical Store"},
    )()
    fake_client = object()
    calls = []
    monkeypatch.setattr(script, "load_manifest", lambda path: fake_manifest)
    monkeypatch.setattr(script, "VECTOR_STORE_ID", "vs_synthetic")
    monkeypatch.setattr("builtins.input", lambda prompt: "ADOPT")
    monkeypatch.setattr(script, "get_openai_client", lambda: fake_client)

    def adopt(client, path, candidate):
        calls.append((client, path, candidate))
        return fake_result

    monkeypatch.setattr(script, "adopt_case_vector_store", adopt)

    assert script.main([str(Path("synthetic-vdr"))]) == 0
    assert calls == [(fake_client, Path("synthetic-vdr"), "vs_synthetic")]
