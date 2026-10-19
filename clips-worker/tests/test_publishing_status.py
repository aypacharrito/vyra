import json
from types import SimpleNamespace
import pytest
import publishing_status as publishing
import social


class Response:
    ok = True
    status_code = 200
    headers = {}
    def __init__(self, data): self.data = data
    def json(self): return self.data


def connect():
    return SimpleNamespace(token=lambda _: ('secret-for-test-only', {'channel_id':'mine','user_id':'123'}),
                           info=lambda: {'instagram': {'connected':True}})


def post(privacy='private'):
    return {'id':'post-1','platform':'youtube','status':'submitted','visibility':privacy,
            'remote_json':json.dumps({'id':'abcdefghijk','visibility':privacy})}


def test_status_refresh_reads_actual_privacy_and_processing_without_writes(monkeypatch):
    calls=[]
    def get(url, **kwargs):
        calls.append((url, kwargs['params']))
        return Response({'items':[{'id':'abcdefghijk','snippet':{'channelId':'mine'},
            'status':{'privacyStatus':'private','uploadStatus':'processed'},
            'processingDetails':{'processingStatus':'succeeded'}}]})
    monkeypatch.setattr(publishing.requests,'get',get)
    monkeypatch.setattr(publishing.requests,'post',lambda *a,**k:pytest.fail('Status checks must never upload'))
    monkeypatch.setattr(publishing.requests,'put',lambda *a,**k:pytest.fail('Status checks must never change privacy'))
    row=post('public')
    checked=publishing.youtube_checks(connect(),[row])['post-1']
    assert checked['state']=='private' and checked['verified']
    assert 'Requested public' in checked['visibility_note']
    assert calls[0][1]['part']=='snippet,status,processingDetails'
    view=publishing.delivery_view(row,checked)
    assert view['studio_url']=='https://studio.youtube.com/video/abcdefghijk/edit'
    assert 'secret-for-test-only' not in json.dumps(view)
    # Receipt-only data must not be presented as a verified/public upload.
    assert publishing.delivery_view(row)['state']=='accepted'


@pytest.mark.parametrize('upload,processing,privacy,state',[
    ('uploaded','processing','public','processing'),
    ('processed','succeeded','public','public'),
    ('processed','succeeded','unlisted','unlisted'),
    ('rejected',None,'private','failed'),
    ('failed','failed','private','failed'),
    ('deleted',None,None,'failed'),
])
def test_distinguishes_platform_outcomes(upload,processing,privacy,state):
    result=publishing.youtube_result({'status':{'uploadStatus':upload,'privacyStatus':privacy},
                                     'processingDetails':{'processingStatus':processing}},'private')
    assert result['state']==state


def test_other_channel_and_missing_receipts_are_not_verified(monkeypatch):
    monkeypatch.setattr(publishing.requests,'get',lambda *a,**k:Response({'items':[{
        'id':'abcdefghijk','snippet':{'channelId':'someone-else'},'status':{'privacyStatus':'public','uploadStatus':'processed'}}]}))
    result=publishing.youtube_checks(connect(),[post()])['post-1']
    assert not result['verified'] and 'Reconnect the channel' in result['message']
    malformed={**post(),'remote_json':'{"id": "https://evil.example/"}'}
    monkeypatch.setattr(publishing.requests,'get',lambda *a,**k:pytest.fail('Invalid receipts must not make API requests'))
    assert not publishing.youtube_checks(connect(),[malformed])['post-1']['verified']
    assert 'studio_url' not in publishing.delivery_view(malformed)


def test_instagram_requires_working_signin_and_upload_hosting(monkeypatch):
    for name in ('R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setattr(publishing.requests,'get',lambda *a,**k:Response({'id':'123','username':'test-creator'}))
    result=publishing.instagram_readiness(connect())
    assert result['verified'] and not result['ready'] and not result['hosting_ready']
    assert 'hosting' in result['message']
    class Rejected(Response):
        ok=False
        status_code=400
    monkeypatch.setattr(publishing.requests,'get',lambda *a,**k:Rejected({'error':{'code':190,'message':'secret-for-test-only'}}))
    result=publishing.instagram_readiness(connect())
    assert not result['ready'] and 'code 190' in result['message']
    assert 'secret-for-test-only' not in json.dumps(result)


def test_youtube_upload_requires_receipt_and_uses_returned_privacy(monkeypatch,tmp_path):
    video=tmp_path/'test.mp4';video.write_bytes(b'fake video fixture')
    initial=Response({});initial.headers={'Location':'https://www.googleapis.com/upload/test-session'}
    monkeypatch.setattr(social.requests,'post',lambda *a,**k:initial)
    monkeypatch.setattr(social.requests,'put',lambda *a,**k:Response({'id':'abcdefghijk','status':{'privacyStatus':'private','uploadStatus':'uploaded'}}))
    result=social.youtube_upload(connect(),video,'Title','Description','public')
    assert result['visibility']=='private' and result['requested_visibility']=='public'
    monkeypatch.setattr(social.requests,'put',lambda *a,**k:Response({}))
    with pytest.raises(RuntimeError,match='did not return a video ID'):
        social.youtube_upload(connect(),video,'Title','Description')
