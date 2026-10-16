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


def test_concurrent_post_creation_prevents_duplicate(worker, monkeypatch, tmp_path):
    video = tmp_path / 'clip_01.mp4'
    video.write_bytes(b'test video')
    monkeypatch.setattr(worker, 'clip_path', lambda *args: video)
    monkeypatch.setattr(worker.CONNECT, 'info', lambda: {'youtube': {'connected': True}})
    body = {'platform': 'youtube', 'job_id': 'a' * 18, 'filename': video.name,
            'title': 'Test', 'caption': 'Test caption', 'visibility': 'private', 'confirm': True}

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
