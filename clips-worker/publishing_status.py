"""Read-only publishing receipts. Refreshing never uploads or changes visibility."""
from datetime import datetime, timezone
import json
import os
import re
import requests
from performance import MeasurementError, read_measurements
from social import TIMEOUT, facebook_version, instagram_permissions, instagram_version
import instagram_storage


def now():
    return datetime.now(timezone.utc).isoformat()


def receipt(row):
    try:
        value = json.loads(row.get('remote_json') or '{}')
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def youtube_id(row):
    value = receipt(row).get('id')
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', value) else None


def youtube_result(video, requested):
    status = video.get('status', {})
    processing = video.get('processingDetails', {})
    upload = status.get('uploadStatus')
    progress = processing.get('processingStatus')
    privacy = status.get('privacyStatus')
    result = {'checked_at': now(), 'verified': True, 'visibility': privacy,
              'upload_status': upload, 'processing_status': progress}
    if upload in ('failed', 'rejected', 'deleted') or progress in ('failed', 'terminated'):
        result.update(state='failed', label='YouTube could not publish this video',
                      message='Check this video in YouTube Studio. Do not upload another copy until you review the result.')
        reason = status.get('rejectionReason') or status.get('failureReason') or processing.get('processingFailureReason')
        # Provider reason codes are short identifiers, never raw error text.
        if isinstance(reason, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', reason):
            result['reason'] = reason
    elif upload == 'processed' or progress == 'succeeded':
        if privacy == 'private':
            result.update(state='private', label='Uploaded · Private',
                          message='YouTube finished processing. This video is private and does not appear publicly on your channel.')
        elif privacy == 'unlisted':
            result.update(state='unlisted', label='Uploaded · Unlisted',
                          message='YouTube finished processing. People with the link can watch; it is not listed publicly on your channel.')
        elif privacy == 'public':
            result.update(state='public', label='Published · Public', message='YouTube reports this video as processed and public.')
        else:
            result.update(state='processed', label='Uploaded · Visibility unknown', message='Processing finished; check visibility in YouTube Studio.')
    else:
        result.update(state='processing', label='Uploaded · Processing',
                      message='YouTube accepted the upload. Processing has not been confirmed complete.')
    if privacy and requested != privacy:
        result['visibility_mismatch'] = True
        result['visibility_note'] = 'Requested '+requested+'; YouTube reports '+privacy+'. Review visibility and restrictions in YouTube Studio.'
    if status.get('publishAt'):
        result['publish_at'] = status['publishAt']
    return result


def unavailable(message):
    return {'checked_at': now(), 'verified': False, 'state': 'unavailable',
            'label': 'Status check unavailable', 'message': message}


def youtube_checks(connect, rows):
    candidates = [r for r in rows if r['platform'] == 'youtube' and r['status'] == 'submitted'][:50]
    if not candidates:
        return {}
    valid = [r for r in candidates if youtube_id(r)]
    results = {r['id']: unavailable('No valid YouTube receipt was saved. Check YouTube Studio before trying again.')
               for r in candidates if not youtube_id(r)}
    if not valid:
        return results
    try:
        token, account = connect.token('youtube')
        data = read_measurements(requests.get('https://www.googleapis.com/youtube/v3/videos',
            params={'part': 'snippet,status,processingDetails', 'id': ','.join(dict.fromkeys(youtube_id(r) for r in valid))},
            headers={'Authorization': 'Bearer '+token}, timeout=TIMEOUT))
        videos = {v.get('id'): v for v in data.get('items', [])}
        for row in valid:
            video = videos.get(youtube_id(row))
            if not video:
                results[row['id']] = unavailable('YouTube did not return this video for the current account. It may have been removed or belong to another account. Check YouTube Studio before retrying.')
            elif not account.get('channel_id') or video.get('snippet', {}).get('channelId') != account['channel_id']:
                results[row['id']] = unavailable('Reconnect the channel that received this upload to verify its status.')
            else:
                results[row['id']] = youtube_result(video, row['visibility'])
    except (ValueError, RuntimeError, requests.RequestException):
        message = 'Could not verify this upload. Reconnect YouTube if its access expired, then check again. The original upload receipt is preserved.'
        results.update({r['id']: unavailable(message) for r in valid})
    return results


def instagram_readiness(connect):
    hosting = instagram_storage.info(connect.vault)['configured']
    result = {'checked_at': now(), 'hosting_ready': hosting, 'verified': False, 'ready': False}
    if not connect.info()['instagram']['connected']:
        return {**result, 'message': 'Connect your Instagram professional account before publishing.'}
    try:
        token, account = connect.token('instagram')
        scopes = instagram_permissions(account.get('scope'))
        if scopes and not {'instagram_business_basic', 'instagram_business_content_publish'} <= scopes:
            return {**result, 'message': 'Reconnect Instagram and approve profile and content publishing permission.'}
        uid = str(account.get('user_id') or '')
        if not uid.isdigit():
            raise ValueError('Missing professional account ID')
        data = read_measurements(requests.get('https://graph.instagram.com/'+instagram_version()+'/'+uid,
            params={'fields': 'id,username'}, headers={'Authorization': 'Bearer '+token}, timeout=TIMEOUT))
        if not data.get('id') or not data.get('username'):
            raise ValueError('No account returned')
        result.update(verified=True, account=str(data['username'])[:160], ready=hosting,
                      message='Instagram sign-in verified.' if hosting else 'Instagram sign-in works, but video upload hosting is not configured. No Reel can be sent yet.')
    except MeasurementError as error:
        result['message'] = ('Instagram rejected the saved sign-in (code 190). Reconnect Instagram before publishing.' if error.code == 190
                             else 'Instagram could not verify this account. Reconnect and review its publishing permissions.')
    except (ValueError, RuntimeError, requests.RequestException):
        result['message'] = 'Instagram could not verify this account. Reconnect Instagram and check again.'
    if not hosting:
        result['setup_message'] = 'Open Instagram App settings → Temporary video storage and save your R2 bucket credentials. Your clips stay saved until setup is complete.'
    return result


def destination_checks(connect, rows):
    """Read provider results; acceptance/processing alone never permits deletion."""
    results = {}
    for row in [r for r in rows if r['status'] == 'submitted' and r['platform'] != 'youtube'][:25]:
        saved = receipt(row)
        platform = row['platform']
        try:
            token, account = connect.token(platform)
            headers = {'Authorization': 'Bearer ' + token}
            state = 'processing'
            if platform == 'instagram':
                if saved.get('status') != 'published' or not str(saved.get('id') or '').isdigit():
                    continue
                if saved.get('account_id') and saved['account_id'] != str(account.get('user_id')):
                    raise ValueError('Different connected account')
                data = read_measurements(requests.get(
                    f'https://graph.instagram.com/{instagram_version()}/{saved["id"]}',
                    params={'fields': 'id,permalink'}, headers=headers, timeout=TIMEOUT))
                if str(data.get('id')) == str(saved['id']): state = 'published'
            elif platform == 'facebook':
                if saved.get('page_id') != str(account.get('page_id')) or not str(saved.get('id') or '').isdigit():
                    continue
                data = read_measurements(requests.get(
                    f'https://graph.facebook.com/{facebook_version()}/{saved["id"]}',
                    params={'fields': 'status,published'}, headers=headers, timeout=TIMEOUT))
                status = data.get('status', {})
                if status.get('video_status') == 'error': state = 'failed'
                elif data.get('published') is True and status.get('video_status') == 'ready': state = 'published'
            elif platform == 'tiktok':
                if not saved.get('publish_id'): continue
                if saved.get('account_id') and saved['account_id'] != str(account.get('open_id')):
                    raise ValueError('Different connected account')
                data = read_measurements(requests.post('https://open.tiktokapis.com/v2/post/publish/status/fetch/',
                    json={'publish_id': saved['publish_id']}, headers=headers, timeout=TIMEOUT))
                status = data.get('data', {}).get('status')
                if status == 'PUBLISH_COMPLETE': state = 'published'
                elif status == 'FAILED': state = 'failed'
            else:
                continue
            results[row['id']] = {'checked_at': now(), 'verified': True, 'state': state,
                'label': 'Published · Confirmed' if state == 'published' else 'Post failed' if state == 'failed' else 'Upload processing',
                'message': 'The platform confirmed publication.' if state == 'published' else 'Your local clip stays saved until publication is confirmed.'}
        except (ValueError, RuntimeError, requests.RequestException):
            results[row['id']] = unavailable('Could not verify this post. Reconnect the original account and check again. Your local clip is preserved.')
    return results


def delivery_view(row, checked=None):
    if row['status'] == 'submitted':
        if checked:
            result = dict(checked)
        else:
            result = {'verified': False, 'state': 'accepted', 'label': 'Upload accepted · Check status',
                      'message': 'The platform accepted the request. Public visibility and processing have not been checked.'}
            if row['platform'] == 'youtube':
                result['message'] += ' Requested visibility: '+row['visibility']+'.'
        vid = youtube_id(row) if row['platform'] == 'youtube' else None
        if vid:
            result.update(url='https://www.youtube.com/watch?v='+vid, studio_url='https://studio.youtube.com/video/'+vid+'/edit')
        return result
    labels = {'approved': ('scheduled', 'Scheduled · Not sent yet'), 'sending': ('sending', 'Sending to platform'),
              'needs_review': ('needs_review', 'Submission uncertain · Review required'), 'cancelled': ('cancelled', 'Cancelled')}
    state, label = labels.get(row['status'], ('unknown', 'Status unknown'))
    return {'state': state, 'label': label, 'message': row.get('error') or '', 'verified': False}
