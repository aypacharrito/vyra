"""Provider-specific OAuth, token storage, and official publishing clients.

Single-user localhost prototype. All provider requests require credentials created by
*the user*, proper app approval, and an interactive account authorization.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
import requests
from cryptography.fernet import Fernet
from connection_settings import ConnectionSettings

HOST = 'http://127.0.0.1:8765'
TIMEOUT = 35
VALID_PLATFORMS = ('youtube', 'instagram', 'facebook', 'tiktok')


def check(response):
    """Never leak raw credential-bearing URLs in errors."""
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok:
        detail = data.get('error', {})
        if isinstance(detail, dict):
            detail = detail.get('message', detail.get('code', 'provider error'))
        raise RuntimeError(f'Provider returned HTTP {response.status_code}: {str(detail)[:280]}')
    if isinstance(data.get('error'), dict) and data['error'].get('code') not in (None, 'ok'):
        raise RuntimeError('Provider: ' + str(data['error'].get('message') or data['error'].get('code'))[:280])
    return data


def required(*names):
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise ValueError('Configure these environment variables in .env: ' + ', '.join(missing))


class Vault:
    """Local encrypted tokens/config. Windows wraps the vault key with user-bound DPAPI."""
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.key_path = directory / 'vault.key'
        self.data_path = directory / 'vault.bin'
        if os.name == 'nt':
            from credential_protection import windows_key
            protected = directory / 'vault-key.dpapi'
            if protected.exists():
                key = windows_key(protected.read_bytes(), False)
            else:
                key = self.key_path.read_bytes().strip() if self.key_path.exists() else Fernet.generate_key()
                tmp = directory / ('key-' + secrets.token_hex(8) + '.tmp')
                tmp.write_bytes(windows_key(key, True))
                os.replace(tmp, protected)
            # Remove the old plaintext wrapping key only after the protected key exists.
            self.key_path.unlink(missing_ok=True)
        elif not self.key_path.exists():
            # exclusive creation: never overwrite a working encryption key
            with self.key_path.open('xb') as f:
                f.write(Fernet.generate_key())
            try:
                self.key_path.chmod(0o600)
            except OSError:
                pass
        if os.name != 'nt':
            key = self.key_path.read_bytes().strip()
        self.fernet = Fernet(key)
        self.lock = threading.RLock()

    def _read(self):
        if not self.data_path.exists():
            return {}
        return json.loads(self.fernet.decrypt(self.data_path.read_bytes()).decode('utf-8'))

    def get(self, name):
        with self.lock:
            return self._read().get(name)

    def save(self, name, value):
        with self.lock:
            data = self._read()
            data[name] = value
            tmp = self.directory / 'vault.tmp'
            tmp.write_bytes(self.fernet.encrypt(json.dumps(data).encode('utf-8')))
            try:
                tmp.chmod(0o600)
            except OSError:
                pass
            os.replace(tmp, self.data_path)

    def delete(self, name):
        with self.lock:
            data = self._read()
            data.pop(name, None)
            self.save_all(data)

    def save_all(self, data):
        tmp = self.directory / 'vault.tmp'
        tmp.write_bytes(self.fernet.encrypt(json.dumps(data).encode('utf-8')))
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp, self.data_path)


class Connectors:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.settings = ConnectionSettings(vault)
        self.pending = {}
        self.lock = threading.RLock()

    def configured(self, provider):
        return self.settings.configured(provider)

    def callback(self, provider):
        if provider in ('instagram', 'facebook'):
            return self.settings.get(provider, 'redirect_uri')
        return f'{HOST}/api/oauth/{provider}/callback'

    def info(self):
        out = {}
        for name in VALID_PLATFORMS:
            v = self.vault.get(name)
            connected = bool(v and v.get('access_token'))
            if name == 'facebook':
                current = bool(v and time.time() - v.get('saved_at', 0) < int(v.get('expires_in', 60*86400)))
                connected = connected and bool(v.get('page_id')) and current
            out[name] = {'configured': self.configured(name), 'connected': connected,
                         'account': (v or {}).get('account', ''),
                         'permission': 'requires approved developer app and creator consent'}
            if name == 'facebook':
                out[name]['pages'] = [{'id': p['id'], 'name': p['name']} for p in (v or {}).get('pages', [])] if current else []
                out[name]['page_id'] = (v or {}).get('page_id', '')
        return out

    def start(self, name):
        if name not in VALID_PLATFORMS:
            raise ValueError('Unsupported platform')
        if not self.configured(name):
            raise ValueError('Complete the account setup in VYRA before signing in.')
        state = secrets.token_urlsafe(32)
        pending = {'provider': name, 'created': time.time(), 'redirect_uri': self.callback(name)}
        redirect = pending['redirect_uri']
        if name == 'youtube':
            verifier = secrets.token_urlsafe(48)
            pending['verifier'] = verifier
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            params = {'client_id': self.settings.get(name, 'client_id'), 'redirect_uri': redirect,
                      'response_type':'code', 'scope':'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
                      'access_type':'offline','prompt':'consent', 'state': state,
                      'code_challenge': challenge, 'code_challenge_method': 'S256'}
            url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)
        elif name == 'instagram':
            destination = urlparse(redirect)
            if destination.scheme != 'https' and not (destination.scheme == 'http' and destination.hostname in ('localhost', '127.0.0.1')):
                raise ValueError('Instagram callback must be an approved HTTPS redirect (or explicitly allowed local development redirect).')
            params = {'client_id':self.settings.get(name, 'client_id'), 'redirect_uri':redirect, 'response_type':'code',
                      'scope':'instagram_business_basic,instagram_business_content_publish', 'state':state}
            url = 'https://www.instagram.com/oauth/authorize?' + urlencode(params)
        elif name == 'facebook':
            params = {'client_id': self.settings.get(name, 'client_id'), 'redirect_uri': redirect,
                      'response_type': 'code', 'state': state,
                      'scope': 'pages_show_list,pages_read_engagement,pages_manage_posts'}
            url = f'https://www.facebook.com/{facebook_version()}/dialog/oauth?' + urlencode(params)
        else:
            verifier = secrets.token_urlsafe(48)
            # TikTok's desktop PKCE docs specify lowercase SHA-256 hex encoding.
            challenge = hashlib.sha256(verifier.encode()).hexdigest()
            pending['verifier'] = verifier
            params = {'client_key':self.settings.get(name, 'client_id'), 'response_type':'code',
                      'scope':'user.info.basic,video.publish', 'redirect_uri':redirect,
                      'state':state,'code_challenge':challenge,'code_challenge_method':'S256'}
            url = 'https://www.tiktok.com/v2/auth/authorize/?' + urlencode(params)
        with self.lock:
            # Remove expired states.
            self.pending = {k:v for k,v in self.pending.items() if time.time()-v['created'] < 600}
            self.pending[state] = pending
        return url

    def finish(self, provider, state, code):
        with self.lock:
            pending = self.pending.pop(state, None)
        if not pending or pending['provider'] != provider or time.time()-pending['created'] > 600:
            raise ValueError('Login state expired or invalid. Start account connection again.')
        if not code:
            raise ValueError('The platform did not return an authorization code.')
        uri = pending['redirect_uri']
        if provider == 'youtube':
            resp = requests.post('https://oauth2.googleapis.com/token', data={
                'client_id':self.settings.get(provider, 'client_id'),'client_secret':self.settings.get(provider, 'client_secret'),
                'code':code,'grant_type':'authorization_code','redirect_uri':uri,'code_verifier':pending['verifier']},timeout=TIMEOUT)
            v = check(resp)
            scopes = str(v.get('scope', '')).split()
            if scopes and 'https://www.googleapis.com/auth/youtube.upload' not in scopes:
                raise ValueError('Google did not grant video upload permission. Reconnect and approve uploads.')
            channels = check(requests.get('https://www.googleapis.com/youtube/v3/channels',
                params={'part':'snippet','mine':'true'}, headers={'Authorization':'Bearer '+v['access_token']}, timeout=TIMEOUT))
            items = channels.get('items', [])
            if len(items) != 1 or not items[0].get('id'):
                raise ValueError('Choose the Google or Brand account for your YouTube channel, then reconnect.')
            v['channel_id'] = str(items[0]['id'])
            v['account'] = str(items[0].get('snippet', {}).get('title') or v['channel_id'])[:160]
        elif provider == 'instagram':
            resp = requests.post('https://api.instagram.com/oauth/access_token', data={
                'client_id':self.settings.get(provider, 'client_id'),'client_secret':self.settings.get(provider, 'client_secret'),
                'grant_type':'authorization_code','redirect_uri':uri,'code':code},timeout=TIMEOUT)
            raw = check(resp)
            upgraded = requests.get('https://graph.instagram.com/access_token', params={
                'grant_type':'ig_exchange_token','client_secret':self.settings.get(provider, 'client_secret'),
                'access_token':raw['access_token']},timeout=TIMEOUT)
            v = check(upgraded)
            v['user_id'] = str(raw['user_id'])
            v['account'] = 'Instagram Professional: ' + v['user_id']
        elif provider == 'facebook':
            base = 'https://graph.facebook.com/' + facebook_version()
            raw = check(requests.get(base + '/oauth/access_token', params={
                'client_id': self.settings.get(provider, 'client_id'),
                'client_secret': self.settings.get(provider, 'client_secret'),
                'redirect_uri': uri, 'code': code}, timeout=TIMEOUT))
            v = check(requests.get(base + '/oauth/access_token', params={
                'grant_type': 'fb_exchange_token', 'client_id': self.settings.get(provider, 'client_id'),
                'client_secret': self.settings.get(provider, 'client_secret'),
                'fb_exchange_token': raw['access_token']}, timeout=TIMEOUT))
            pages = []
            after = ''
            for _ in range(10):
                params = {'fields': 'id,name,access_token,tasks', 'limit': 100}
                if after: params['after'] = after
                result = check(requests.get(base + '/me/accounts', params=params,
                    headers={'Authorization': 'Bearer ' + v['access_token']}, timeout=TIMEOUT))
                pages.extend(p for p in result.get('data', []) if p.get('id') and p.get('name') and p.get('access_token')
                             and ('CREATE_CONTENT' in p.get('tasks', []) or 'MANAGE' in p.get('tasks', [])))
                paging = result.get('paging', {})
                after = paging.get('cursors', {}).get('after', '')
                if not paging.get('next') or not after: break
            if not pages:
                raise ValueError('No Facebook Pages with publishing access were returned. Check Page access and grant the Page permissions, then reconnect.')
            v['pages'] = pages
            v['account'] = 'Choose your Facebook Page'
        else:
            resp = requests.post('https://open.tiktokapis.com/v2/oauth/token/', data={
                'client_key':self.settings.get(provider, 'client_id'),'client_secret':self.settings.get(provider, 'client_secret'),
                'code':code,'grant_type':'authorization_code','redirect_uri':uri,'code_verifier':pending['verifier']},
                headers={'Content-Type':'application/x-www-form-urlencoded'},timeout=TIMEOUT)
            v = check(resp)
            v['account'] = 'TikTok: ' + str(v.get('open_id','authorized account'))[:50]
        v['saved_at'] = time.time()
        self.vault.save(provider,v)
        return {'provider':provider,'account':v['account']}

    def token(self, provider):
        data = self.vault.get(provider)
        if not data:
            raise ValueError('Connect your ' + provider + ' account first.')
        if provider == 'facebook':
            if not data.get('page_id') or not data.get('page_access_token'):
                raise ValueError('Choose the Facebook Page you want VYRA to publish to.')
            if time.time() - data.get('saved_at', 0) >= int(data.get('expires_in', 60*86400)):
                raise ValueError('Reconnect Facebook to renew the Page connection.')
            return data['page_access_token'], data
        age = time.time() - data.get('saved_at',0)
        exp = int(data.get('expires_in',3600))
        if provider == 'instagram' and age < exp - 7*86400:
            return data['access_token'], data
        if provider != 'instagram' and age < exp - 180:
            return data['access_token'], data
        if provider == 'youtube':
            if not data.get('refresh_token'):
                raise ValueError('Reconnect YouTube to receive a refresh token.')
            v = check(requests.post('https://oauth2.googleapis.com/token',data={
                'client_id':self.settings.get(provider, 'client_id'),'client_secret':self.settings.get(provider, 'client_secret'),
                'refresh_token':data['refresh_token'],'grant_type':'refresh_token'},timeout=TIMEOUT))
        elif provider == 'instagram':
            v = check(requests.get('https://graph.instagram.com/refresh_access_token',params={
                'grant_type':'ig_refresh_token','access_token':data['access_token']},timeout=TIMEOUT))
        else:
            v = check(requests.post('https://open.tiktokapis.com/v2/oauth/token/',data={
                'client_key':self.settings.get(provider, 'client_id'), 'client_secret':self.settings.get(provider, 'client_secret'),
                'refresh_token':data['refresh_token'],'grant_type':'refresh_token'},timeout=TIMEOUT))
        data.update(v)
        data['saved_at'] = time.time()
        self.vault.save(provider,data)
        return data['access_token'],data

    def select_page(self, page_id):
        data = self.vault.get('facebook') or {}
        page = next((p for p in data.get('pages', []) if p['id'] == page_id), None)
        if not page:
            raise ValueError('Choose a Page returned by your Facebook connection.')
        data.update(page_id=page['id'], page_access_token=page['access_token'], account=page['name'])
        self.vault.save('facebook', data)
        return {'connected': True, 'account': page['name'], 'page_id': page['id']}

    def tiktok_options(self):
        token,_ = self.token('tiktok')
        data = check(requests.post('https://open.tiktokapis.com/v2/post/publish/creator_info/query/',
                                   headers={'Authorization':'Bearer '+token},timeout=TIMEOUT))
        return data.get('data', {})


def facebook_version():
    value = os.getenv('FACEBOOK_GRAPH_VERSION', 'v24.0')
    import re
    if not re.fullmatch(r'v\d+\.\d+', value):
        raise ValueError('Invalid Facebook API version in local app configuration.')
    return value


def facebook_post(connectors: Connectors, video: Path, title: str, caption: str):
    """Meta's start / local binary upload / finish flow for Facebook Page Reels."""
    from clip_engine import probe
    media = probe(video)
    if not 4 <= media['duration'] <= 60.5:
        raise ValueError('Choose a Facebook Reel between 4 and 60 seconds.')
    if media['width'] < 540 or media['height'] < 960 or abs(media['width']/media['height'] - 9/16) > .02:
        raise ValueError('Facebook Reels need a vertical 9:16 clip at 540 × 960 or higher.')
    token, account = connectors.token('facebook')
    version = facebook_version()
    base = f'https://graph.facebook.com/{version}/{account["page_id"]}/video_reels'
    headers = {'Authorization': 'Bearer ' + token}
    started = check(requests.post(base, data={'upload_phase': 'start'}, headers=headers, timeout=TIMEOUT))
    video_id = str(started.get('video_id', ''))
    upload = str(started.get('upload_url', ''))
    destination = urlparse(upload)
    if not video_id.isdigit() or destination.scheme != 'https' or destination.hostname != 'rupload.facebook.com' or destination.username or destination.password or destination.port not in (None, 443):
        raise RuntimeError('Facebook did not return a trusted upload endpoint.')
    with video.open('rb') as source:
        transferred = check(requests.post(upload, data=source, headers={
            'Authorization': 'OAuth ' + token, 'offset': '0', 'file_size': str(video.stat().st_size),
            'Content-Type': 'application/octet-stream'}, timeout=300, allow_redirects=False))
    if transferred.get('success') is not True:
        raise RuntimeError('Facebook did not confirm the file upload. Check the Page before retrying.')
    finished = check(requests.post(base, data={'upload_phase': 'finish', 'video_id': video_id,
        'video_state': 'PUBLISHED', 'title': title[:100], 'description': caption[:2200]}, headers=headers, timeout=TIMEOUT))
    if finished.get('success') is not True:
        raise RuntimeError('Facebook did not confirm submission. Check the Page before retrying.')
    return {'id': video_id, 'status': 'submitted for Facebook processing', 'page': account['account']}


def youtube_upload(connectors: Connectors, video: Path, title: str, description: str, privacy='private'):
    if privacy not in ('private','unlisted','public'):
        raise ValueError('Invalid YouTube visibility')
    token,_ = connectors.token('youtube')
    size = video.stat().st_size
    resource = {'snippet':{'title':title[:100], 'description':description[:5000], 'categoryId':'22'},
                'status':{'privacyStatus':privacy,'selfDeclaredMadeForKids':False}}
    init = requests.post('https://www.googleapis.com/upload/youtube/v3/videos',
        params={'uploadType':'resumable','part':'snippet,status'},
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
                 'X-Upload-Content-Type':'video/mp4','X-Upload-Content-Length':str(size)},
        json=resource, timeout=TIMEOUT)
    if not init.ok:
        check(init)
    upload = init.headers.get('Location')
    if not upload or not upload.startswith('https://www.googleapis.com/'):
        raise RuntimeError('YouTube did not return an approved upload session URL.')
    chunk_size = 8 * 1024 * 1024
    offset = 0
    with video.open('rb') as f:
        while offset < size:
            data = f.read(chunk_size)
            end = offset + len(data) - 1
            response = requests.put(upload, headers={'Authorization':'Bearer '+token,
                'Content-Type':'video/mp4','Content-Length':str(len(data)),
                'Content-Range':f'bytes {offset}-{end}/{size}'},data=data,timeout=180)
            if response.status_code == 308:
                header = response.headers.get('Range')
                if header:
                    offset = int(header.rsplit('-',1)[1])+1
                    f.seek(offset)
                else:
                    offset = end+1
                continue
            if response.ok:
                obj=check(response)
                return {'id':obj.get('id'),'url':'https://www.youtube.com/watch?v='+str(obj.get('id')),
                        'visibility':privacy}
            check(response)
    raise RuntimeError('YouTube did not confirm the upload; check YouTube Studio before retrying.')


def tiktok_post(connectors: Connectors, video: Path, title: str, privacy: str):
    if privacy not in ('PUBLIC_TO_EVERYONE','MUTUAL_FOLLOW_FRIENDS','FOLLOWER_OF_CREATOR','SELF_ONLY'):
        raise ValueError('Invalid TikTok privacy choice.')
    creator=connectors.tiktok_options()  # must be refreshed at time of posting
    options=creator.get('privacy_level_options',[])
    if privacy not in options:
        raise ValueError('This account did not offer the selected privacy option: '+', '.join(options))
    maximum = float(creator.get('max_video_post_duration_sec') or 0)
    if maximum < 1:
        raise ValueError('TikTok creator info did not provide valid video constraints.')
    from clip_engine import probe
    if probe(video)['duration'] > maximum + 0.5:
        raise ValueError(f'The TikTok account permits only {maximum:g}-second videos. Choose a shorter clip.')
    token,_=connectors.token('tiktok')
    size=video.stat().st_size
    chunk_size=10*1024*1024
    chunks=max(1,size//chunk_size)
    payload={'post_info':{'title':title[:150], 'privacy_level':privacy,
                          'disable_comment':False,'disable_duet':False,'disable_stitch':False},
             'source_info':{'source':'FILE_UPLOAD','video_size':size,
                            'chunk_size':min(size,chunk_size),'total_chunk_count':chunks}}
    result=check(requests.post('https://open.tiktokapis.com/v2/post/publish/video/init/',
                 json=payload,headers={'Authorization':'Bearer '+token},timeout=TIMEOUT))
    info=result.get('data',{})
    upload=info.get('upload_url','')
    if urlparse(upload).scheme != 'https' or urlparse(upload).hostname not in {'open-upload.tiktokapis.com','open-upload.tiktokcdn.com'}:
        raise RuntimeError('TikTok did not return a trusted upload endpoint.')
    with video.open('rb') as f:
        pos=0
        for i in range(chunks):
            n=chunk_size if i < chunks-1 else size-pos
            data=f.read(n)
            last=pos+len(data)-1
            resp=requests.put(upload,data=data,headers={'Content-Type':'video/mp4',
                 'Content-Length':str(len(data)),'Content-Range':f'bytes {pos}-{last}/{size}'},timeout=180)
            if not resp.ok:
                raise RuntimeError('TikTok upload failed, HTTP '+str(resp.status_code)+'. Inspect TikTok account before retry.')
            pos=last+1
    return {'publish_id':info.get('publish_id'),'status':'submitted for TikTok processing','privacy':privacy}


def instagram_post(connectors: Connectors, video: Path, caption: str):
    """Upload local MP4 to private R2, give Meta a temporary signed media URL."""
    required('R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET')
    import boto3
    token,account=connectors.token('instagram')
    uid=account.get('user_id')
    if not uid:
        raise ValueError('Reconnect Instagram to obtain an Instagram professional ID.')
    s3=boto3.client('s3',endpoint_url=f'https://{os.getenv("R2_ACCOUNT_ID")}.r2.cloudflarestorage.com',
                    aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
                    aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),region_name='auto')
    key='vyra-publishing/'+secrets.token_hex(18)+'.mp4'
    bucket=os.getenv('R2_BUCKET')
    s3.upload_file(str(video),bucket,key,ExtraArgs={'ContentType':'video/mp4'})
    media_url=s3.generate_presigned_url('get_object',Params={'Bucket':bucket,'Key':key},ExpiresIn=3600)
    version=os.getenv('INSTAGRAM_GRAPH_VERSION','v24.0')
    base=f'https://graph.instagram.com/{version}'
    try:
        created=check(requests.post(f'{base}/{uid}/media',data={
            'media_type':'REELS','video_url':media_url,'caption':caption[:2200]},
            headers={'Authorization':'Bearer '+token},timeout=TIMEOUT))
        container=created['id']
        # Allow Meta processing without busy-polling.
        for _ in range(15):
            time.sleep(8)
            stat=check(requests.get(f'{base}/{container}',params={'fields':'status_code,status'},
                                    headers={'Authorization':'Bearer '+token},timeout=TIMEOUT))
            status=stat.get('status_code','')
            if status == 'FINISHED':
                result=check(requests.post(f'{base}/{uid}/media_publish',data={'creation_id':container},
                                           headers={'Authorization':'Bearer '+token},timeout=TIMEOUT))
                return {'id':result.get('id'),'status':'published'}
            if status in {'ERROR','EXPIRED'}:
                raise RuntimeError('Instagram rejected media processing: '+str(stat.get('status',''))[:180])
        raise RuntimeError('Instagram still processing. Inspect creator account before retrying to prevent duplicates.')
    finally:
        try:
            s3.delete_object(Bucket=bucket,Key=key)
        except Exception:
            pass
