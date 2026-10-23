import importlib.util
import json
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setenv('VYRA_CLIPS_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('VYRA_DISABLE_SCHEDULER', '1')
    source = Path(__file__).parents[1] / 'server.py'
    spec = importlib.util.spec_from_file_location('vyra_worker_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed(worker, status='approved'):
    row = {'id': 'post-one', 'job_id': 'a' * 18, 'filename': 'clip_01.mp4',
           'platform': 'youtube', 'title': 'Test', 'caption': 'Test caption',
           'visibility': 'private', 'scheduled_at': worker.utc_now(),
           'status': status, 'remote_json': None, 'error': None,
           'created_at': worker.utc_now()}
    with worker.database() as conn:
        conn.execute('INSERT INTO postings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', tuple(row.values()))
    return row


def seed_clip_and_account(worker, monkeypatch):
    job='b'*18
    folder=worker.OUTPUT/job;folder.mkdir()
    (folder/'clip_01.mp4').write_bytes(b'test video fixture')
    (folder/'manifest.json').write_text(json.dumps({'clips':[{'file':'clip_01.mp4','start':0,'end':30,'title':'Original','caption':'Original words'}]}),'utf-8')
    scratch=worker.WORK/job;scratch.mkdir()
    (scratch/'transcript.json').write_text(json.dumps([{'start':0,'end':1,'word':'Actual speech'}]),'utf-8')
    monkeypatch.setattr(worker.CONNECT,'info',lambda:{p:{'connected':True,'account':'Test channel'} for p in worker.VALID_PLATFORMS})
    return {'job_id':job,'filename':'clip_01.mp4','platform':'youtube','title':'Prepared title','caption':'Prepared description','visibility':'public','scheduled_at':''}


def test_intelligence_prepares_and_revises_without_publishing(worker,monkeypatch):
    body=seed_clip_and_account(worker,monkeypatch)
    monkeypatch.setattr(worker,'handle_post',lambda *_:pytest.fail('A draft must never publish'))
    with TestClient(worker.app,base_url='http://127.0.0.1:8765') as client:
        headers={'x-vyra-csrf':worker.APP_TOKEN}
        assert client.post('/api/intelligence/prepare_post',json=body).status_code==403
        response=client.post('/api/intelligence/prepare_post',headers=headers,json=body)
        assert response.status_code==200
        draft=response.json();assert draft['status']=='draft' and draft['revision']==1
        revision={**body,'id':draft['id'],'revision':1,'title':'Stronger title'}
        updated=client.post('/api/intelligence/update_draft',headers=headers,json=revision)
        assert updated.status_code==200 and updated.json()['revision']==2
        assert client.post('/api/intelligence/update_draft',headers=headers,json=revision).status_code==409
        assert client.post('/api/drafts/'+draft['id']+'/submit',headers=headers,json={'confirm':True,'revision':1}).status_code==409
        assert client.post('/api/drafts/'+draft['id']+'/submit',headers=headers,json={'confirm':False,'revision':2}).status_code==400
        assert client.get('/api/queue').json()==[]
        assert client.get('/api/drafts').json()[0]['title']=='Stronger title'


def test_youtube_defaults_public_and_rejects_new_private_drafts(worker,monkeypatch):
    body=seed_clip_and_account(worker,monkeypatch)
    body.pop('visibility')
    with TestClient(worker.app,base_url='http://127.0.0.1:8765') as client:
        headers={'x-vyra-csrf':worker.APP_TOKEN}
        public=client.post('/api/intelligence/prepare_post',headers=headers,json=body)
        assert public.status_code==200 and public.json()['visibility']=='public'
        private=client.post('/api/intelligence/prepare_post',headers=headers,json={**body,'visibility':'private'})
        assert private.status_code==400
        assert client.get('/api/queue').json()==[]
    prepared=worker.make_post({**body,'confirm':True},False)
    assert prepared['visibility']=='public' and prepared['status']=='approved'


def test_draft_is_bound_to_account_and_claimed_once(worker,monkeypatch):
    body=seed_clip_and_account(worker,monkeypatch)
    submissions=[]
    with TestClient(worker.app,base_url='http://127.0.0.1:8765') as client:
        headers={'x-vyra-csrf':worker.APP_TOKEN}
        draft=client.post('/api/intelligence/prepare_post',headers=headers,json=body).json()
        monkeypatch.setattr(worker,'make_post',lambda *args:submissions.append(args) or {'id':'accepted-once'})
        monkeypatch.setattr(worker,'deliver',lambda *_:None)
        payload={'confirm':True,'revision':1};path='/api/drafts/'+draft['id']+'/submit'
        assert client.post(path,headers=headers,json=payload).status_code==200
        assert client.post(path,headers=headers,json=payload).status_code==409
        assert len(submissions)==1
        second=client.post('/api/intelligence/prepare_post',headers=headers,json=body).json()
        monkeypatch.setattr(worker.CONNECT,'info',lambda:{p:{'connected':True,'account':'Different channel'} for p in worker.VALID_PLATFORMS})
        assert client.post('/api/drafts/'+second['id']+'/submit',headers=headers,json=payload).status_code==409
        assert len(submissions)==1


def test_clip_actions_use_real_transcript_and_reject_paths(worker,monkeypatch):
    body=seed_clip_and_account(worker,monkeypatch)
    with TestClient(worker.app,base_url='http://127.0.0.1:8765') as client:
        headers={'x-vyra-csrf':worker.APP_TOKEN}
        read=client.post('/api/intelligence/read_clip',headers=headers,json=body)
        assert read.json()['transcript']=='Actual speech'
        saved=client.post('/api/intelligence/update_clip',headers=headers,json={**body,'hook':'Real hook'})
        assert saved.status_code==200
        assert client.get('/api/library').json()[0]['clips'][0]['title']=='Prepared title'
        assert client.post('/api/intelligence/read_clip',headers=headers,json={**body,'job_id':'../../.local'}).status_code==404
        assert client.post('/api/intelligence/publish',headers=headers,json={**body,'confirm':True}).status_code==404


def test_two_delivery_threads_only_submit_once(worker, monkeypatch):
    seed(worker)
    calls = []
    entered, finish = threading.Event(), threading.Event()

    def post(row):
        calls.append(row['id'])
        entered.set()
        assert finish.wait(5)
        return {'id': 'remote-test'}

    monkeypatch.setattr(worker, 'handle_post', post)
    first = threading.Thread(target=worker.deliver, args=('post-one',))
    first.start()
    assert entered.wait(5)
    worker.deliver('post-one')
    finish.set()
    first.join(5)
    assert calls == ['post-one']
    assert worker.read_posts()[0]['status'] == 'submitted'


def test_failed_delivery_is_not_retried(worker, monkeypatch):
    seed(worker)
    calls = []

    def fail(row):
        calls.append(row['id'])
        raise RuntimeError('Unknown remote outcome')

    monkeypatch.setattr(worker, 'handle_post', fail)
    worker.deliver('post-one')
    worker.deliver('post-one')
    assert calls == ['post-one']
    assert worker.read_posts()[0]['status'] == 'needs_review'


def test_refresh_status_is_protected_and_preserves_submission(worker,monkeypatch):
    row=seed(worker,'submitted')
    with worker.database() as conn:
        conn.execute('UPDATE postings SET remote_json=? WHERE id=?',(json.dumps({'id':'abcdefghijk'}),row['id']))
    calls=[]
    monkeypatch.setattr(worker,'youtube_checks',lambda *_:calls.append('read') or {row['id']:{'state':'private','label':'Uploaded · Private','verified':True}})
    monkeypatch.setattr(worker,'instagram_readiness',lambda *_:{'ready':False,'verified':False,'message':'Reconnect Instagram.'})
    monkeypatch.setattr(worker,'handle_post',lambda *_:pytest.fail('Refresh must never send a post'))
    with TestClient(worker.app,base_url='http://127.0.0.1:8765') as client:
        assert client.post('/api/publishing/refresh').status_code==403
        headers={'x-vyra-csrf':worker.APP_TOKEN}
        assert client.post('/api/publishing/refresh',headers=headers).status_code==200
        assert client.post('/api/publishing/refresh',headers=headers).json()['cached']
        result=client.get('/api/queue').json()[0]
        assert result['status']=='submitted' and result['visibility']=='private'
        assert result['delivery']['state']=='private' and '/abcdefghijk/edit' in result['delivery']['studio_url']
    assert calls==['read']


def test_blocked_instagram_draft_stays_editable_and_sends_nothing(worker,monkeypatch):
    body=seed_clip_and_account(worker,monkeypatch)
    body.update(platform='instagram',visibility='reels')
    monkeypatch.setattr(worker,'instagram_readiness',lambda *_:{'ready':False,'verified':False,'message':'Reconnect Instagram (code 190).','setup_message':'Upload hosting is missing.'})
    monkeypatch.setattr(worker,'handle_post',lambda *_:pytest.fail('Blocked Instagram must not publish'))
    with TestClient(worker.app,base_url='http://127.0.0.1:8765') as client:
        headers={'x-vyra-csrf':worker.APP_TOKEN}
        draft=client.post('/api/intelligence/prepare_post',headers=headers,json=body).json()
        result=client.post('/api/drafts/'+draft['id']+'/submit',headers=headers,json={'confirm':True,'revision':1})
        assert result.status_code==400 and 'No post was sent' in result.json()['detail']
        assert client.get('/api/drafts/'+draft['id']).json()['status']=='draft'
        assert client.get('/api/queue').json()==[]


def test_concurrent_post_creation_prevents_duplicate(worker, monkeypatch, tmp_path):
    video = tmp_path / 'clip_01.mp4'
    video.write_bytes(b'test video')
    monkeypatch.setattr(worker, 'clip_path', lambda *args: video)
    monkeypatch.setattr(worker.CONNECT, 'info', lambda: {'youtube': {'connected': True}})
    body = {'platform': 'youtube', 'job_id': 'a' * 18, 'filename': video.name,
            'title': 'Test', 'caption': 'Test caption', 'visibility': 'public', 'confirm': True}

    def create():
        try:
            return worker.make_post(body, False)['id']
        except worker.HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert 409 in results
    assert len(worker.read_posts()) == 1


def test_local_write_requires_session_and_origin(worker):
    client = TestClient(worker.app, base_url='http://127.0.0.1:8765')
    assert client.post('/api/queue/missing/cancel').status_code == 403
    assert client.post('/api/queue/missing/cancel', headers={
        'x-vyra-csrf': worker.APP_TOKEN, 'origin': 'https://foreign.example'
    }).status_code == 403
    assert client.post('/api/queue/missing/cancel', headers={
        'x-vyra-csrf': worker.APP_TOKEN
    }).status_code == 409


def test_connection_wizard_saves_privately_and_requires_local_session(worker):
    client=TestClient(worker.app,base_url='http://127.0.0.1:8765')
    body={'credential_json':json.dumps({'installed':{'client_id':'123-test.apps.googleusercontent.com','client_secret':'private-local-secret'}})}
    assert client.put('/api/connections/youtube',json=body).status_code == 403
    saved=client.put('/api/connections/youtube',json=body,headers={'x-vyra-csrf':worker.APP_TOKEN})
    assert saved.status_code == 200
    assert saved.json()['configured']
    assert 'private-local-secret' not in saved.text
    assert 'private-local-secret' not in client.get('/api/status').text
    started=client.post('/api/oauth/youtube/start',json={},headers={'x-vyra-csrf':worker.APP_TOKEN})
    assert started.status_code == 200 and 'code_challenge=' in started.json()['url']
    assert 'private-local-secret' not in started.text
    oversized=client.put('/api/connections/youtube',content='a'*32769,headers={'x-vyra-csrf':worker.APP_TOKEN})
    assert oversized.status_code == 413


def test_callback_errors_never_reflect_credential_urls(worker,monkeypatch):
    def fail(*args): raise RuntimeError('https://provider.example?client_secret=private-secret')
    monkeypatch.setattr(worker.CONNECT,'finish',fail)
    client=TestClient(worker.app,base_url='http://127.0.0.1:8765',follow_redirects=False)
    response=client.get('/api/oauth/facebook/callback?state=test&code=test')
    assert response.status_code == 302
    assert 'private-secret' not in response.headers['location']


def test_cancelled_post_cannot_start(worker, monkeypatch):
    seed(worker, 'cancelled')
    monkeypatch.setattr(worker, 'handle_post', lambda row: pytest.fail('Cancelled post sent'))
    worker.deliver('post-one')
    assert worker.read_posts()[0]['status'] == 'cancelled'


def test_studio_can_only_be_framed_by_local_vyra(worker):
    client = TestClient(worker.app, base_url='http://127.0.0.1:8765')
    response = client.get('/')
    assert response.status_code == 200
    assert response.headers['content-security-policy'] == "frame-ancestors 'self' http://127.0.0.1:48791 http://localhost:48791"
    assert '__VYRA_CSRF_VALUE__' not in response.text
    assert client.post('/api/oauth/youtube/start', json={}, headers={
        'Origin': 'http://evil.example', 'x-vyra-csrf': worker.APP_TOKEN}).status_code == 403


def test_missing_engine_stops_before_accepting_source(worker,monkeypatch):
    monkeypatch.setattr(worker,'media_status',lambda:{'ready':False,'message':'Repair video tools'})
    client=TestClient(worker.app,base_url='http://127.0.0.1:8765')
    result=client.post('/api/jobs',files={'file':('source.mp4',b'source','video/mp4')},headers={'x-vyra-csrf':worker.APP_TOKEN})
    assert result.status_code==503
    assert not worker.JOBS and not list(worker.WORK.iterdir())


def test_processing_failure_keeps_uploaded_source(worker,monkeypatch):
    source=worker.WORK/('a'*18+'.mp4');source.write_bytes(b'source')
    worker.JOBS['a'*18]={'status':'processing'}
    def fail(*args):raise RuntimeError('Try again')
    monkeypatch.setattr(worker,'process_video',fail)
    worker.do_job('a'*18,source,1,20,60)
    assert source.exists() and worker.JOBS['a'*18]['status']=='error'
