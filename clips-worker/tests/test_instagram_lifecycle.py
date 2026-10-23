import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from test_queue import worker, seed_clip_and_account
from test_connections import connectors, Response
import instagram_storage as storage
import social
import publishing_status


def pending(worker, monkeypatch):
    body = seed_clip_and_account(worker, monkeypatch)
    monkeypatch.setattr(worker, 'instagram_readiness', lambda _: {'ready': True})
    post = worker.make_post({**body, 'platform': 'instagram', 'visibility': 'reels', 'confirm': True}, False)
    saved = {'container_id': '123', 'account_id': '456', 'status': 'processing'}
    monkeypatch.setattr(worker, 'handle_post', lambda _: saved)
    worker.deliver(post['id'])
    return body, post


def test_slow_instagram_processing_survives_polls_and_publishes_once(worker, monkeypatch):
    body, post = pending(worker, monkeypatch)
    calls = []
    monkeypatch.setattr(worker, 'instagram_container', lambda *_: 'IN_PROGRESS')
    monkeypatch.setattr(worker, 'instagram_publish', lambda *_: pytest.fail('Not processed yet'))
    worker.advance_instagram(); worker.advance_instagram()
    assert worker.read_posts()[0]['status'] == 'submitted'
    assert worker.clip_path(body['job_id'], body['filename']).exists()
    monkeypatch.setattr(worker, 'instagram_container', lambda *_: 'FINISHED')
    monkeypatch.setattr(worker, 'instagram_publish', lambda _, saved: calls.append(saved['container_id']) or {**saved, 'id': '999', 'status': 'published'})
    worker.advance_instagram(); worker.advance_instagram()
    assert calls == ['123']
    assert worker.queue()[0]['delivery']['state'] == 'published'
    assert worker.queue()[0]['local_copy'] == 'saved'


def test_unknown_publication_never_retries_or_deletes_local_file(worker, monkeypatch):
    body, _ = pending(worker, monkeypatch)
    calls = []
    monkeypatch.setattr(worker, 'instagram_container', lambda *_: 'FINISHED')
    def interrupted(*_): calls.append('publish'); raise RuntimeError('unknown outcome')
    monkeypatch.setattr(worker, 'instagram_publish', interrupted)
    worker.advance_instagram(); worker.advance_instagram()
    assert calls == ['publish']
    assert worker.read_posts()[0]['status'] == 'needs_review'
    assert worker.clip_path(body['job_id'], body['filename']).exists()


def test_two_container_workers_cannot_publish_a_stale_receipt(worker, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    pending(worker, monkeypatch)
    first_done = threading.Event()
    calls = []; polls = []
    original_store = worker.store_checks
    def store(results):
        original_store(results)
        if any(r.get('state') == 'published' for r in results.values()): first_done.set()
    monkeypatch.setattr(worker, 'store_checks', store)
    barrier = threading.Barrier(2)
    def check(*_):
        polls.append(threading.get_ident())
        first = len(polls) == 1
        barrier.wait(5)
        if not first: assert first_done.wait(5)
        return 'FINISHED'
    monkeypatch.setattr(worker, 'instagram_container', check)
    monkeypatch.setattr(worker, 'instagram_publish', lambda _, r: calls.append(r['container_id']) or {**r, 'id':'999', 'status':'published'})
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: worker.advance_instagram(), range(2)))
    assert calls == ['123']


def test_restart_keeps_processing_receipt_and_holds_interrupted_write(worker, monkeypatch):
    import importlib.util
    from pathlib import Path
    _, post = pending(worker, monkeypatch)
    def reopen():
        spec = importlib.util.spec_from_file_location('vyra_restart_test', Path(worker.__file__))
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module
    restarted = reopen()
    assert restarted.read_posts()[0]['status'] == 'submitted'
    assert json.loads(restarted.read_posts()[0]['remote_json'])['container_id'] == '123'
    with restarted.database() as conn:
        conn.execute("UPDATE postings SET status='sending' WHERE id=?", (post['id'],))
    interrupted = reopen()
    assert interrupted.read_posts()[0]['status'] == 'needs_review'
    monkeypatch.setattr(interrupted, 'instagram_publish', lambda *_: pytest.fail('Never retry an interrupted write'))
    interrupted.advance_instagram()


def test_staging_keeps_processing_files_and_retries_failed_delete(connectors, monkeypatch, tmp_path):
    for env in storage.FIELDS.values(): monkeypatch.delenv(env, raising=False)
    secret = 'private-storage-secret'
    storage.save(connectors.vault, {'account_id': 'a'*32, 'access_key_id': 'private-key', 'secret_access_key': secret, 'bucket': 'vyra-test'})
    deleted = []; should_fail = [True]
    class S3:
        def upload_file(self, *args, **kwargs): pass
        def generate_presigned_url(self, *args, **kwargs): return 'https://example.test/temporary-signed-video'
        def delete_object(self, **kwargs):
            if should_fail[0]: raise RuntimeError('offline')
            deleted.append(kwargs['Key'])
    monkeypatch.setattr(storage, 'client', lambda _: (S3(), 'vyra-test'))
    video = tmp_path/'clip.mp4'; video.write_bytes(b'video')
    key, _ = storage.stage(connectors.vault, video)
    storage.attach(connectors.vault, key, '123')
    storage.collect(connectors.vault)
    assert not deleted
    storage.collect(connectors.vault, {'123'})
    assert connectors.vault.get('_instagram_staging')
    should_fail[0] = False
    storage.collect(connectors.vault)
    assert deleted == [key] and not connectors.vault.get('_instagram_staging')
    assert secret not in json.dumps(storage.info(connectors.vault))
    assert secret.encode() not in connectors.vault.data_path.read_bytes()


def test_staging_expires_even_if_container_creation_was_interrupted(connectors, monkeypatch):
    key = 'vyra-publishing/' + 'a'*36 + '.mp4'
    connectors.vault.save('_instagram_staging', {key: {'bucket': 'test', 'created': time.time()-26*3600, 'container': ''}})
    calls=[]
    monkeypatch.setattr(storage, 'release', lambda _, key: calls.append(key))
    storage.collect(connectors.vault)
    assert calls == [key]


def test_pending_storage_allows_credentials_repair_but_not_bucket_move(connectors, monkeypatch):
    for env in storage.FIELDS.values(): monkeypatch.delenv(env, raising=False)
    config = {'account_id':'a'*32, 'bucket':'test-bucket', 'access_key_id':'key', 'secret_access_key':'wrong'}
    storage.save(connectors.vault, config)
    connectors.vault.save('_instagram_staging', {'pending': {'bucket': 'test-bucket'}})
    storage.save(connectors.vault, {'secret_access_key':'corrected'})
    assert storage.config(connectors.vault)['secret_access_key'] == 'corrected'
    with pytest.raises(ValueError, match='moving buckets'):
        storage.save(connectors.vault, {'bucket':'different-bucket'})


def test_instagram_stage_does_not_delete_before_meta_finishes(connectors, monkeypatch, tmp_path):
    monkeypatch.setattr(connectors, 'token', lambda _: ('private-token', {'user_id': '456'}))
    monkeypatch.setattr(storage, 'stage', lambda *_: ('key', 'https://example.test/temp-video'))
    attached=[]
    monkeypatch.setattr(storage, 'attach', lambda *args: attached.append(args[1:]))
    monkeypatch.setattr(storage, 'release', lambda *_: pytest.fail('Do not remove a processing upload'))
    monkeypatch.setattr(social.requests, 'post', lambda *_args, **_kwargs: Response({'id': '123'}))
    result = social.instagram_post(connectors, tmp_path/'video.mp4', 'Caption')
    assert result['status'] == 'processing' and result['container_id'] == '123'
    assert attached == [('key', '123')]


def test_expired_token_and_new_token_refresh_rules(connectors, monkeypatch):
    monkeypatch.setattr(social.requests, 'get', lambda *_a, **_k: pytest.fail('Cannot refresh a token younger than 24 hours'))
    connectors.vault.save('instagram', {'access_token': 'token', 'saved_at': time.time(), 'expires_in': 3600})
    assert connectors.token('instagram')[0] == 'token'
    connectors.vault.save('instagram', {'access_token': 'token', 'saved_at': time.time()-3601, 'expires_in': 3600})
    with pytest.raises(ValueError, match='expired'): connectors.token('instagram')


def test_reconnect_requests_instagram_login_and_requires_granted_publish_permission(connectors, monkeypatch):
    connectors.settings.save('instagram', {'client_id': '123', 'client_secret': 'secret', 'redirect_uri': 'https://vyra-five-lac.vercel.app/api/instagram-callback'})
    query = parse_qs(urlparse(connectors.start('instagram')).query)
    assert query['enable_fb_login'] == ['0'] and query['force_authentication'] == ['1']
    connectors.vault.save('instagram', {'access_token': 'previous'})
    monkeypatch.setattr(social.requests, 'post', lambda *_a, **_k: Response({'access_token': 'short', 'user_id': '456', 'permissions': ['instagram_business_basic']}))
    monkeypatch.setattr(social.requests, 'get', lambda *_a, **_k: Response({'access_token': 'long'}))
    with pytest.raises(ValueError, match='publishing permission'):
        connectors.finish('instagram', query['state'][0], 'code')
    assert connectors.vault.get('instagram')['access_token'] == 'previous'


def test_storage_api_authorized_encrypted_and_used_by_readiness(worker, monkeypatch):
    for name in storage.FIELDS.values(): monkeypatch.delenv(name, raising=False)
    body={'account_id': 'a'*32, 'access_key_id': 'private-key', 'secret_access_key': 'private-secret', 'bucket': 'vyra-test'}
    with TestClient(worker.app, base_url='http://127.0.0.1:8765') as client:
        assert client.put('/api/connections/instagram/storage', json=body).status_code == 403
        result=client.put('/api/connections/instagram/storage', json=body, headers={'x-vyra-csrf': worker.APP_TOKEN})
        assert result.status_code == 200 and result.json()['configured']
        assert 'private-secret' not in result.text
        assert client.get('/api/connections/instagram').json()['storage']['configured']
    monkeypatch.setattr(worker.CONNECT, 'token', lambda _: ('private-token', {'user_id':'456'}))
    monkeypatch.setattr(worker.CONNECT, 'info', lambda: {'instagram': {'connected': True}})
    monkeypatch.setattr(publishing_status.requests, 'get', lambda *_a, **_k: Response({'id':'456', 'username':'test'}))
    assert publishing_status.instagram_readiness(worker.CONNECT)['ready']


@pytest.mark.parametrize('state,expected', [('PROCESSING_UPLOAD','processing'), ('SEND_TO_USER_INBOX','processing'), ('PUBLISH_COMPLETE','published'), ('FAILED','failed')])
def test_tiktok_only_complete_publication_allows_cleanup(monkeypatch, state, expected):
    connect = SimpleNamespace(token=lambda _: ('token', {'open_id':'mine'}))
    row = {'id':'one', 'platform':'tiktok', 'status':'submitted', 'remote_json':json.dumps({'publish_id':'123','account_id':'mine'})}
    monkeypatch.setattr(publishing_status.requests, 'post', lambda *_a, **_k: Response({'data':{'status': state}, 'error':{'code':'ok'}}))
    assert publishing_status.destination_checks(connect, [row])['one']['state'] == expected


@pytest.mark.parametrize('published,status,expected', [(False,'ready','processing'), (True,'processing','processing'), (True,'ready','published'), (False,'error','failed')])
def test_facebook_acceptance_is_not_publication(monkeypatch, published, status, expected):
    connect = SimpleNamespace(token=lambda _: ('token', {'page_id':'123'}))
    row = {'id':'one', 'platform':'facebook', 'status':'submitted', 'remote_json':json.dumps({'id':'456','page_id':'123'})}
    monkeypatch.setattr(publishing_status.requests, 'get', lambda *_a, **_k: Response({'published':published, 'status':{'video_status':status}}))
    assert publishing_status.destination_checks(connect, [row])['one']['state'] == expected
