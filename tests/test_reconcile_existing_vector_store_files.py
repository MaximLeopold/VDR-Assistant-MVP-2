from scripts import reconcile_existing_vector_store_files as script


def test_manifest_v2_disables_historical_mutation(monkeypatch,capsys):
    def forbidden(*args,**kwargs):
        raise AssertionError('Disabled scripts must not request input or contact OpenAI.')
    monkeypatch.setattr('builtins.input',forbidden)
    assert script.main()==1
    assert 'Disabled for Manifest v2' in capsys.readouterr().err
