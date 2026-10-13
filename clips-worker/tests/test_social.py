import json
import tempfile
from pathlib import Path
import pytest
from social import Vault, Connectors, check


def test_vault_round_trip():
    with tempfile.TemporaryDirectory() as d:
        v=Vault(Path(d))
        v.save('youtube',{'access_token':'secret-not-in-plaintext'})
        assert v.get('youtube')['access_token']=='secret-not-in-plaintext'
        assert 'secret-not-in-plaintext' not in v.data_path.read_bytes().decode('ascii')
        v.delete('youtube')
        assert v.get('youtube') is None


def test_oauth_state_validation(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        v=Vault(Path(d)); c=Connectors(v)
        monkeypatch.setenv('YOUTUBE_CLIENT_ID','test-id');monkeypatch.setenv('YOUTUBE_CLIENT_SECRET','test-secret')
        url=c.start('youtube')
        assert 'accounts.google.com' in url and '127.0.0.1' in url
        with pytest.raises(ValueError, match='state'):
            c.finish('youtube','invalid','fake-code')


def test_platform_keys_are_only_checked_not_returned(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        v=Vault(Path(d)); c=Connectors(v)
        monkeypatch.setenv('TIKTOK_CLIENT_KEY','this-is-a-private-client-key')
        monkeypatch.setenv('TIKTOK_CLIENT_SECRET','this-is-a-private-client-secret')
        assert c.info()['tiktok']['configured']
        assert 'this-is-a-private-client-key' not in json.dumps(c.info())


def test_tiktok_private_requires_actual_oauth(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        c=Connectors(Vault(Path(d)))
        with pytest.raises(ValueError,match='Connect'):
            c.tiktok_options()
