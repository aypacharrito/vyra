import base64
import hashlib
import json
import os
import time
from urllib.parse import parse_qs, urlparse

import pytest
import social
from social import Connectors, Vault, facebook_post


@pytest.fixture
def connectors(tmp_path, monkeypatch):
    from connection_settings import FIELDS
    for fields in FIELDS.values():
        for variable in fields.values(): monkeypatch.delenv(variable, raising=False)
    return Connectors(Vault(tmp_path))


def test_google_import_is_encrypted_and_does_not_expose_secrets(connectors):
    secret = 'private-google-secret'
    saved = connectors.settings.save('youtube', {'credential_json': json.dumps({'installed': {
        'client_id': '123-example.apps.googleusercontent.com', 'client_secret': secret}})})
    assert saved['configured']
    assert secret not in json.dumps(saved)
    assert secret.encode() not in connectors.vault.data_path.read_bytes()
    assert secret not in json.dumps(connectors.info())
    url = connectors.start('youtube')
    query = parse_qs(urlparse(url).query)
    pending = connectors.pending[query['state'][0]]
    expected = base64.urlsafe_b64encode(hashlib.sha256(pending['verifier'].encode()).digest()).rstrip(b'=').decode()
    assert query['code_challenge'] == [expected]
    assert query['code_challenge_method'] == ['S256']
    assert query['scope'] == ['https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly']
    if os.name == 'nt':
        assert (connectors.vault.directory / 'vault-key.dpapi').is_file()
        assert not connectors.vault.key_path.exists()


def test_callback_configuration_and_google_file_validation(connectors):
    for invalid in ['not json', '[]', '{}', '{"installed":{}}']:
        with pytest.raises(ValueError): connectors.settings.save('youtube', {'credential_json': invalid})
    for invalid in ['https://host.example/callback?secret=hidden', 'file:///tmp/callback', 'http://localhost.evil.example/callback']:
        with pytest.raises(ValueError): connectors.settings.save('facebook', {
            'client_id':'123', 'client_secret':'private', 'redirect_uri':invalid})


def test_existing_windows_vault_migrates_without_losing_connections(tmp_path):
    if os.name != 'nt': pytest.skip('Windows account protection')
    from cryptography.fernet import Fernet
    key=Fernet.generate_key()
    (tmp_path/'vault.key').write_bytes(key)
    (tmp_path/'vault.bin').write_bytes(Fernet(key).encrypt(json.dumps({'youtube':{'access_token':'old-private-token'}}).encode()))
    migrated=Vault(tmp_path)
    assert migrated.get('youtube')['access_token'] == 'old-private-token'
    assert not (tmp_path/'vault.key').exists()
    reopened=Vault(tmp_path)
    assert reopened.get('youtube')['access_token'] == 'old-private-token'


def test_facebook_page_selection_never_exposes_tokens(connectors):
    connectors.vault.save('facebook', {'access_token':'private-user-token', 'saved_at':time.time(),
        'pages':[{'id':'111','name':'First Page','access_token':'private-page-one'},
                 {'id':'222','name':'Second Page','access_token':'private-page-two'}]})
    info=connectors.info()['facebook']
    assert not info['connected'] and len(info['pages']) == 2
    assert 'private-' not in json.dumps(info)
    with pytest.raises(ValueError): connectors.select_page('999')
    result=connectors.select_page('222')
    assert result['account'] == 'Second Page'
    token, account=connectors.token('facebook')
    assert token == 'private-page-two' and account['page_id'] == '222'
    assert 'private-' not in json.dumps(connectors.info())


def test_changing_app_details_requires_a_fresh_sign_in(connectors):
    body={'client_id':'123', 'client_secret':'one', 'redirect_uri':'https://vyra-five-lac.vercel.app/api/facebook-callback'}
    connectors.settings.save('facebook',body)
    connectors.vault.save('facebook',{'access_token':'old'})
    connectors.settings.save('facebook',{})
    assert connectors.vault.get('facebook') is not None
    connectors.settings.save('facebook',{'client_secret':'two'})
    assert connectors.vault.get('facebook') is None


class Response:
    ok=True
    status_code=200
    def __init__(self,data): self.data=data
    def json(self): return self.data


def test_facebook_upload_uses_selected_page_and_validates_endpoint(connectors,tmp_path,monkeypatch):
    video=tmp_path/'clip.mp4'; video.write_bytes(b'test clip')
    connectors.vault.save('facebook', {'access_token':'user-token', 'page_access_token':'page-token',
        'page_id':'222', 'account':'Second Page', 'saved_at':time.time()})
    import clip_engine
    monkeypatch.setattr(clip_engine,'probe',lambda _: {'duration':30,'width':1080,'height':1920})
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        if kwargs.get('data') == {'upload_phase':'start'}:
            return Response({'video_id':'333','upload_url':'https://rupload.facebook.com/video-upload/v24.0/333'})
        return Response({'success':True})
    monkeypatch.setattr(social.requests,'post',post)
    result=facebook_post(connectors,video,'Title','Caption')
    assert result['id'] == '333' and result['page'] == 'Second Page'
    assert len(calls) == 3
    assert calls[0][0].endswith('/222/video_reels')
    assert calls[1][1]['headers']['Authorization'] == 'OAuth page-token'
    assert calls[2][1]['data']['video_state'] == 'PUBLISHED'
    calls.clear()
    monkeypatch.setattr(social.requests,'post',lambda *a,**k: Response({'video_id':'333','upload_url':'https://attacker.example/upload'}))
    with pytest.raises(RuntimeError,match='trusted'): facebook_post(connectors,video,'Title','Caption')
