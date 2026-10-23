"""Explicit local clip deletion, with durable retry for Windows file locks."""
import json
import re
from fastapi import HTTPException


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS manual_deletions (
        job_id TEXT NOT NULL, filename TEXT NOT NULL, requested_at TEXT NOT NULL,
        PRIMARY KEY(job_id, filename))''')


def valid(job, filename):
    return bool(re.fullmatch('[a-f0-9]{18}', job) and re.fullmatch(r'clip_\d{2}\.mp4', filename))


def finish(env):
    with env['database']() as conn:
        conn.execute('BEGIN IMMEDIATE')
        # Recover a request if the process ended between marking its manifest
        # and committing the queue transaction. The marker prevents new sends.
        for manifest in env['OUTPUT'].glob('*/manifest.json'):
            if manifest.parent.is_symlink() or manifest.is_symlink(): continue
            try: clips = json.loads(manifest.read_text('utf-8')).get('clips', [])
            except (OSError, ValueError): continue
            for clip in clips:
                job, filename = manifest.parent.name, str(clip.get('file', ''))
                if valid(job, filename) and clip.get('delete_requested_at'):
                    conn.execute('''INSERT OR IGNORE INTO manual_deletions
                        SELECT ?,?,? WHERE NOT EXISTS (SELECT 1 FROM clip_cleanup WHERE job_id=? AND filename=?)''',
                        (job, filename, clip['delete_requested_at'], job, filename))
        for row in conn.execute('SELECT * FROM manual_deletions').fetchall():
            job, filename = row['job_id'], row['filename']
            if not valid(job, filename): continue
            folder = env['OUTPUT'] / job
            if folder.is_symlink(): continue
            paths = [folder / filename, folder / (filename[:-4] + '.ass')]
            if any(p.is_symlink() for p in paths): continue
            try:
                size = sum(p.stat().st_size for p in paths if p.is_file())
                for path in paths: path.unlink(missing_ok=True)
            except OSError:
                continue
            conn.execute('INSERT OR IGNORE INTO clip_cleanup VALUES (?,?,?,?)', (job, filename, env['utc_now'](), size))
            conn.execute('DELETE FROM manual_deletions WHERE job_id=? AND filename=?', (job, filename))


def delete(env, job, filename):
    if not valid(job, filename): raise HTTPException(404, 'Clip not found.')
    folder = env['OUTPUT'] / job
    manifest = folder / 'manifest.json'
    if folder.is_symlink() or manifest.is_symlink() or not manifest.is_file():
        raise HTTPException(404, 'Clip not found.')
    with env['LOCK'], env['database']() as conn:
        conn.execute('BEGIN IMMEDIATE')
        value = json.loads(manifest.read_text('utf-8'))
        clip = next((c for c in value.get('clips', []) if c.get('file') == filename), None)
        if clip is None: raise HTTPException(404, 'Clip not found.')
        posts = conn.execute('SELECT * FROM postings WHERE job_id=? AND filename=?', (job, filename)).fetchall()
        if any(p['status'] == 'sending' for p in posts):
            raise HTTPException(409, 'This clip is being sent. Wait for submission to finish before deleting its local file.')
        drafts = conn.execute("SELECT * FROM drafts WHERE status IN ('draft','submitting','review_required')").fetchall()
        matches = [r for r in drafts if (lambda d: d.get('job_id') == job and d.get('filename') == filename)(json.loads(r['payload']))]
        if any(r['status'] == 'submitting' for r in matches):
            raise HTTPException(409, 'A draft for this clip is being submitted. Wait for it to finish.')
        # Stop queued work before hiding/removing the file. Existing posts stay online.
        conn.execute("UPDATE postings SET status='cancelled' WHERE job_id=? AND filename=? AND status='approved'", (job, filename))
        for post in posts:
            if post['platform'] != 'instagram' or post['status'] != 'submitted': continue
            saved = json.loads(post['remote_json'] or '{}')
            if saved.get('container_id') and saved.get('status') != 'published':
                conn.execute("UPDATE postings SET status='cancelled' WHERE id=? AND status='submitted'", (post['id'],))
        for row in matches:
            if row['status'] == 'draft': conn.execute("UPDATE drafts SET status='discarded' WHERE id=?", (row['id'],))
        requested = clip.get('delete_requested_at') or env['utc_now']()
        conn.execute('INSERT OR IGNORE INTO manual_deletions VALUES (?,?,?)', (job, filename, requested))
        # The manifest marker also excludes new drafts and sends during lock retries.
        clip['delete_requested_at'] = requested
        tmp = manifest.with_suffix('.delete.tmp')
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8'); tmp.replace(manifest)
    finish(env)
    with env['database']() as conn:
        pending = conn.execute('SELECT 1 FROM manual_deletions WHERE job_id=? AND filename=?', (job, filename)).fetchone()
    return {'deleted': not bool(pending), 'pending': bool(pending), 'job_id': job, 'filename': filename,
            'message': 'Close video playback; deletion will retry automatically.' if pending else 'Local clip deleted. Queued posts cancelled. Existing social posts stay online.'}
