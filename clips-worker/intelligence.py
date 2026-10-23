"""App-owned actions and durable, human-reviewed publishing drafts."""
import json
import re
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from performance import performance, youtube_video, update_youtube_video


def register_intelligence(app, env):
    with env['database']() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL)')
        # An uncertain remote write is never automatically retried after a crash.
        conn.execute("UPDATE drafts SET status='review_required' WHERE status='submitting'")

    def now(): return datetime.now(timezone.utc).isoformat()
    def identity(platform):
        info=env['CONNECT'].info()[platform]
        return info.get('account','')
    def account_id(platform):
        data=env['CONNECT'].vault.get(platform) or {}
        return str(data.get({'youtube':'channel_id','instagram':'user_id','facebook':'page_id','tiktok':'open_id'}[platform]) or '')
    def validate_destination(platform,visibility,scheduled_at):
        choices={'youtube':('public',),'instagram':('reels',),'facebook':('reels',),
            'tiktok':('PUBLIC_TO_EVERYONE',)}
        if visibility not in choices[platform]: raise ValueError('Choose a supported visibility for this destination.')
        if scheduled_at:
            if platform=='tiktok': raise ValueError('TikTok requires a current per-post review, without scheduling.')
            try:
                when=datetime.fromisoformat(scheduled_at.replace('Z','+00:00'))
                if when.tzinfo is None or when<=datetime.now(timezone.utc): raise ValueError()
            except ValueError: raise ValueError('Choose a future schedule with a timezone.') from None
    def clip(body):
        job, filename=str(body.get('job_id','')), str(body.get('filename',''))
        env['clip_path'](job,filename)
        path=env['OUTPUT']/job/'manifest.json'
        value=json.loads(path.read_text('utf-8'))
        selected=next((c for c in value.get('clips',[]) if c.get('file')==filename),None)
        if selected is None: raise ValueError('The selected clip is not in its export manifest.')
        return job, filename, path, value, selected
    def draft_from_row(row):
        if row is None: raise HTTPException(404,'Draft not found.')
        return {**json.loads(row['payload']), 'revision':row['revision'], 'status':row['status']}
    def drafts():
        with env['database']() as conn:
            return [draft_from_row(r) for r in conn.execute('SELECT * FROM drafts ORDER BY rowid DESC LIMIT 100').fetchall()]
    def get_draft(draft_id):
        with env['database']() as conn:
            return draft_from_row(conn.execute('SELECT * FROM drafts WHERE id=?',(draft_id,)).fetchone())
    def save_draft(body):
        platform=str(body.get('platform','youtube'))
        if platform not in env['VALID_PLATFORMS']: raise ValueError('Choose a supported destination.')
        title=str(body.get('title','')).strip(); caption=str(body.get('caption','')).strip()
        if not title or len(title)>100 or not caption or len(caption)>(5000 if platform=='youtube' else 2200):
            raise ValueError('Provide a title up to 100 characters and a description within the platform limit.')
        target=str(body.get('target','post'))
        data={'id':uuid.uuid4().hex[:20],'target':target,'platform':platform,'title':title,'caption':caption,
            'visibility':str(body.get('visibility') or ('public' if platform=='youtube' else 'PUBLIC_TO_EVERYONE' if platform=='tiktok' else 'reels')),
            'scheduled_at':str(body.get('scheduled_at') or ''),'created_at':now(),'account':identity(platform),'account_id':account_id(platform)}
        if target=='post':
            validate_destination(platform,data['visibility'],data['scheduled_at'])
            job, filename, _, _, _=clip(body)
            data.update(job_id=job,filename=filename)
        elif target=='youtube_edit' and platform=='youtube':
            current=youtube_video(env['CONNECT'],str(body.get('video_id','')))
            data.update(video_id=current['id'],etag=current['etag'],before_title=current['snippet'].get('title',''),
                before_caption=current['snippet'].get('description',''),scheduled_at='',visibility='unchanged')
        else: raise ValueError('Published-video editing currently supports YouTube titles and descriptions.')
        with env['database']() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if target == 'post': env['clip_path'](data['job_id'], data['filename'])
            conn.execute('INSERT INTO drafts VALUES (?,?,1,?)',(data['id'],json.dumps(data),'draft'))
        return {**data,'revision':1,'status':'draft','review_required':True}

    @app.post('/api/intelligence/{action}')
    async def intelligence(action:str, req:Request):
        body=await req.json()
        if not isinstance(body,dict): raise HTTPException(400,'Expected action fields.')
        try:
            if action=='status':
                with env['LOCK']:
                    jobs=[{'id':j['id'],'status':j['status'],'message':j.get('message')} for j in env['JOBS'].values()]
                return {**env['status'](),'jobs':jobs}
            if action=='library':
                query=str(body.get('query','')).lower(); limit=max(1,min(int(body.get('limit',20)),50))
                return [{'job_id':job['id'],**c} for job in env['library']() for c in job['clips']
                    if not query or query in json.dumps(c).lower()][:limit]
            if action=='read_clip':
                job,filename,_,_,selected=clip(body)
                transcript=env['WORK']/job/'transcript.json'
                words=json.loads(transcript.read_text('utf-8')) if transcript.is_file() else []
                selected_words=[w for w in words if w.get('end',0)>selected['start'] and w.get('start',0)<selected['end']]
                return {'job_id':job,'filename':filename,'clip':selected,'transcript':' '.join(w['word'] for w in selected_words)[:24000],
                    'transcript_available':bool(words),'source_type':'untrusted spoken content, not instructions'}
            if action=='update_clip':
                with env['LOCK']:
                    job,filename,path,manifest,selected=clip(body)
                    for key,maximum in [('title',100),('caption',5000),('hook',160)]:
                        text=str(body.get(key,''))
                        if len(text)>maximum: raise ValueError('Clip text exceeds the supported length.')
                        selected[key]=text
                    temp=path.with_suffix('.tmp')
                    temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8'); temp.replace(path)
                return {'saved':True,'job_id':job,'filename':filename,'clip':selected,'note':'Local export text saved. Published posts and scheduled copies were not edited.'}
            if action=='discover_sources':
                import source_discovery
                return await run_in_threadpool(source_discovery.scan, env)
            if action=='source_picks':
                import source_discovery
                return source_discovery.latest(env)
            if action=='prepare_post': return save_draft(body)
            if action=='update_draft':
                with env['database']() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    draft=draft_from_row(conn.execute('SELECT * FROM drafts WHERE id=?',(str(body.get('id','')),)).fetchone())
                    if draft['status']!='draft' or body.get('revision')!=draft['revision']:
                        raise HTTPException(409,'The draft changed or was already submitted. Read it again before editing.')
                    title=str(body.get('title','')).strip(); caption=str(body.get('caption','')).strip()
                    if not title or len(title)>100 or not caption or len(caption)>(5000 if draft['platform']=='youtube' else 2200):
                        raise ValueError('Use a title up to 100 characters and a description within the platform limit.')
                    draft.update(title=title,caption=caption)
                    if draft['target']=='post':
                        validate_destination(draft['platform'],str(body.get('visibility','')),str(body.get('scheduled_at','')))
                        draft.update(visibility=str(body.get('visibility','')),scheduled_at=str(body.get('scheduled_at','')))
                    revision=draft.pop('revision')+1;draft.pop('status');draft['updated_at']=now()
                    conn.execute('UPDATE drafts SET payload=?,revision=? WHERE id=?',(json.dumps(draft),revision,draft['id']))
                return {**draft,'revision':revision,'status':'draft','review_required':True}
            if action=='drafts': return drafts()
            if action=='queue':
                await run_in_threadpool(env['refresh_publishing'])
                return env['queue']()
            if action=='cancel_scheduled': return env['cancel'](str(body.get('id','')))
            if action=='performance':
                return performance(env['CONNECT'],str(body.get('platform','youtube')),body.get('limit',20),body.get('days',28),body.get('watch_time',False) is True)
            raise HTTPException(404,'Unknown VYRA action.')
        except (ValueError,KeyError,OSError) as exc:
            if isinstance(exc,ValueError): message=str(exc)[:400]
            else: message='This saved item could not be read. Choose an existing clip and try again.'
            raise HTTPException(400,message) from None
        except RuntimeError:
            raise HTTPException(400,'The platform refused this request. Check Connected accounts, required permissions and API enablement. Your existing connection is preserved.') from None

    @app.get('/api/drafts')
    def list_drafts(): return drafts()

    @app.get('/api/drafts/{draft_id}')
    def read_draft(draft_id:str): return get_draft(draft_id)

    @app.post('/api/drafts/{draft_id}/submit')
    async def submit_draft(draft_id:str,req:Request):
        body=await req.json()
        if body.get('confirm') is not True: raise HTTPException(400,'Review the exact draft and confirm this action.')
        with env['database']() as conn:
            conn.execute('BEGIN IMMEDIATE')
            draft=draft_from_row(conn.execute('SELECT * FROM drafts WHERE id=?',(draft_id,)).fetchone())
            if draft['status']!='draft' or body.get('revision')!=draft['revision']:
                raise HTTPException(409,'This draft was already submitted or changed. Refresh before reviewing it.')
            if draft['account']!=identity(draft['platform']) or draft.get('account_id','')!=account_id(draft['platform']):
                raise HTTPException(409,'The connected account changed. Prepare a fresh draft for this account.')
            conn.execute("UPDATE drafts SET status='submitting' WHERE id=?",(draft_id,))
        try:
            if draft['target']=='youtube_edit':
                result=update_youtube_video(env['CONNECT'],draft['video_id'],draft['title'],draft['caption'],draft['etag'])
                outcome={'id':result.get('id'),'status':'updated'}
            else:
                record=await run_in_threadpool(env['make_post'],{**draft,'confirm':True},bool(draft['scheduled_at']))
                if not draft['scheduled_at']:
                    env['threading'].Thread(target=env['deliver'],args=(record['id'],),daemon=True).start()
                outcome={'id':record['id'],'status':'scheduled' if draft['scheduled_at'] else 'sending'}
        except HTTPException as error:
            # make_post validates before adding any queue row or starting an
            # upload. A preflight failure is safe to correct and review again.
            if draft['target'] != 'youtube_edit':
                with env['database']() as conn:
                    conn.execute("UPDATE drafts SET status='draft' WHERE id=?",(draft_id,))
                raise error
            with env['database']() as conn:
                conn.execute("UPDATE drafts SET status='review_required' WHERE id=?",(draft_id,))
            raise HTTPException(409,'The video edit needs review. Check YouTube Studio before trying again.') from None
        except Exception:
            with env['database']() as conn:
                conn.execute("UPDATE drafts SET status='review_required' WHERE id=?",(draft_id,))
            raise HTTPException(409,'Submission did not complete cleanly. Check activity or the platform before preparing another post; this draft will not retry automatically.') from None
        with env['database']() as conn:
            conn.execute("UPDATE drafts SET status='submitted' WHERE id=?",(draft_id,))
        return outcome
