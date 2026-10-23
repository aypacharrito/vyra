"""Bounded source scouting and public URL imports. Never publishes or bypasses access controls."""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import requests

SCAN_LOCK = threading.Lock()
CACHE_SECONDS = 6 * 3600
DAILY_LIMIT = 8
PATTERN = {'version': 1, 'source': {'traction': 40, 'freshness': 25, 'engagement': 20, 'channel_scale': 15},
           'moment': {'hook': 25, 'payoff': 25, 'emotion': 20, 'standalone': 20, 'editability': 10},
           'candidate_limit': 20, 'shortlist': 5, 'scan_hours': 6,
           'note': 'Editorial ranking, not a probability of going viral. Missing measurements are excluded.'}


def initialize(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS source_scans (key TEXT PRIMARY KEY, created REAL NOT NULL, result TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS source_imports (url TEXT PRIMARY KEY, job_id TEXT NOT NULL, created REAL NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS source_budget (day TEXT PRIMARY KEY, count INTEGER NOT NULL)')


def canonical_url(raw):
    if not isinstance(raw, str) or len(raw) > 2048: raise ValueError('Paste a supported video link.')
    try: u = urlsplit(raw.strip()); port = u.port
    except ValueError: raise ValueError('Invalid video link.') from None
    if u.scheme != 'https' or u.username or u.password or port not in (None, 443):
        raise ValueError('Use a public HTTPS video link.')
    host = (u.hostname or '').lower()
    if host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'):
        parts = u.path.strip('/').split('/')
        vid = parts[0] if host == 'youtu.be' else (parse_qs(u.query).get('v', [''])[0] if u.path == '/watch' else (parts[1] if len(parts) == 2 and parts[0] in ('shorts', 'live') else ''))
        if re.fullmatch(r'[A-Za-z0-9_-]{11}', vid): return 'https://www.youtube.com/watch?v=' + vid
    if host in ('twitch.tv', 'www.twitch.tv', 'clips.twitch.tv'):
        p = u.path.strip('/').split('/')
        if host == 'clips.twitch.tv' and len(p) == 1 and re.fullmatch(r'[A-Za-z0-9_-]{6,200}', p[0]): return 'https://clips.twitch.tv/' + p[0]
        if len(p) == 2 and p[0] == 'videos' and p[1].isdigit(): return 'https://www.twitch.tv/videos/' + p[1]
        if len(p) == 3 and p[1] == 'clip' and re.fullmatch(r'[A-Za-z0-9_-]{6,200}', p[2]): return 'https://clips.twitch.tv/' + p[2]
    if host == 'archive.org' and re.fullmatch(r'/details/[A-Za-z0-9_.-]{1,160}/?', u.path):
        return 'https://archive.org/details/' + u.path.strip('/').split('/')[1]
    raise ValueError('Use a single YouTube video, Twitch clip/VOD, or Internet Archive movie. Channels and playlists are not supported.')


def get_json(url, **kwargs):
    response = requests.get(url, timeout=20, **kwargs)
    if not response.ok: raise ValueError('Source service unavailable (HTTP ' + str(response.status_code) + '). Check its connection and try later.')
    return response.json()


def youtube(connect, query, now):
    try: token, _ = connect.token('youtube')
    except Exception: raise ValueError('Connect YouTube in Connected accounts to discover YouTube sources.') from None
    headers = {'Authorization': 'Bearer ' + token}
    def api(action, **params): return get_json('https://www.googleapis.com/youtube/v3/' + action, headers=headers, params=params)
    found = api('search', part='snippet', type='video', q=query, maxResults=20, order='viewCount',
                publishedAfter=(now-timedelta(days=14)).isoformat(), videoDuration='medium')
    ids = [x.get('id', {}).get('videoId', '') for x in found.get('items', [])]
    if not ids: return []
    videos = api('videos', part='snippet,statistics,contentDetails', id=','.join(ids)).get('items', [])
    channel_ids = list({v['snippet']['channelId'] for v in videos})
    channels = api('channels', part='statistics', id=','.join(channel_ids)).get('items', [])
    sizes = {c['id']: c.get('statistics', {}).get('subscriberCount') for c in channels if not c.get('statistics', {}).get('hiddenSubscriberCount')}
    result = []
    for v in videos:
        s, stats = v['snippet'], v.get('statistics', {})
        if s.get('liveBroadcastContent') in ('live', 'upcoming'): continue
        result.append({'url': 'https://www.youtube.com/watch?v='+v['id'], 'platform': 'youtube', 'title': s['title'][:200],
                       'creator': s.get('channelTitle', ''), 'published_at': s['publishedAt'], 'views': stats.get('viewCount'),
                       'likes': stats.get('likeCount'), 'comments': stats.get('commentCount'), 'subscribers': sizes.get(s['channelId'])})
    return result


def twitch(vault, query, now):
    config = vault.get('discovery_twitch') or {}
    if not config.get('client_id') or not config.get('client_secret'):
        raise ValueError('Add a Twitch developer Client ID and secret in Discovery settings to scout Twitch.')
    auth = requests.post('https://id.twitch.tv/oauth2/token', data={**config, 'grant_type': 'client_credentials'}, timeout=20)
    if not auth.ok: raise ValueError('Twitch rejected the discovery credentials.')
    headers = {'Client-Id': config['client_id'], 'Authorization': 'Bearer '+auth.json()['access_token']}
    def api(action, **params): return get_json('https://api.twitch.tv/helix/'+action, headers=headers, params=params).get('data', [])
    games = api('search/categories', query=query, first=1) if query else api('games/top', first=1)
    if not games: return []
    clips = api('clips', game_id=games[0]['id'], first=20, started_at=(now-timedelta(days=7)).isoformat().replace('+00:00', 'Z'))
    return [{'url': canonical_url(c['url']), 'platform': 'twitch', 'title': c['title'][:200], 'creator': c.get('broadcaster_name', ''),
             'published_at': c['created_at'], 'views': c.get('view_count')} for c in clips]


def movies(query):
    # Restrict discovery to feature films with an explicit public-domain/CC license field.
    safe = ' '.join(re.findall(r'[\w-]+', query))[:120]
    q = 'collection:feature_films AND (licenseurl:*publicdomain* OR licenseurl:*creativecommons*)'
    if safe: q += ' AND title:(' + safe + ')'
    data = get_json('https://archive.org/advancedsearch.php', params={'q': q, 'fl[]': ['identifier','title','downloads','licenseurl'], 'sort[]': 'downloads desc', 'rows':20, 'output':'json'})
    result = []
    for d in data.get('response', {}).get('docs', []):
        try: url = canonical_url('https://archive.org/details/' + d['identifier'])
        except ValueError: continue
        result.append({'url':url, 'platform':'movies', 'title':str(d.get('title','Movie'))[:200], 'creator':'Internet Archive',
                       'views':d.get('downloads'), 'license':d.get('licenseurl'), 'measurement':'Archive downloads; verify the item license before reuse.'})
    return result


def number(value):
    try: return max(0, float(value)) if math.isfinite(float(value)) else 0
    except (TypeError, ValueError): return 0


def rank(items, now):
    for item in items:
        metrics = {}
        views = number(item.get('views'))
        hours = None
        try: hours = max(1, (now-datetime.fromisoformat(item['published_at'].replace('Z','+00:00'))).total_seconds()/3600)
        except (KeyError, ValueError, TypeError): pass
        if item.get('views') is not None:
            metrics['traction'] = min(1, math.log10(1+views/(hours or 24))/4)
        if hours is not None: metrics['freshness'] = max(0, 1-hours/(14*24))
        if views and item.get('likes') is not None:
            metrics['engagement'] = min(1, (number(item.get('likes'))+2*number(item.get('comments')))/views/.08)
        if views and number(item.get('subscribers')):
            metrics['channel_scale'] = min(1, views/number(item['subscribers'])/2)
        weights = PATTERN['source']
        item['score'] = round(100*sum(weights[k]*v for k,v in metrics.items())/sum(weights[k] for k in metrics)) if metrics else None
        item['signals'] = list(metrics)
        item['reason'] = ' · '.join(k.replace('_',' ') for k in metrics) or 'No measured signals available'
        item['confidence'] = 'limited' if len(metrics)<3 else 'more signals'
    return sorted(items, key=lambda i:i['score'] if i['score'] is not None else -1, reverse=True)


def settings(env):
    saved = env['VAULT'].get('discovery_settings') or {'query':'storytelling', 'provider':'youtube', 'enabled':False}
    return {**saved, 'twitch_configured':bool((env['VAULT'].get('discovery_twitch') or {}).get('client_secret')), 'pattern':PATTERN}


def save_settings(env, body):
    provider = body.get('provider', 'youtube')
    if provider not in ('youtube','twitch','movies'): raise ValueError('Choose YouTube, Twitch, or Movies.')
    query = str(body.get('query','')).strip()[:120]
    if provider=='youtube' and not query: raise ValueError('Choose a topic first.')
    if body.get('client_id') or body.get('client_secret'):
        if not body.get('client_id') or not body.get('client_secret'): raise ValueError('Enter both Twitch credentials.')
        env['VAULT'].save('discovery_twitch', {'client_id':str(body['client_id']).strip()[:200], 'client_secret':str(body['client_secret']).strip()[:300]})
    env['VAULT'].save('discovery_settings', {'query':query, 'provider':provider, 'enabled':body.get('enabled') is True})
    return settings(env)


def scan(env):
    if not SCAN_LOCK.acquire(blocking=False): raise ValueError('A discovery scan is already running.')
    try:
        config = settings(env)
        key = hashlib.sha256((config['provider']+'\n'+config['query']).encode()).hexdigest()
        now = datetime.now(timezone.utc)
        with env['database']() as conn:
            cached = conn.execute('SELECT * FROM source_scans WHERE key=?', (key,)).fetchone()
            if cached and time.time()-cached['created']<CACHE_SECONDS:
                result=json.loads(cached['result'])
                imported={r['url'] for r in conn.execute('SELECT url FROM source_imports')}
                result['items']=[x for x in result['items'] if x['url'] not in imported]
                return {**result, 'cached':True}
            conn.execute('BEGIN IMMEDIATE')
            day = now.date().isoformat()
            row = conn.execute('SELECT count FROM source_budget WHERE day=?',(day,)).fetchone()
            if row and row['count']>=DAILY_LIMIT: raise ValueError('Daily discovery budget used. Existing picks remain available; try tomorrow.')
            conn.execute('INSERT INTO source_budget VALUES (?,1) ON CONFLICT(day) DO UPDATE SET count=count+1',(day,))
            conn.execute('DELETE FROM source_budget WHERE day<?',((now-timedelta(days=7)).date().isoformat(),))
        if config['provider']=='youtube': candidates = youtube(env['CONNECT'], config['query'], now)
        elif config['provider']=='twitch': candidates = twitch(env['VAULT'], config['query'], now)
        else: candidates = movies(config['query'])
        ranked = rank(candidates[:20], now)
        with env['database']() as conn:
            imported = {r['url'] for r in conn.execute('SELECT url FROM source_imports')}
            picks = [c for c in ranked if c['url'] not in imported][:5]
            result = {'items':picks, 'checked':len(candidates[:20]), 'created_at':now.isoformat(), 'pattern':PATTERN, 'config':{'query':config['query'],'provider':config['provider']}}
            conn.execute('INSERT OR REPLACE INTO source_scans VALUES (?,?,?)',(key,time.time(),json.dumps(result)))
        return result
    finally: SCAN_LOCK.release()


def latest(env):
    config=settings(env)
    key=hashlib.sha256((config['provider']+'\n'+config['query']).encode()).hexdigest()
    with env['database']() as conn:
        row=conn.execute('SELECT result FROM source_scans WHERE key=?',(key,)).fetchone()
        imported={r['url'] for r in conn.execute('SELECT url FROM source_imports')}
    result=json.loads(row['result']) if row else {'items':[]}
    result['items']=[x for x in result['items'] if x['url'] not in imported]
    return {'settings':config, 'results':result}


LAST_AUTO_ATTEMPT=0

def auto_scan(env):
    global LAST_AUTO_ATTEMPT
    if settings(env)['enabled'] and time.time()-LAST_AUTO_ATTEMPT>CACHE_SECONDS:
        LAST_AUTO_ATTEMPT=time.time()
        try: scan(env)
        except Exception: pass  # No credentials/URLs in background logs. Manual scans show actionable errors.


def download(url, folder):
    """Separate process bounds downloader lifetime, memory-independent from the UI worker."""
    folder.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(folder).free < 3*1024**3: raise ValueError('Free at least 3 GB before importing a source.')
    try:
        done=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--download',url,str(folder)],
            capture_output=True,text=True,timeout=1200,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except subprocess.TimeoutExpired:
        raise ValueError('Source import timed out. Try a shorter source.') from None
    if done.returncode: raise ValueError('Could not import this public video. It may require sign-in, be restricted, or no longer be downloadable. Try an authorized local file.')
    files=[p for p in folder.iterdir() if p.suffix in ('.mp4','.webm','.mkv') and p.is_file()]
    if len(files)!=1 or files[0].stat().st_size>2*1024**3: raise ValueError('Import did not produce one video under 2 GB.')
    return files[0]


def _download_child(url, folder):
    import yt_dlp
    import deno
    from media_tools import tool_path
    url=canonical_url(url)
    def allowed(info, *, incomplete=False):
        if info.get('is_live') or info.get('live_status') in ('is_live','is_upcoming'): return 'Live streams are not supported.'
        if info.get('has_drm'): return 'DRM is not supported.'
        duration=info.get('duration')
        if not incomplete and (not duration or duration>7200): return 'Choose a video of up to two hours.'
    class Quiet:
        def debug(self,*_): pass
        info=warning=error=debug
    def size_guard(data):
        if number(data.get('downloaded_bytes'))>2*1024**3: raise ValueError('Maximum import size is 2 GB.')
    options={'noplaylist':True, 'playlist_items':'1', 'outtmpl':str(folder/'source.%(ext)s'), 'quiet':True, 'logger':Quiet(),
             'ignoreerrors':False,'cachedir':False,'socket_timeout':15,'retries':1,'fragment_retries':1,'concurrent_fragment_downloads':1,
             'max_filesize':2*1024**3,'format':'best[height<=1080][ext=mp4]/best[height<=1080]', 'merge_output_format':'mp4',
             'ffmpeg_location':str(Path(tool_path('ffmpeg')).parent), 'match_filter':allowed,'progress_hooks':[size_guard],
             'js_runtimes':{'deno':{'path':deno.find_deno_bin()}}, 'remote_components':set(), 'overwrites':False}
    with yt_dlp.YoutubeDL(options) as ydl: ydl.download([url])


if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='--download': sys.exit(2)
    try: _download_child(sys.argv[2],Path(sys.argv[3]))
    except Exception: sys.exit(1)
