import json
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from test_queue import worker, seed_clip_and_account
import video_retention


def setup_post(worker, monkeypatch):
    body = seed_clip_and_account(worker, monkeypatch)
    (worker.OUTPUT / body['job_id'] / 'clip_01.ass').write_bytes(b'captions')
    post = worker.make_post({**body, 'confirm': True}, False)
    with worker.database() as conn:
        conn.execute("UPDATE postings SET status='submitted' WHERE id=?", (post['id'],))
    return body, post


def verify(worker, post):
    worker.store_checks({post['id']: {'verified': True, 'state': 'public', 'checked_at': worker.utc_now()}})


def sweep(worker, seconds=0):
    return video_retention.sweep(vars(worker), time.time() + seconds)


def test_confirmed_exports_removed_immediately_with_history_preserved(worker, monkeypatch, tmp_path):
    body, post = setup_post(worker, monkeypatch)
    video = worker.OUTPUT / body['job_id'] / body['filename']
    original = tmp_path / 'my-original.mp4'; original.write_bytes(b'original')
    other = video.with_name('clip_02.mp4'); other.write_bytes(b'unposted')
    assert not sweep(worker) and video.exists()  # Accepted is insufficient.
    verify(worker, post)
    # store_checks triggers cleanup immediately, without the old ten-minute timer.
    assert not video.exists()
    assert not video.exists() and not video.with_suffix('.ass').exists()
    assert original.exists() and other.exists() and (video.parent / 'manifest.json').exists()
    assert not sweep(worker)  # Idempotent, including after reopening the DB.
    assert worker.queue()[0]['local_copy'] == 'removed'
    assert worker.read_posts()[0]['status'] == 'submitted'
    assert worker.library() == []
    with pytest.raises(worker.HTTPException): worker.clip_path(body['job_id'], body['filename'])


@pytest.mark.parametrize('state', ['approved', 'sending', 'needs_review', 'submitted'])
def test_other_destination_still_needs_clip(worker, monkeypatch, state):
    body, first = setup_post(worker, monkeypatch)
    second = worker.make_post({**body, 'platform': 'facebook', 'visibility': 'reels', 'confirm': True}, False)
    with worker.database() as conn:
        conn.execute('UPDATE postings SET status=? WHERE id=?', (state, second['id']))
    verify(worker, first)
    assert not sweep(worker)
    assert worker.clip_path(body['job_id'], body['filename']).exists()
    if state == 'submitted':
        verify(worker, second)
        assert not (worker.OUTPUT / body['job_id'] / body['filename']).exists()


def test_cancelled_destination_does_not_block_but_draft_does(worker, monkeypatch):
    body, first = setup_post(worker, monkeypatch)
    second = worker.make_post({**body, 'platform': 'facebook', 'visibility': 'reels', 'confirm': True}, False)
    worker.cancel(second['id'])
    with worker.database() as conn:
        conn.execute('INSERT INTO drafts VALUES (?,?,1,?)', ('draft', json.dumps({**body, 'target': 'post'}), 'draft'))
    verify(worker, first)
    assert not sweep(worker)
    with worker.database() as conn:
        conn.execute("UPDATE drafts SET status='discarded'")
    assert sweep(worker) > 0


def test_confirmation_clock_does_not_reset_and_failed_check_keeps_file(worker, monkeypatch):
    body, post = setup_post(worker, monkeypatch)
    with worker.database() as conn:
        conn.execute('INSERT INTO drafts VALUES (?,?,1,?)', ('keep', json.dumps({**body,'target':'post'}), 'draft'))
    verify(worker, post)
    with worker.database() as conn:
        first = json.loads(conn.execute('SELECT result_json FROM publishing_checks').fetchone()[0])
    verify(worker, post)
    with worker.database() as conn:
        assert json.loads(conn.execute('SELECT result_json FROM publishing_checks').fetchone()[0])['confirmed_at'] == first['confirmed_at']
    worker.store_checks({post['id']: {'verified': True, 'state': 'failed'}})
    assert not sweep(worker)


def test_windows_busy_file_retries_without_losing_receipts(worker, monkeypatch):
    _, post = setup_post(worker, monkeypatch)
    from pathlib import Path
    original = Path.unlink
    def busy(path, *args, **kwargs):
        if path.suffix == '.mp4': raise PermissionError('Video still playing')
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', busy)
        verify(worker, post)
        assert not sweep(worker)
    assert sweep(worker) > 0
