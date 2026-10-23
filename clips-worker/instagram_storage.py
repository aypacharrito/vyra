"""Private staging configuration and durable cleanup of temporary Instagram files."""
import os
import re
import secrets
import time
import tempfile
from pathlib import Path
import requests

FIELDS = {'account_id': 'R2_ACCOUNT_ID', 'access_key_id': 'R2_ACCESS_KEY_ID',
          'secret_access_key': 'R2_SECRET_ACCESS_KEY', 'bucket': 'R2_BUCKET'}


def config(vault):
    saved = vault.get('_instagram_storage') or {}
    return {key: os.getenv(env) or saved.get(key, '') for key, env in FIELDS.items()}


def info(vault):
    value = config(vault)
    return {'configured': all(value.values()), 'saved_fields': [k for k, v in value.items() if v]}


def save(vault, body):
    with vault.lock:
        return _save(vault, body)


def _save(vault, body):
    values = dict(vault.get('_instagram_storage') or {})
    before = config(vault)
    for key in FIELDS:
        value = body.get(key, '')
        if not isinstance(value, str) or len(value) > 512:
            raise ValueError('Check the storage settings.')
        if value.strip(): values[key] = value.strip()
    effective = {key: os.getenv(env) or values.get(key, '') for key, env in FIELDS.items()}
    if not re.fullmatch('[a-fA-F0-9]{32}', effective['account_id']):
        raise ValueError('Use the 32-character Cloudflare account ID, not your account name.')
    if not re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', effective['bucket']):
        raise ValueError('Check the R2 bucket name.')
    if not all(effective.values()): raise ValueError('Complete all four storage settings.')
    if vault.get('_instagram_staging') and any(effective[k] != before[k] for k in ('account_id', 'bucket')):
        raise ValueError('Wait for pending Instagram uploads and temporary-file cleanup before moving buckets. Credentials for the same bucket can be repaired now.')
    vault.save('_instagram_storage', values)
    return info(vault)


def client(vault):
    import boto3
    from botocore.config import Config
    value = config(vault)
    if not all(value.values()):
        raise ValueError('Set up temporary video storage in Instagram App settings before publishing.')
    return boto3.client('s3', endpoint_url=f'https://{value["account_id"]}.r2.cloudflarestorage.com',
                        aws_access_key_id=value['access_key_id'], aws_secret_access_key=value['secret_access_key'],
                        region_name='auto', config=Config(signature_version='s3v4',
                            connect_timeout=8, read_timeout=30, retries={'max_attempts': 1})), value['bucket']


def verify_url(url, expected):
    """Verify signed GET access, never sign a GET then accidentally test it as HEAD."""
    try:
        with requests.get(url, headers={'Range': 'bytes=0-15'}, stream=True,
                          timeout=12, allow_redirects=False) as response:
            if response.status_code not in (200, 206) or response.raw.read(16) != expected:
                raise ValueError('Temporary video URL could not be read. Check R2 Object Read & Write access and the bucket.')
    except requests.RequestException:
        raise ValueError('Temporary video storage could not be reached. Check the connection and run Test posting setup again.') from None


def stage(vault, video):
    key = 'vyra-publishing/' + secrets.token_hex(18) + '.mp4'
    # Persist before upload, so partial uploads and failed deletes are retried.
    with vault.lock:
        s3, bucket = client(vault)
        items = vault.get('_instagram_staging') or {}
        items[key] = {'bucket': bucket, 'created': time.time(), 'container': ''}
        vault.save('_instagram_staging', items)
    try:
        s3.upload_file(str(video), bucket, key, ExtraArgs={'ContentType': 'video/mp4'})
        url = s3.generate_presigned_url('get_object', Params={'Bucket': bucket, 'Key': key}, ExpiresIn=86400)
        with video.open('rb') as source: verify_url(url, source.read(16))
        return key, url
    except Exception:
        release(vault, key)
        raise ValueError('Instagram video storage upload failed. Check the bucket and Object Read & Write credentials in App settings.') from None


def test(vault):
    key = None
    try:
        with tempfile.TemporaryDirectory(prefix='vyra-storage-check-') as folder:
            sample = Path(folder) / 'probe.mp4'; sample.write_bytes(b'VYRA storage test - not a social post')
            key, _ = stage(vault, sample)
        return {'ready': True, 'message': 'Temporary storage upload and signed video URL verified. No social post was created.'}
    finally:
        if key: release(vault, key)


def attach(vault, key, container):
    with vault.lock:
        items = vault.get('_instagram_staging') or {}
        if key in items:
            items[key]['container'] = container
            vault.save('_instagram_staging', items)


def release(vault, key):
    try:
        with vault.lock:
            items = vault.get('_instagram_staging') or {}
            item = items.get(key)
            if not item: return
            if not re.fullmatch(r'vyra-publishing/[a-f0-9]{36}\.mp4', key): return
            item['delete_ready'] = True
            vault.save('_instagram_staging', items)
            s3, _ = client(vault)
            s3.delete_object(Bucket=item['bucket'], Key=key)
            items.pop(key, None)
            vault.save('_instagram_staging', items)
    except Exception:
        pass  # The durable record survives a restart and will be retried.


def collect(vault, finished=()):
    with vault.lock:
        items = vault.get('_instagram_staging') or {}
        for item in items.values():
            if item.get('container') in finished or time.time() - item.get('created', time.time()) > 25 * 3600:
                item['delete_ready'] = True
        if items: vault.save('_instagram_staging', items)
    for key, item in items.items():
        if item.get('delete_ready'): release(vault, key)
