"""VYRA Clips: loopback-only video worker, account connections, review-first publishing."""
from __future__ import annotations
from contextlib import contextmanager
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool
from clip_engine import process_video
from media_tools import media_status
from desktop_connection import refresh_desktop_connection
from social import Connectors, Vault, VALID_PLATFORMS, facebook_post, instagram_post, instagram_container, instagram_publish, tiktok_post, youtube_upload
from publishing_status import delivery_view, instagram_readiness, youtube_checks, destination_checks, receipt
import video_retention
import instagram_storage
import post_assistant
import clip_deletion
import source_discovery
import posting_schedule

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')
DATA = Path(os.getenv('VYRA_CLIPS_DATA_DIR') or str(BASE))
DATA.mkdir(parents=True, exist_ok=True)
WORK = DATA / 'work'
OUTPUT = DATA / 'output'
LOCAL = DATA / '.local'
for folder in (WORK, OUTPUT, LOCAL):
    folder.mkdir(exist_ok=True)
VAULT = Vault(LOCAL)
CONNECT = Connectors(VAULT)
DB = LOCAL / 'queue.sqlite3'
APP_TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
PUBLISHING_LOCK = threading.Lock()
PUBLISHING_HEALTH = {}
CONNECTION_EVENTS = {}
LAST_PUBLISHING_CHECK = 0.0
LAST_MAINTENANCE = 0.0
JOBS: dict[str,dict] = {}
ALLOWED = {'.mp4','.mov','.mkv','.webm'}
NAME = re.compile(r'^clip_\d{2}\.mp4$')
app = FastAPI(title='VYRA Clips / Local', docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])


@contextmanager
def database():
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE IF NOT EXISTS postings (
        id TEXT PRIMARY KEY, job_id TEXT NOT NULL, filename TEXT NOT NULL,
        platform TEXT NOT NULL, title TEXT NOT NULL, caption TEXT NOT NULL,
        visibility TEXT NOT NULL, scheduled_at TEXT NOT NULL,
        status TEXT NOT NULL, remote_json TEXT, error TEXT,
        created_at TEXT NOT NULL)''')
    conn.commit()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

with database() as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS publishing_checks (post_id TEXT PRIMARY KEY, result_json TEXT NOT NULL)')
    video_retention.initialize(conn)
    post_assistant.initialize(conn)
    clip_deletion.initialize(conn)
    source_discovery.initialize(conn)
    posting_schedule.initialize(conn)
    # A previous process may have ended after the provider accepted an upload.
    # Keep it for review instead of duplicating the submission after restart.
    conn.execute("UPDATE postings SET status='needs_review', error='Worker closed during submission. Check the platform before trying again.' WHERE status='sending'")
    conn.commit()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_posts(limit=200):
    with database() as conn:
        sql = 'SELECT * FROM postings ORDER BY scheduled_at DESC'
        return [dict(r) for r in conn.execute(sql + (' LIMIT ?' if limit else ''), (limit,) if limit else ()).fetchall()]


def store_checks(results):
    with database() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for post_id, result in results.items():
            before = conn.execute('SELECT result_json FROM publishing_checks WHERE post_id=?', (post_id,)).fetchone()
            old = json.loads(before['result_json']) if before else {}
            result = dict(result)
            if video_retention.confirmed(result):
                result['confirmed_at'] = old.get('confirmed_at') or utc_now()
            conn.execute('INSERT OR REPLACE INTO publishing_checks VALUES (?,?)', (post_id, json.dumps(result)))
    video_retention.sweep(globals())


def pending_verification():
    with database() as conn:
        checks = {r['post_id']: json.loads(r['result_json']) for r in conn.execute('SELECT * FROM publishing_checks')}
    rows = [r for r in read_posts(None) if r['status'] == 'submitted' and not video_retention.confirmed(checks.get(r['id'], {}))]
    return sorted(rows, key=lambda r: checks.get(r['id'], {}).get('checked_at', ''))


def publishing_accounts():
    accounts = CONNECT.info()
    for platform, event in CONNECTION_EVENTS.copy().items():
        accounts[platform]['last_connection_attempt'] = event
    for platform, health in PUBLISHING_HEALTH.copy().items():
        if accounts[platform]['connected'] and health['identity'] == accounts[platform].get('account'):
            accounts[platform]['publishing'] = health['result']
    return accounts


def refresh_publishing():
    global LAST_PUBLISHING_CHECK
    # Refreshes never call upload or visibility-update paths. Concurrent
    # browser windows share one bounded check instead of consuming API quota.
    with PUBLISHING_LOCK:
        if time.monotonic() - LAST_PUBLISHING_CHECK < 30:
            return {'platforms': publishing_accounts(), 'cached': True}
        rows = pending_verification()
        store_checks({**youtube_checks(CONNECT, rows), **destination_checks(CONNECT, rows)})
        identity = CONNECT.info()['instagram'].get('account')
        health = instagram_readiness(CONNECT)
        PUBLISHING_HEALTH['instagram'] = {'identity': identity, 'result': health}
        LAST_PUBLISHING_CHECK = time.monotonic()
    return {'platforms': publishing_accounts(), 'cached': False}


def advance_instagram():
    """Complete an already-approved container. Claim once before media_publish."""
    finished = set()
    for row in read_posts(None):
        if row['platform'] != 'instagram': continue
        saved = receipt(row)
        container = saved.get('container_id')
        if not container: continue
        if saved.get('status') == 'published':
            finished.add(container)
            continue
        if row['status'] != 'submitted': continue
        try:
            checked = instagram_container(CONNECT, saved)
            state = checked.get('state') if isinstance(checked, dict) else checked
        except Exception as exc:
            # Polling is read-only and can safely resume after a temporary failure.
            store_checks({row['id']: {'verified': False, 'state': 'unavailable', 'checked_at': utc_now(),
                'label': 'Instagram status unavailable', 'message': str(exc)[:240] if isinstance(exc, ValueError) else 'Reconnect Instagram and check again. Local clip preserved.'}})
            continue
        if state in ('ERROR', 'EXPIRED'):
            finished.add(container)
            with database() as conn:
                conn.execute("UPDATE postings SET status='needs_review', error=? WHERE id=? AND status='submitted'",
                    ((checked.get('message') if isinstance(checked, dict) else 'Instagram could not process this Reel. Your local clip is preserved; review the video and connection settings.'), row['id']))
            continue
        if state not in ('FINISHED', 'PUBLISHED'):
            store_checks({row['id']: {'verified': True, 'state': 'processing', 'checked_at': utc_now(),
                'label': 'Instagram processing', 'message': 'Waiting for Instagram to finish. No second upload will be created.'}})
            continue
        # Meta has fetched the file; staging is no longer needed.
        finished.add(container)
        if state == 'PUBLISHED':
            store_checks({row['id']: {'verified': True, 'state': 'published', 'checked_at': utc_now(),
                'label': 'Published · Confirmed', 'message': 'Instagram confirmed this container is published.'}})
            continue
        with database() as conn:
            claim = conn.execute("UPDATE postings SET status='sending' WHERE id=? AND status='submitted' AND remote_json=?",
                (row['id'], row['remote_json']))
            if claim.rowcount != 1: continue
        try:
            result = instagram_publish(CONNECT, saved)
            with database() as conn:
                conn.execute("UPDATE postings SET status='submitted', remote_json=?, error=NULL WHERE id=?",
                    (json.dumps(result), row['id']))
            store_checks({row['id']: {'verified': True, 'state': 'published', 'checked_at': utc_now(),
                'label': 'Published · Confirmed', 'message': 'Instagram confirmed Reel publication.'}})
        except Exception:
            with database() as conn:
                conn.execute("UPDATE postings SET status='needs_review', error=? WHERE id=?",
                    ('Instagram publication was not confirmed. Check the account before retrying; no automatic duplicate will be sent.', row['id']))
    instagram_storage.collect(VAULT, finished)


def maintenance():
    global LAST_MAINTENANCE
    with PUBLISHING_LOCK:
        if time.monotonic() - LAST_MAINTENANCE < 60: return
        advance_instagram()
        rows = pending_verification()
        store_checks({**youtube_checks(CONNECT, rows), **destination_checks(CONNECT, rows)})
        video_retention.sweep(globals())
        clip_deletion.finish(globals())
        LAST_MAINTENANCE = time.monotonic()


def progress(job_id, message, pct):
    with LOCK:
        JOBS[job_id].update(message=message, progress=pct)


def do_job(job_id, source, count, minimum, maximum):
    try:
        progress(job_id,'Transcribing and selecting',7)
        result=process_video(source, WORK/job_id, OUTPUT/job_id,count,minimum,maximum,
                             lambda msg,pct:progress(job_id,msg,pct))
        with LOCK:
            JOBS[job_id].update(status='done',result=result,progress=100,message='Ready to review')
    except Exception as exc:
        with LOCK:
            JOBS[job_id].update(status='error',message=str(exc)[:500],progress=0)
    else:
        source.unlink(missing_ok=True)


def clip_path(job_id, filename):
    if not re.fullmatch('[a-f0-9]{18}',job_id) or not NAME.fullmatch(filename):
        raise HTTPException(404,'Clip not found')
    path=OUTPUT/job_id/filename
    if not path.is_file() or not (OUTPUT/job_id/'manifest.json').exists():
        raise HTTPException(404,'Clip not found')
    manifest=json.loads((OUTPUT/job_id/'manifest.json').read_text('utf-8'))
    if not any(c.get('file')==filename and not c.get('delete_requested_at') for c in manifest.get('clips',[])):
        raise HTTPException(404,'Clip not found')
    return path


def handle_post(row):
    video=clip_path(row['job_id'],row['filename'])
    if row['platform']=='youtube':
        return youtube_upload(CONNECT,video,row['title'],row['caption'],row['visibility'])
    if row['platform']=='instagram':
        return instagram_post(CONNECT,video,row['caption'])
    if row['platform']=='facebook':
        return facebook_post(CONNECT,video,row['title'],row['caption'])
    if row['platform']=='tiktok':
        return tiktok_post(CONNECT,video,row['caption'],row['visibility'])
    raise ValueError('Unknown destination')


def deliver(post_id):
    with database() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=posting_schedule.claim(conn,post_id,datetime.now(timezone.utc))
        if not row: return
        conn.commit()
    try:
        response=handle_post(dict(row))
        with database() as conn:
            conn.execute('UPDATE postings SET status=?,remote_json=? WHERE id=?',
                         ('submitted',json.dumps(response),post_id))
            conn.commit()
        try: maintenance()
        except Exception: pass
    except Exception as exc:
        with database() as conn:
            # No retries automatically: avoid duplicate publication if network
            # fails after the provider accepted the clip.
            conn.execute('UPDATE postings SET status=?,error=? WHERE id=?',
                         ('needs_review',str(exc)[:400],post_id))
            conn.commit()


def worker():
    while True:
        try:
            with database() as conn:
                now=utc_now()
                ready=conn.execute("SELECT id FROM postings WHERE status='approved' AND scheduled_at<=? ORDER BY scheduled_at LIMIT 1",(now,)).fetchone()
            if ready:
                deliver(ready['id'])
            maintenance()
        except Exception:
            pass
        time.sleep(12)




@app.middleware('http')
async def local_only_security(req: Request, next_call):
    # Prevent a malicious web page from submitting local state changes via CSRF.
    if req.method in ('POST','PUT','DELETE','PATCH'):
        origin=req.headers.get('origin')
        if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765'):
            return HTMLResponse('Foreign origin blocked',status_code=403)
        if req.headers.get('x-vyra-csrf') != APP_TOKEN:
            return HTMLResponse('Missing local session authorization',status_code=403)
    if req.method=='POST' and req.url.path=='/api/jobs' and not media_status()['ready']:
        return JSONResponse({'detail':media_status()['message']},status_code=503)
    result=await next_call(req)
    result.headers['X-Content-Type-Options']='nosniff'
    result.headers['Referrer-Policy']='no-referrer'
    result.headers['Cache-Control']='no-store'
    result.headers['Content-Security-Policy']="frame-ancestors 'self' http://127.0.0.1:48791 http://localhost:48791"
    return result


@app.get('/',response_class=HTMLResponse)
def homepage():
    source=(BASE/'static'/'index.html').read_text('utf-8')
    return source.replace('__VYRA_CSRF_VALUE__',APP_TOKEN)


@app.get('/assets/{name}')
def asset(name:str):
    allowed={'connections.js':'text/javascript', 'intelligence.js':'text/javascript', 'post-assistant.js':'text/javascript', 'discovery.js':'text/javascript', 'studio.css':'text/css', 'studio.js':'text/javascript', 'icon.svg':'image/svg+xml', 'favicon.ico':'image/x-icon'}
    if name not in allowed: raise HTTPException(404, 'Asset not found')
    return FileResponse(BASE/'static'/name, media_type=allowed[name])


@app.get('/api/status')
def status():
    refresh_desktop_connection()
    return {'version':'0.6.5','ready':bool(os.getenv('OPENAI_API_KEY')),
            'platforms':publishing_accounts(), 'media':media_status(), 'render_engine':'FFmpeg','post_safety':'consent per destination'}


@app.get('/api/discovery')
def discovery_status():
    return source_discovery.latest(globals())


@app.post('/api/discovery/settings')
async def discovery_settings(req: Request):
    try: return source_discovery.save_settings(globals(), await req.json())
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@app.post('/api/discovery/scan')
async def discovery_scan():
    try: return await run_in_threadpool(source_discovery.scan, globals())
    except ValueError as exc: raise HTTPException(400, str(exc)) from None
    except Exception: raise HTTPException(502, 'Discovery service unavailable. Check the source connection and try later.') from None


def do_source_job(job_id, url, count, minimum, maximum):
    folder=WORK/(job_id+'-import')
    try:
        progress(job_id,'Downloading public source (up to two hours / 2 GB)',2)
        source=source_discovery.download(url,folder)
        do_job(job_id,source,count,minimum,maximum)
        if JOBS[job_id]['status']=='done':
            manifest=OUTPUT/job_id/'manifest.json'
            data=json.loads(manifest.read_text('utf-8'))
            data['source']={'url':url,'imported_at':utc_now(),'pattern_version':1}
            manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
    except Exception as exc:
        with LOCK: JOBS[job_id].update(status='error',message=str(exc)[:500],progress=0)
    finally:
        import shutil
        shutil.rmtree(folder,ignore_errors=True)
        if JOBS[job_id]['status']=='error':
            with database() as conn: conn.execute('DELETE FROM source_imports WHERE url=? AND job_id=?',(url,job_id))


@app.post('/api/sources/import')
async def import_source(req: Request):
    body=await req.json()
    if body.get('authorized') is not True: raise HTTPException(400,'Confirm you own or have permission to reuse this source.')
    try:
        url=source_discovery.canonical_url(body.get('url'))
        count=max(1,min(int(body.get('count',5)),12))
        minimum=max(12,min(int(body.get('min_seconds',20)),120))
        maximum=max(minimum,min(int(body.get('max_seconds',60)),180))
    except (ValueError,TypeError) as exc: raise HTTPException(400,str(exc)) from None
    refresh_desktop_connection()
    if not media_status()['ready']: raise HTTPException(503,media_status()['message'])
    if not os.getenv('OPENAI_API_KEY'): raise HTTPException(503,'Connect OpenAI in Settings & connections first.')
    job_id=uuid.uuid4().hex[:18]
    with LOCK:
        if any(j.get('status')=='processing' for j in JOBS.values()): raise HTTPException(429,'Local video worker already busy.')
        with database() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing=conn.execute('SELECT job_id FROM source_imports WHERE url=?',(url,)).fetchone()
            if existing: raise HTTPException(409,'This source has already been imported. Check your clip library.')
            conn.execute('INSERT INTO source_imports VALUES (?,?,?)',(url,job_id,time.time()))
        JOBS[job_id]={'id':job_id,'status':'processing','message':'Starting source import','progress':0}
    threading.Thread(target=do_source_job,args=(job_id,url,count,minimum,maximum),daemon=True).start()
    return {'job_id':job_id}


@app.post('/api/jobs')
async def start_job(file: UploadFile=File(...),count:int=Form(5),
                    min_seconds:int=Form(20),max_seconds:int=Form(60)):
    refresh_desktop_connection()
    if not media_status()['ready']:
        raise HTTPException(503,media_status()['message'])
    if not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(503,'Connect OpenAI in VYRA’s Settings & connections first.')
    count=max(1,min(count,12))
    minimum=max(12,min(min_seconds,120))
    maximum=max(minimum,min(max_seconds,180))
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(400,'Choose MP4, MOV, MKV, or WebM.')
    job_id=uuid.uuid4().hex[:18]
    with LOCK:
        if any(j.get('status')=='processing' for j in JOBS.values()):
            raise HTTPException(429,'Local video worker already busy.')
        JOBS[job_id]={'id':job_id,'status':'processing','message':'Receiving source','progress':0}
    incoming=WORK/(job_id+suffix)
    total=0
    try:
        with incoming.open('wb') as out:
            while chunk:=await file.read(1024*1024):
                total+=len(chunk)
                if total > 8*1024**3:
                    raise HTTPException(413,'Maximum upload size is 8GB.')
                out.write(chunk)
        if total==0:
            raise HTTPException(400,'Empty video.')
    except Exception:
        incoming.unlink(missing_ok=True)
        with LOCK:
            JOBS.pop(job_id,None)
        raise
    finally:
        await file.close()
    threading.Thread(target=do_job,args=(job_id,incoming,count,minimum,maximum),daemon=True).start()
    return {'job_id':job_id}


@app.get('/api/jobs/{job_id}')
def get_job(job_id:str):
    with LOCK:
        job=JOBS.get(job_id)
    if job:
        return job
    if not re.fullmatch('[a-f0-9]{18}',job_id):
        raise HTTPException(404,'Job not found')
    manifest=OUTPUT/job_id/'manifest.json'
    if manifest.is_file():
        return {'id':job_id,'status':'done','progress':100,
                'message':'Previously exported clips','result':json.loads(manifest.read_text('utf-8'))}
    raise HTTPException(404,'Job not found')


@app.get('/api/library')
def library():
    jobs=[]
    with database() as conn:
        checks={r['post_id']:json.loads(r['result_json']) for r in conn.execute('SELECT * FROM publishing_checks')}
        rows=[dict(r) for r in conn.execute("SELECT * FROM postings WHERE status != 'cancelled'")]
        reserved={(r['job_id'],r['filename']) for r in rows if r['status'] in ('approved','sending','submitted')}
        recoverable={(r['job_id'],r['filename']) for r in rows if r['status']=='needs_review'
                     or checks.get(r['id'],{}).get('state') in ('failed','rejected','unavailable')
                     or checks.get(r['id'],{}).get('visibility_mismatch')}
        reserved-=recoverable

    for item in sorted(OUTPUT.glob('*/manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            data=json.loads(item.read_text('utf-8'))
            clips = [c for c in data.get('clips', []) if (item.parent.name,c.get('file')) not in reserved and not c.get('delete_requested_at') and NAME.fullmatch(str(c.get('file', '')))
                     and (item.parent / c['file']).is_file()]
            if clips: jobs.append({'id':item.parent.name,'clips':clips})
            if len(jobs) >= 40: break
        except (ValueError,OSError):
            pass
    return jobs


@app.post('/api/post-assistant')
async def prepare_post_assistant(req:Request):
    body = await req.json()
    if not isinstance(body, dict): raise HTTPException(400, 'Choose a clip and destination.')
    try: return await run_in_threadpool(post_assistant.prepare, globals(), body)
    except ValueError as exc: raise HTTPException(400, str(exc)[:240]) from None


@app.delete('/api/clips/{job_id}/{filename}')
async def delete_clip(job_id:str, filename:str, req:Request):
    body = await req.json()
    if not isinstance(body, dict) or body.get('confirm') is not True:
        raise HTTPException(400, 'Confirm local deletion and cancellation of queued posts for this clip.')
    return await run_in_threadpool(clip_deletion.delete, globals(), job_id, filename)


@app.get('/api/jobs/{job_id}/files/{filename}')
def download(job_id:str,filename:str):
    if filename=='manifest.json' and re.fullmatch('[a-f0-9]{18}',job_id):
        p=OUTPUT/job_id/filename
        if p.exists():
            return FileResponse(p,media_type='application/json')
    path=clip_path(job_id,filename)
    return FileResponse(path,media_type='video/mp4',filename=filename,
                        content_disposition_type='inline')


@app.post('/api/oauth/{provider}/start')
def login(provider:str,access:str='basic'):
    if provider not in VALID_PLATFORMS:
        raise HTTPException(404,'Unknown platform')
    try:
        return {'url': CONNECT.start(provider,access) if provider=='youtube' else CONNECT.start(provider)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get('/api/connections/{provider}')
def connection_setup(provider:str):
    if provider not in VALID_PLATFORMS:
        raise HTTPException(404, 'Unknown platform')
    value = CONNECT.settings.info(provider)
    if provider == 'instagram': value['storage'] = instagram_storage.info(VAULT)
    return value


@app.put('/api/connections/instagram/storage')
async def save_instagram_storage(req:Request):
    global LAST_PUBLISHING_CHECK
    raw = await req.body()
    if len(raw) > 4096: raise HTTPException(413, 'Storage settings are too large.')
    try:
        body = json.loads(raw)
        if not isinstance(body, dict): raise ValueError('Check the storage fields.')
        result = instagram_storage.save(VAULT, body)
        PUBLISHING_HEALTH.pop('instagram', None)
        LAST_PUBLISHING_CHECK = 0.0
        return result
    except (ValueError, TypeError):
        raise HTTPException(400, 'Check all storage fields and wait for pending Instagram uploads before changing storage.') from None


@app.post('/api/connections/instagram/test')
def test_instagram_posting():
    global LAST_PUBLISHING_CHECK
    with PUBLISHING_LOCK:
        health = instagram_readiness(CONNECT)
        if health.get('ready'):
            try: health['storage_test'] = instagram_storage.test(VAULT)
            except ValueError as exc:
                health.update(ready=False, message=str(exc)[:240])
            except Exception:
                health.update(ready=False, message='Temporary storage test failed. Check the R2 credentials and bucket.')
        PUBLISHING_HEALTH['instagram'] = {'identity': CONNECT.info()['instagram'].get('account'), 'result': health}
        LAST_PUBLISHING_CHECK = 0.0
        return health


@app.put('/api/connections/{provider}')
async def save_connection_setup(provider:str, req:Request):
    if provider not in VALID_PLATFORMS:
        raise HTTPException(404, 'Unknown platform')
    raw = bytearray()
    async for chunk in req.stream():
        raw.extend(chunk)
        if len(raw) > 32768: raise HTTPException(413, 'Connection settings are too large.')
    try:
        body=json.loads(raw)
        if not isinstance(body, dict): raise ValueError('Invalid connection settings.')
        return CONNECT.settings.save(provider, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)[:240]) from None
    except TypeError:
        raise HTTPException(400, 'Check the required connection fields.') from None


@app.post('/api/accounts/facebook/page')
async def choose_facebook_page(req:Request):
    try:
        body=await req.json()
        return CONNECT.select_page(str(body.get('page_id', '')))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(400, 'Choose a Page returned by your Facebook sign-in.') from None


@app.get('/api/oauth/{provider}/callback')
def callback(provider:str,state:str='',code:str='',error:str=''):
    global LAST_PUBLISHING_CHECK
    if provider not in VALID_PLATFORMS:
        raise HTTPException(404,'Unsupported provider')
    if error:
        return RedirectResponse('/?error='+quote(error),status_code=302)
    try:
        data=CONNECT.finish(provider,state,code)
        CONNECTION_EVENTS[provider]={'ok':True,'at':utc_now(),'message':'Account connection saved.'}
        PUBLISHING_HEALTH.pop(provider,None)
        LAST_PUBLISHING_CHECK=0.0
    except ValueError as exc:
        CONNECTION_EVENTS[provider]={'ok':False,'at':utc_now(),'message':str(exc)[:200]}
        return RedirectResponse('/?error='+quote(str(exc)[:200]),status_code=302)
    except Exception:
        CONNECTION_EVENTS[provider]={'ok':False,'at':utc_now(),'message':'Connection was not completed. Check your app settings and granted permissions, then try again.'}
        return RedirectResponse('/?error='+quote('Connection was not completed. Check your app settings and granted permissions, then try again.'),status_code=302)
    return RedirectResponse('/?connected='+quote(data['provider']),status_code=302)


@app.get('/api/tiktok/creator')
def creator_options():
    try:
        data=CONNECT.tiktok_options()
        return {'username':data.get('creator_username',''),
                'privacy_levels':data.get('privacy_level_options',[]),
                'max_duration':data.get('max_video_post_duration_sec',0)}
    except Exception as exc:
        raise HTTPException(400,str(exc)[:300])


@app.delete('/api/accounts/{provider}')
def disconnect(provider:str):
    global LAST_PUBLISHING_CHECK
    if provider not in VALID_PLATFORMS:
        raise HTTPException(404,'Unsupported provider')
    VAULT.delete(provider)
    PUBLISHING_HEALTH.pop(provider,None)
    LAST_PUBLISHING_CHECK=0.0
    return {'disconnected':provider}


def make_post(body,scheduled):
    provider=str(body.get('platform',''))
    job_id=str(body.get('job_id',''))
    filename=str(body.get('filename',''))
    if provider not in VALID_PLATFORMS:
        raise HTTPException(400,'Choose YouTube, Instagram, Facebook, or TikTok.')
    video=clip_path(job_id,filename)
    title=str(body.get('title','')).strip()[:100]
    caption=str(body.get('caption','')).strip()[:2200]
    visibility=str(body.get('visibility') or ('public' if provider=='youtube' else 'reels'))
    if not title or not caption:
        raise HTTPException(400,'Title and caption are required.')
    if body.get('confirm') is not True:
        raise HTTPException(400,'Check the publishing consent confirmation first.')
    if not CONNECT.info()[provider]['connected']:
        raise HTTPException(400,'Connect your social account first.')
    if provider=='tiktok' and scheduled:
        raise HTTPException(400,'TikTok requires a fresh, explicit posting confirmation and available privacy choices; use Publish now.')
    if provider=='youtube' and visibility != 'public':
        raise HTTPException(400,'New YouTube posts must be Public. Prepare a public post before confirming.')
    if provider in ('instagram','facebook') and visibility != 'reels':
        raise HTTPException(400, 'Choose Reels publishing for this destination.')
    if provider=='tiktok' and visibility != 'PUBLIC_TO_EVERYONE':
        raise HTTPException(400,'Choose Public in TikTok. This client will not silently post a private copy.')
    if scheduled:
        try:
            when=datetime.fromisoformat(str(body.get('scheduled_at','')).replace('Z','+00:00'))
            if when.tzinfo is None:
                raise ValueError('timezone required')
            if when.astimezone(timezone.utc) <= datetime.now(timezone.utc):
                raise ValueError('date passed')
        except ValueError:
            raise HTTPException(400,'Choose a future date and time with a timezone offset.')
    else:
        when=datetime.now(timezone.utc)
    if provider=='instagram':
        health=instagram_readiness(CONNECT)
        PUBLISHING_HEALTH['instagram']={'identity':CONNECT.info()['instagram'].get('account'),'result':health}
        if not health['ready']:
            raise HTTPException(400,health['message']+' '+health.get('setup_message','')+' No post was sent.')
    record={'id':uuid.uuid4().hex[:20],'job_id':job_id,'filename':filename,
            'platform':provider,'title':title,'caption':caption,'visibility':visibility,
            'scheduled_at':when.astimezone(timezone.utc).isoformat(),'status':'approved',
            'remote_json':None,'error':None,'created_at':utc_now()}
    with database() as conn:
        conn.execute('BEGIN IMMEDIATE')
        # Recheck after acquiring the same lock used by storage cleanup.
        clip_path(job_id, filename)
        duplicate=conn.execute("SELECT id FROM postings WHERE job_id=? AND filename=? AND platform=? AND status IN ('approved','sending','submitted') LIMIT 1",(job_id,filename,provider)).fetchone()
        if duplicate:
            raise HTTPException(409,'This clip already has a queued or submitted post for this account. Check activity first.')
        available=posting_schedule.next_free(when,posting_schedule.occupied(conn,provider))
        if abs((available-when).total_seconds())>1:
            raise HTTPException(409,'This account already has a nearby post. Leave 90 minutes between posts. The next available time is '+available.isoformat()+'. Choose automatic timing again or select a later time.')
        conn.execute('INSERT INTO postings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',tuple(record.values()))
        conn.commit()
    return record


@app.post('/api/publish')
async def publish(req:Request):
    body=await req.json()
    record=await run_in_threadpool(make_post,body,False)
    threading.Thread(target=deliver,args=(record['id'],),daemon=True).start()
    return {'id':record['id'],'status':'queued','note':'Queued for delivery. Files transfer one at a time; check Publishing for confirmation.'}


@app.post('/api/schedule')
async def schedule(req:Request):
    record=await run_in_threadpool(make_post,await req.json(),True)
    return {'id':record['id'],'status':'approved','scheduled_at':record['scheduled_at']}


@app.get('/api/queue')
def queue():
    with database() as conn:
        checks={r['post_id']:json.loads(r['result_json']) for r in conn.execute('SELECT * FROM publishing_checks')}
        removed = {(r['job_id'], r['filename']) for r in conn.execute('SELECT * FROM clip_cleanup')}
    return [{**row,'delivery':delivery_view(row,checks.get(row['id'])),
             'local_copy': 'removed' if (row['job_id'], row['filename']) in removed else 'pending_delivery' if row['status'] in ('approved','sending','submitted') and checks.get(row['id'],{}).get('state') not in ('failed','rejected','unavailable') and not checks.get(row['id'],{}).get('visibility_mismatch') else 'saved'} for row in read_posts()]


@app.post('/api/publishing/refresh')
def check_publishing():
    return refresh_publishing()


@app.post('/api/queue/{item_id}/cancel')
def cancel(item_id:str):
    with database() as conn:
        cur=conn.execute("UPDATE postings SET status='cancelled' WHERE id=? AND status='approved'",(item_id,))
        conn.commit()
    if not cur.rowcount:
        raise HTTPException(409,'Could not cancel; the job may have started sending already.')
    return {'cancelled':True}


from intelligence import register_intelligence
register_intelligence(app, globals())


def discovery_loop():
    while True:
        source_discovery.auto_scan(globals())
        time.sleep(60)

if os.getenv('VYRA_DISABLE_SCHEDULER') != '1':
    threading.Thread(target=discovery_loop,daemon=True).start()

if os.getenv('VYRA_DISABLE_SCHEDULER') != '1':
    threading.Thread(target=worker,daemon=True).start()
