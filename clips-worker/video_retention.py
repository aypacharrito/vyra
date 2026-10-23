"""Delete only app-owned exports with confirmed delivery and no remaining uses."""
import json
import re
import time
from datetime import datetime

GRACE_SECONDS = 600  # Time to queue another destination or download a copy.


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS clip_cleanup (
        job_id TEXT NOT NULL, filename TEXT NOT NULL, deleted_at TEXT NOT NULL,
        freed_bytes INTEGER NOT NULL, PRIMARY KEY(job_id, filename))''')


def confirmed(result):
    return result.get('verified') is True and not result.get('visibility_mismatch') and result.get('state') in (
        'public', 'private', 'unlisted', 'published')


def sweep(env, clock=None):
    """The SQLite write lock excludes new queue/draft references during deletion.

    Manifests and receipts stay for history. Only the matching MP4 and its own
    generated ASS are removed; original user files are never traversed.
    Missing files on a retry are safe after a crash between unlink and commit.
    """
    clock = time.time() if clock is None else clock
    freed = 0
    with env['database']() as conn:
        conn.execute('BEGIN IMMEDIATE')
        rows = [dict(r) for r in conn.execute("SELECT * FROM postings WHERE status != 'cancelled'")]
        checks = {r['post_id']: json.loads(r['result_json'])
                  for r in conn.execute('SELECT * FROM publishing_checks')}
        drafts = [json.loads(r['payload']) for r in conn.execute(
            "SELECT payload FROM drafts WHERE status IN ('draft','submitting','review_required')")]
        groups = {}
        for row in rows:
            groups.setdefault((row['job_id'], row['filename']), []).append(row)
        for (job, filename), posts in groups.items():
            if not re.fullmatch('[a-f0-9]{18}', job) or not re.fullmatch(r'clip_\d{2}\.mp4', filename):
                continue
            if any(p['status'] != 'submitted' or not confirmed(checks.get(p['id'], {})) for p in posts):
                continue
            try:
                latest = max(datetime.fromisoformat(checks[p['id']]['confirmed_at']).timestamp() for p in posts)
            except (KeyError, ValueError, TypeError):
                continue
            if clock - latest < GRACE_SECONDS:
                continue
            if any(d.get('target') == 'post' and d.get('job_id') == job and d.get('filename') == filename for d in drafts):
                continue
            if conn.execute('SELECT 1 FROM clip_cleanup WHERE job_id=? AND filename=?', (job, filename)).fetchone():
                continue
            folder = env['OUTPUT'] / job
            manifest = folder / 'manifest.json'
            if folder.is_symlink() or manifest.is_symlink() or not manifest.is_file():
                continue
            try:
                clips = json.loads(manifest.read_text('utf-8')).get('clips', [])
                if not any(c.get('file') == filename for c in clips):
                    continue
                paths = [folder / filename, folder / (filename[:-4] + '.ass')]
                if any(p.is_symlink() for p in paths):
                    continue
                size = sum(p.stat().st_size for p in paths if p.is_file())
                for path in paths:
                    path.unlink(missing_ok=True)
                conn.execute('INSERT INTO clip_cleanup VALUES (?,?,?,?)',
                             (job, filename, env['utc_now'](), size))
                freed += size
            except (OSError, ValueError, TypeError):
                # Windows may still hold a video open. Retry on the next pass.
                continue
    return freed
