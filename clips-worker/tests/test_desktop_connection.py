import os
import desktop_connection as connection
import credential_protection


def test_replacement_and_forgotten_desktop_key(monkeypatch, tmp_path):
    if os.name != 'nt':
        return
    keyfile = tmp_path / 'api-key.dpapi'
    monkeypatch.setattr(connection, '_path', keyfile)
    monkeypatch.setattr(connection, '_stamp', None)
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-old-placeholder-never-real')
    monkeypatch.setattr(credential_protection, 'windows_key', lambda data, encrypt: b'sk-replacement-placeholder-never-real')
    keyfile.write_bytes(b'encrypted-test-fixture')
    connection.refresh_desktop_connection()
    assert os.getenv('OPENAI_API_KEY') == 'sk-replacement-placeholder-never-real'
    keyfile.unlink()
    connection.refresh_desktop_connection()
    assert not os.getenv('OPENAI_API_KEY')
