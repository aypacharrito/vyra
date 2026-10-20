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
from social import Connectors, Vault, VALID_PLATFORMS, facebook_post, instagram_post, tiktok_post, youtube_upload
from publishing_status import delivery_view, instagram_readiness, youtube_checks

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
    # A previous process may have ended after the provider accepted an upload.
    # Keep it for review instead of duplicating the submission after restart.
    conn.execute("UPDATE postings SET status='needs_review', error='Worker closed during submission. Check the platform before trying again.' WHERE status='sending'")
    conn.commit()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_posts():
    with database() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM postings ORDER BY scheduled_at DESC LIMIT 200').fetchall()]


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
        results = youtube_checks(CONNECT, read_posts())
        with database() as conn:
            for post_id, result in results.items():
                conn.execute('INSERT OR REPLACE INTO publishing_checks VALUES (?,?)', (post_id, json.dumps(result)))
        identity = CONNECT.info()['instagram'].get('account')
        health = instagram_readiness(CONNECT)
        PUBLISHING_HEALTH['instagram'] = {'identity': identity, 'result': health}
        LAST_PUBLISHING_CHECK = time.monotonic()
    return {'platforms': publishing_accounts(), 'cached': False}


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
    if not any(c.get('file')==filename for c in manifest.get('clips',[])):
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
        return tiktok_post(CONNECT,video,row['title']+' '+row['caption'],row['visibility'])
    raise ValueError('Unknown destination')


def deliver(post_id):
    with database() as conn:
        # The claim must be atomic across the schedule thread and Publish now.
        claim=conn.execute("UPDATE postings SET status='sending' WHERE id=? AND status='approved'",(post_id,))
        if claim.rowcount != 1:
            return
        row=conn.execute('SELECT * FROM postings WHERE id=?',(post_id,)).fetchone()
        conn.commit()
    try:
        response=handle_post(dict(row))
        with database() as conn:
            conn.execute('UPDATE postings SET status=?,remote_json=? WHERE id=?',
                         ('submitted',json.dumps(response),post_id))
            conn.commit()
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
        except Exception:
            pass
        time.sleep(12)

if os.getenv('VYRA_DISABLE_SCHEDULER') != '1':
    threading.Thread(target=worker,daemon=True).start()


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
    allowed={'connections.js':'text/javascript', 'intelligence.js':'text/javascript', 'icon.svg':'image/svg+xml', 'favicon.ico':'image/x-icon'}
    if name not in allowed: raise HTTPException(404, 'Asset not found')
    return FileResponse(BASE/'static'/name, media_type=allowed[name])


@app.get('/api/status')
def status():
    refresh_desktop_connection()
    return {'version':'0.6.2','ready':bool(os.getenv('OPENAI_API_KEY')),
            'platforms':publishing_accounts(), 'media':media_status(), 'render_engine':'FFmpeg','post_safety':'consent per destination'}


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
    for item in sorted(OUTPUT.glob('*/manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:40]:
        try:
            data=json.loads(item.read_text('utf-8'))
            jobs.append({'id':item.parent.name,'clips':data.get('clips',[])})
        except (ValueError,OSError):
            pass
    return jobs


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
    return CONNECT.settings.info(provider)


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
    if provider=='youtube' and visibility not in ('private','unlisted','public'):
        raise HTTPException(400,'YouTube visibility must be private, unlisted, or public.')
    if provider in ('instagram','facebook') and visibility != 'reels':
        raise HTTPException(400, 'Choose Reels publishing for this destination.')
    if provider=='tiktok' and visibility not in ('PUBLIC_TO_EVERYONE','MUTUAL_FOLLOW_FRIENDS','FOLLOWER_OF_CREATOR','SELF_ONLY'):
        raise HTTPException(400,'Select a privacy option shown by TikTok.')
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
        duplicate=conn.execute("SELECT id FROM postings WHERE job_id=? AND filename=? AND platform=? AND status IN ('approved','sending','submitted') LIMIT 1",(job_id,filename,provider)).fetchone()
        if duplicate:
            raise HTTPException(409,'This clip already has a queued or submitted post for this account. Check activity first.')
        conn.execute('INSERT INTO postings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',tuple(record.values()))
        conn.commit()
    return record


@app.post('/api/publish')
async def publish(req:Request):
    body=await req.json()
    record=await run_in_threadpool(make_post,body,False)
    threading.Thread(target=deliver,args=(record['id'],),daemon=True).start()
    return {'id':record['id'],'status':'sending','note':'Submission initiated. Check publishing queue for provider response.'}


@app.post('/api/schedule')
async def schedule(req:Request):
    record=await run_in_threadpool(make_post,await req.json(),True)
    return {'id':record['id'],'status':'approved','scheduled_at':record['scheduled_at']}


@app.get('/api/queue')
def queue():
    with database() as conn:
        checks={r['post_id']:json.loads(r['result_json']) for r in conn.execute('SELECT * FROM publishing_checks')}
    return [{**row,'delivery':delivery_view(row,checks.get(row['id']))} for row in read_posts()]


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
