"""Read owned-channel measurements; credentials never leave the connector."""
from datetime import date, timedelta, datetime, timezone
import re
import requests
from social import TIMEOUT, check, facebook_version

YT_ANALYTICS = 'https://www.googleapis.com/auth/yt-analytics.readonly'
YT_EDIT = 'https://www.googleapis.com/auth/youtube.force-ssl'


class MeasurementError(RuntimeError):
    def __init__(self,status,code):
        self.status=status;self.code=code
        super().__init__('Measurements unavailable (HTTP '+str(status)+', platform code '+str(code)+').')


def read_measurements(response):
    try: return check(response)
    except RuntimeError:
        try: code=int(response.json().get('error',{}).get('code',0))
        except (ValueError,TypeError,AttributeError): code=0
        raise MeasurementError(response.status_code,code) from None


def youtube_video(connect, video_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('Choose a valid YouTube video ID from your performance report.')
    token, account = connect.token('youtube')
    result = read_measurements(requests.get('https://www.googleapis.com/youtube/v3/videos',
        params={'part': 'snippet,statistics,contentDetails', 'id': video_id},
        headers={'Authorization': 'Bearer '+token}, timeout=TIMEOUT))
    items = result.get('items', [])
    if len(items) != 1 or items[0].get('snippet', {}).get('channelId') != account.get('channel_id'):
        raise ValueError('This video does not belong to the connected YouTube channel.')
    return items[0]


def update_youtube_video(connect, video_id, title, description, expected_etag):
    token, account = connect.token('youtube')
    scopes = str(account.get('scope', '')).split()
    if YT_EDIT not in scopes and 'https://www.googleapis.com/auth/youtube' not in scopes:
        raise ValueError('Enable published-video editing in Connected accounts, then approve YouTube access.')
    current = youtube_video(connect, video_id)
    if current.get('etag') != expected_etag:
        raise ValueError('The YouTube video changed after this draft was prepared. Prepare a fresh edit.')
    snippet = current['snippet']
    # videos.update replaces mutable snippet properties; preserve every supported
    # existing field and never send status (privacy) or unrelated video parts.
    writable = {k: snippet[k] for k in ('title','description','categoryId','tags','defaultLanguage','defaultAudioLanguage') if k in snippet}
    writable.update(title=title, description=description)
    return check(requests.put('https://www.googleapis.com/youtube/v3/videos',
        params={'part':'snippet'}, json={'id':video_id,'snippet':writable},
        headers={'Authorization':'Bearer '+token, 'If-Match':expected_etag}, timeout=TIMEOUT))


def youtube_performance(connect, limit, days, watch_time):
    token, account = connect.token('youtube')
    headers = {'Authorization': 'Bearer '+token}
    channels = read_measurements(requests.get('https://www.googleapis.com/youtube/v3/channels',
        params={'part':'contentDetails,snippet','mine':'true'}, headers=headers, timeout=TIMEOUT))
    items = channels.get('items', [])
    if len(items) != 1 or items[0].get('id') != account.get('channel_id'):
        raise ValueError('Reconnect the intended YouTube channel before reading its performance.')
    playlist = items[0].get('contentDetails', {}).get('relatedPlaylists', {}).get('uploads')
    if not playlist:
        return {'platform':'youtube','videos':[], 'notes':['No uploads playlist is available.']}
    uploads = read_measurements(requests.get('https://www.googleapis.com/youtube/v3/playlistItems',
        params={'part':'contentDetails','playlistId':playlist,'maxResults':limit}, headers=headers, timeout=TIMEOUT))
    ids = [v['contentDetails']['videoId'] for v in uploads.get('items', []) if v.get('contentDetails', {}).get('videoId')]
    videos = []
    if ids:
        data = read_measurements(requests.get('https://www.googleapis.com/youtube/v3/videos',
            params={'part':'snippet,statistics,contentDetails','id':','.join(ids)}, headers=headers, timeout=TIMEOUT))
        for v in data.get('items', []):
            s, stats = v.get('snippet', {}), v.get('statistics', {})
            if s.get('channelId') != account.get('channel_id'): continue
            measured = {k:int(stats[k]) if str(stats.get(k, '')).isdigit() else None for k in ('viewCount','likeCount','commentCount')}
            videos.append({'id':v['id'], 'title':s.get('title',''), 'description':s.get('description','')[:5000],
                'published_at':s.get('publishedAt'), 'duration':v.get('contentDetails',{}).get('duration'),
                'url':'https://www.youtube.com/watch?v='+v['id'], 'lifetime':measured})
    result = {'platform':'youtube','account':account.get('account'), 'fetched_at':datetime.now(timezone.utc).isoformat(),
        'videos':videos, 'basic_counts_available':True, 'uploads_returned':len(videos),
        'sample':'Most recent uploads; this is not a complete channel history or a Shorts-only filter.',
        'notes':['Lifetime counts have different exposure times. Associations do not establish why a video performed well. Missing measurements are unknown, not zero.']}
    if not videos: result['notes'].append('No uploads were returned for the connected channel. Missing analytics authorization does not block basic upload listings or counts.')
    if watch_time:
        if YT_ANALYTICS not in str(account.get('scope','')).split():
            result['analytics']={'available':False,'reason':'Approve analytics access in Connected accounts to read watch time.'}
        elif ids:
            try:
                end = date.today()-timedelta(days=2)
                start = end-timedelta(days=days-1)
                data = read_measurements(requests.get('https://youtubeanalytics.googleapis.com/v2/reports',params={
                    'ids':'channel==MINE','startDate':start.isoformat(),'endDate':end.isoformat(),
                    'dimensions':'video','filters':'video=='+','.join(ids),
                    'metrics':'views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,shares',
                    'maxResults':limit,'sort':'-views'},headers=headers,timeout=TIMEOUT))
                names=[h['name'] for h in data.get('columnHeaders',[])]
                result['analytics']={'available':True,'start_date':start.isoformat(),'end_date':end.isoformat(),
                    'rows':[dict(zip(names,row)) for row in data.get('rows',[])], 'note':'Recent days can be delayed or incomplete.'}
            except (ValueError, RuntimeError, requests.RequestException):
                result['analytics']={'available':False,'reason':'YouTube Analytics is unavailable. Enable the API in your Google project and check account permissions. Basic counts are shown.'}
    return result


def instagram_performance(connect, limit):
    token, account = connect.token('instagram')
    endpoint='https://graph.instagram.com/'+facebook_version()+'/'+str(account['user_id'])+'/media'
    fields='id,caption,media_type,permalink,timestamp'
    unavailable=False
    try:
        data=read_measurements(requests.get(endpoint,params={'fields':fields+',like_count,comments_count','limit':limit},headers={'Authorization':'Bearer '+token},timeout=TIMEOUT))
    except RuntimeError as error:
        if isinstance(error,MeasurementError) and error.code in (190,10,200): raise
        data=read_measurements(requests.get(endpoint,params={'fields':fields,'limit':limit},headers={'Authorization':'Bearer '+token},timeout=TIMEOUT))
        unavailable=True
    return {'platform':'instagram','account':account.get('account'),'fetched_at':datetime.now(timezone.utc).isoformat(),
        'media':[{k:v.get(k) for k in ('id','caption','media_type','permalink','timestamp','like_count','comments_count')} for v in data.get('data',[])],
        'notes':['Recent media and available lifetime engagement only. Reach, views, retention and watch time are not connected for Instagram yet. Missing measurements are unknown.']+(['Engagement fields were unavailable for this connection; basic media records are shown.'] if unavailable else [])}


def performance(connect, platform, limit=20, days=28, watch_time=False):
    limit=max(1,min(int(limit),50)); days=max(1,min(int(days),365))
    try:
        if platform=='youtube': return youtube_performance(connect,limit,days,watch_time)
        if platform=='instagram': return instagram_performance(connect,limit)
        raise ValueError('Performance is available for connected YouTube and Instagram accounts.')
    except requests.RequestException:
        raise ValueError('The platform could not be reached. Your saved connection has been preserved.') from None
    except MeasurementError as error:
        if error.code==190:
            raise ValueError('Instagram rejected the saved access token (platform code 190). Reconnect Instagram in Connected accounts; existing clip drafts are preserved.') from None
        if error.code in (10,200):
            raise ValueError('The platform did not grant access to these measurements (code '+str(error.code)+'). Review the app permissions in Connected accounts.') from None
        raise ValueError(str(error)+' Check Connected accounts and API permissions.') from None
    except RuntimeError:
        raise ValueError('The platform could not provide these measurements. Reconnect the intended account and check its permissions.') from None
