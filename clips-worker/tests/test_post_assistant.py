import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from test_queue import worker, seed_clip_and_account
from test_connections import connectors, Response
import post_assistant as assistant
import instagram_storage
import social
import video_retention


def test_timing_uses_device_zone_future_windows_and_avoids_queue():
    now = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)
    first = assistant.choose_time('youtube', 'America/Los_Angeles', now=now)
    assert first['basis'] == 'starter_test_window'
    when = datetime.fromisoformat(first['scheduled_at'])
    assert when > now and when.astimezone(ZoneInfo('America/Los_Angeles')).hour in (12, 17, 19)
    second = assistant.choose_time('youtube', 'America/Los_Angeles', queued=[when.isoformat()], now=now)
    assert abs((datetime.fromisoformat(second['scheduled_at'])-when).total_seconds()) >= 5400
    with pytest.raises(ValueError, match='timezone'): assistant.choose_time('youtube', 'Invalid/Zone', now=now)


def test_account_results_inform_timing_only_with_sufficient_sample():
    now = datetime(2026, 10, 22, 9, tzinfo=timezone.utc)
    videos=[]
    for i in range(12):
        date=(now-timedelta(days=i+3)).replace(hour=19 if i%2 else 12)
        videos.append({'published_at':date.isoformat(),'lifetime':{'viewCount':10000 if i%2 else 100,'likeCount':20}})
    result=assistant.choose_time('youtube','UTC',{'videos':videos},now=now)
    assert result['basis']=='recent_account_results' and result['sample_size']==12
    assert datetime.fromisoformat(result['scheduled_at']).hour==19
    assert 'association' in result['reason']
    small=assistant.choose_time('youtube','UTC',{'videos':videos[:2]},now=now)
    assert small['basis']=='starter_test_window'


def test_prepare_is_authenticated_cached_and_does_not_publish(worker,monkeypatch):
    body=seed_clip_and_account(worker,monkeypatch)
    monkeypatch.setenv('OPENAI_API_KEY','fixture-key')
    calls=[]
    def copy(source,platform):
        calls.append(source)
        return {'title':'A clear hook','caption':'A concise description. #Topic','ai_generated':True,'reason':'Specific hook with a clear payoff.'}
    monkeypatch.setattr(assistant,'create_copy',copy)
    monkeypatch.setattr(worker,'handle_post',lambda *_:pytest.fail('Preparation cannot publish'))
    with TestClient(worker.app,base_url='http://127.0.0.1:8765') as client:
        headers={'x-vyra-csrf':worker.APP_TOKEN}
        assert client.post('/api/post-assistant',json=body).status_code==403
        result=client.post('/api/post-assistant',headers=headers,json={**body,'timezone':'America/Los_Angeles'})
        assert result.status_code==200 and result.json()['visibility']=='public'
        assert result.json()['title']=='A clear hook'
        assert calls[0]['transcript']=='Actual speech'
        assert client.post('/api/post-assistant',headers=headers,json=body).status_code==200
        assert len(calls)==1
        assert client.post('/api/post-assistant',headers=headers,json={**body,'regenerate':True}).status_code==400
        assert client.get('/api/queue').json()==[]


def test_failed_ai_keeps_original_and_never_claims_generated(worker,monkeypatch):
    body=seed_clip_and_account(worker,monkeypatch)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    result=assistant.prepare(vars(worker),{**body,'timezone':'UTC'})
    assert not result['ai_generated'] and result['caption']=='Original words'
    assert result['timing']['scheduled_at']


def test_structured_copy_has_no_tools_and_rejects_invented_numbers(monkeypatch):
    import openai
    calls=[]
    value={'variants':[{'title':'A surprising grocery challenge','caption':'Can they finish it? #Challenge'}], 'chosen':0,'reason':'Clear curiosity.'}
    def create(**kwargs): calls.append(kwargs);return SimpleNamespace(output_text=json.dumps(value))
    monkeypatch.setattr(openai,'OpenAI',lambda **_:SimpleNamespace(responses=SimpleNamespace(create=create)))
    result=assistant.create_copy({'transcript':'A grocery challenge.'},'youtube')
    assert result['ai_generated']
    assert 'tools' not in calls[0] and calls[0]['store'] is False
    assert 'untrusted' in calls[0]['instructions']
    assert calls[0]['text']['format']['type']=='json_schema'
    value['variants'][0]['caption']='It cost 999 dollars.'
    with pytest.raises(ValueError,match='numbers'): assistant.create_copy({'transcript':'A grocery challenge.'},'youtube')


def test_delete_cancels_queue_drafts_and_removes_only_selected_local_clip(worker,monkeypatch,tmp_path):
    body=seed_clip_and_account(worker,monkeypatch)
    original=tmp_path/'original.mp4';original.write_bytes(b'original')
    sibling=worker.OUTPUT/body['job_id']/'clip_02.mp4';sibling.write_bytes(b'other')
    worker.make_post({**body,'confirm':True},False)
    with TestClient(worker.app,base_url='http://127.0.0.1:8765') as client:
        path='/api/clips/'+body['job_id']+'/'+body['filename']
        headers={'x-vyra-csrf':worker.APP_TOKEN}
        draft=client.post('/api/intelligence/prepare_post',headers=headers,json=body).json()
        assert client.request('DELETE',path,json={'confirm':True}).status_code==403
        assert client.request('DELETE',path,headers=headers,json={}).status_code==400
        result=client.request('DELETE',path,headers=headers,json={'confirm':True})
        assert result.status_code==200 and result.json()['deleted']
        assert client.get('/api/drafts/'+draft['id']).json()['status']=='discarded'
        assert client.get('/api/queue').json()[0]['status']=='cancelled'
        assert client.get('/api/library').json()==[]
        assert client.get('/api/jobs/'+body['job_id']+'/files/'+body['filename']).status_code==404
    assert original.exists() and sibling.exists()


def test_delete_blocks_inflight_send_and_retries_windows_lock(worker,monkeypatch):
    from pathlib import Path
    import clip_deletion
    body=seed_clip_and_account(worker,monkeypatch)
    post=worker.make_post({**body,'confirm':True},False)
    with worker.database() as conn: conn.execute("UPDATE postings SET status='sending'")
    with pytest.raises(worker.HTTPException) as caught: clip_deletion.delete(vars(worker),body['job_id'],body['filename'])
    assert caught.value.status_code==409
    with worker.database() as conn: conn.execute("UPDATE postings SET status='approved'")
    unlink=Path.unlink
    def busy(path,*a,**k):
        if path.suffix=='.mp4':raise PermissionError('playing')
        return unlink(path,*a,**k)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'unlink',busy)
        result=clip_deletion.delete(vars(worker),body['job_id'],body['filename'])
        assert result['pending'] and worker.library()==[]
        with pytest.raises(worker.HTTPException): worker.make_post({**body,'confirm':True},False)
    clip_deletion.finish(vars(worker))
    assert not (worker.OUTPUT/body['job_id']/body['filename']).exists()


def test_public_mismatch_keeps_local_export():
    import publishing_status
    result=publishing_status.youtube_result({'status':{'privacyStatus':'private','uploadStatus':'processed'}},'public')
    assert result['visibility_mismatch'] and not video_retention.confirmed(result)


def test_instagram_diagnostic_stops_on_account_error_and_never_publishes(worker,monkeypatch):
    monkeypatch.setattr(worker,'instagram_readiness',lambda _: {'ready':False,'message':'Reconnect Instagram (code 190).'})
    monkeypatch.setattr(instagram_storage,'test',lambda *_:pytest.fail('No staging when sign-in fails'))
    with TestClient(worker.app,base_url='http://127.0.0.1:8765') as client:
        assert client.post('/api/connections/instagram/test').status_code==403
        result=client.post('/api/connections/instagram/test',headers={'x-vyra-csrf':worker.APP_TOKEN})
        assert not result.json()['ready'] and '190' in result.json()['message']


def test_signed_storage_probe_uses_range_get_and_never_exposes_signed_url(monkeypatch):
    calls=[]
    class Probe:
        status_code=206
        raw=io.BytesIO(b'0123456789abcdef')
        def __enter__(self):return self
        def __exit__(self,*_):pass
    monkeypatch.setattr(instagram_storage.requests,'get',lambda url,**k:calls.append(k) or Probe())
    instagram_storage.verify_url('https://test.example/?secret=do-not-echo',b'0123456789abcdef')
    assert calls[0]['headers']['Range']=='bytes=0-15' and calls[0]['allow_redirects'] is False
    Probe.status_code=403
    with pytest.raises(ValueError) as caught: instagram_storage.verify_url('https://test.example/?secret=do-not-echo',b'anything')
    assert 'do-not-echo' not in str(caught.value)


def test_instagram_errors_include_safe_codes_without_provider_text():
    class Error(Response): ok=False;status_code=400
    with pytest.raises(social.InstagramRequestError) as caught:
        social.instagram_check(Error({'error':{'code':100,'error_subcode':2207052,'message':'token=never-show'}}))
    assert '2207052' in str(caught.value) and 'never-show' not in str(caught.value)


def test_tiktok_upload_receipt_preserves_account_without_private_fallback(monkeypatch,tmp_path):
    import clip_engine
    video=tmp_path/'clip.mp4';video.write_bytes(b'video fixture')
    connect=SimpleNamespace(tiktok_options=lambda:{'privacy_level_options':['PUBLIC_TO_EVERYONE'],'max_video_post_duration_sec':60},
                            token=lambda _:('private-token',{'open_id':'my-account'}))
    monkeypatch.setattr(clip_engine,'probe',lambda _: {'duration':30})
    calls=[]
    def start(url,**kwargs):
        calls.append(kwargs)
        return Response({'data':{'publish_id':'receipt','upload_url':'https://open-upload.tiktokapis.com/upload'},'error':{'code':'ok'}})
    monkeypatch.setattr(social.requests,'post',start)
    monkeypatch.setattr(social.requests,'put',lambda *_a,**_k:Response({}))
    result=social.tiktok_post(connect,video,'Description.','PUBLIC_TO_EVERYONE')
    assert result['account_id']=='my-account'
    assert calls[0]['json']['post_info']['privacy_level']=='PUBLIC_TO_EVERYONE'
    assert calls[0]['json']['post_info']['disable_comment'] is True


def test_new_post_routes_reject_private_and_unlisted(worker,monkeypatch):
    body=seed_clip_and_account(worker,monkeypatch)
    for visibility in ('private','unlisted'):
        with pytest.raises(worker.HTTPException) as caught: worker.make_post({**body,'confirm':True,'visibility':visibility},False)
        assert caught.value.status_code==400
    with pytest.raises(worker.HTTPException): worker.make_post({**body,'platform':'tiktok','visibility':'SELF_ONLY','confirm':True},False)
    assert worker.read_posts()==[]
