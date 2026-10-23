"""Persistent queue spacing and single-upload claims; no AI or provider calls."""
from datetime import datetime, timedelta, timezone

GAP_SECONDS = 90 * 60


def initialize(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS delivery_slots (post_id TEXT PRIMARY KEY, platform TEXT NOT NULL, started_at TEXT NOT NULL)')


def stamp(value):
    try:
        date=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return date.astimezone(timezone.utc) if date.tzinfo else None
    except (ValueError,TypeError): return None


def occupied(conn, platform):
    rows=conn.execute('''SELECT p.scheduled_at, p.created_at, p.status, s.started_at FROM postings p
        LEFT JOIN delivery_slots s ON s.post_id=p.id
        WHERE p.platform=? AND p.status IN ('approved','sending','submitted','needs_review')''',(platform,))
    values=[]
    for row in rows:
        value=stamp(row['scheduled_at'] if row['status']=='approved' else row['started_at'] or row['scheduled_at'])
        if value: values.append(value)
    return values


def next_free(when, times):
    """Walk forward through occupied intervals, including reservations after when."""
    candidate=when.astimezone(timezone.utc)
    gap=timedelta(seconds=GAP_SECONDS)
    for other in sorted(times):
        if abs((other-candidate).total_seconds()) < GAP_SECONDS:
            candidate=other+gap
    return candidate


def claim(conn, post_id, now):
    """Caller holds BEGIN IMMEDIATE. Never starts two provider uploads together."""
    row=conn.execute('SELECT * FROM postings WHERE id=? AND status=\'approved\'',(post_id,)).fetchone()
    if not row: return None
    scheduled=stamp(row['scheduled_at'])
    if scheduled and scheduled>now+timedelta(seconds=1): return None
    # Other destinations can publish in the same window, but transfer one file at a time.
    if conn.execute("SELECT 1 FROM postings WHERE status='sending' LIMIT 1").fetchone(): return None
    last=conn.execute('SELECT started_at FROM delivery_slots WHERE platform=? ORDER BY started_at DESC LIMIT 1',(row['platform'],)).fetchone()
    latest=stamp(last['started_at']) if last else None
    if latest and (now-latest).total_seconds() < GAP_SECONDS:
        free=latest+timedelta(seconds=GAP_SECONDS)
        # Do not collide with another approved reservation when catching up after downtime.
        others=[stamp(r['scheduled_at']) for r in conn.execute("SELECT scheduled_at FROM postings WHERE platform=? AND status='approved' AND id<>?",(row['platform'],post_id))]
        free=next_free(free,[d for d in others if d and d>now])
        conn.execute("UPDATE postings SET scheduled_at=? WHERE id=? AND status='approved'",(free.isoformat(),post_id))
        return None
    cur=conn.execute("UPDATE postings SET status='sending' WHERE id=? AND status='approved'",(post_id,))
    if cur.rowcount!=1:return None
    conn.execute('INSERT OR REPLACE INTO delivery_slots VALUES (?,?,?)',(post_id,row['platform'],now.isoformat()))
    return dict(row)
