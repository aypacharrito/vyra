"""Private, local developer-app configuration used by the connection wizard."""
import json
import os
import re
from urllib.parse import urlparse

FIELDS = {
    'youtube': {'client_id': 'YOUTUBE_CLIENT_ID', 'client_secret': 'YOUTUBE_CLIENT_SECRET'},
    'instagram': {'client_id': 'INSTAGRAM_APP_ID', 'client_secret': 'INSTAGRAM_APP_SECRET', 'redirect_uri': 'INSTAGRAM_REDIRECT_URI'},
    'facebook': {'client_id': 'FACEBOOK_APP_ID', 'client_secret': 'FACEBOOK_APP_SECRET', 'redirect_uri': 'FACEBOOK_REDIRECT_URI'},
    'tiktok': {'client_id': 'TIKTOK_CLIENT_KEY', 'client_secret': 'TIKTOK_CLIENT_SECRET'},
}
DOCS = {
    'youtube': 'https://console.cloud.google.com/auth/clients',
    'instagram': 'https://developers.facebook.com/apps/',
    'facebook': 'https://developers.facebook.com/apps/',
    'tiktok': 'https://developers.tiktok.com/',
}


class ConnectionSettings:
    def __init__(self, vault):
        self.vault = vault

    def get(self, provider, field):
        env = FIELDS[provider].get(field)
        if env and os.getenv(env):
            return os.getenv(env)
        return (self.vault.get('_config_' + provider) or {}).get(field, '')

    def configured(self, provider):
        return all(self.get(provider, field) for field in FIELDS[provider])

    def info(self, provider):
        return {'provider': provider, 'configured': self.configured(provider),
                'saved_fields': [field for field in FIELDS[provider] if self.get(provider, field)],
                'developer_url': DOCS[provider],
                'callback': self.get(provider, 'redirect_uri') if 'redirect_uri' in FIELDS[provider]
                            else f'http://127.0.0.1:8765/api/oauth/{provider}/callback'}

    def save(self, provider, body):
        before = {field: self.get(provider, field) for field in FIELDS[provider]}
        values = self.vault.get('_config_' + provider) or {}
        if provider == 'youtube' and body.get('credential_json'):
            try:
                raw = json.loads(body['credential_json'])
                if not isinstance(raw, dict):
                    raise ValueError('Choose the Google OAuth client JSON file.')
                client = raw.get('installed') or raw.get('web')
                if not isinstance(client, dict):
                    raise ValueError('Choose the Google OAuth client JSON file.')
                body = {'client_id': client['client_id'], 'client_secret': client['client_secret']}
                if 'web' in raw and 'http://127.0.0.1:8765/api/oauth/youtube/callback' not in client.get('redirect_uris', []):
                    raise ValueError('Use a Desktop app credential file, or register VYRA’s callback for this Web app.')
            except (KeyError, TypeError, json.JSONDecodeError):
                raise ValueError('Choose the OAuth client JSON downloaded from Google, using the Desktop app type.') from None
        values = dict(values)
        for field in FIELDS[provider]:
            value = body.get(field, '')
            if not isinstance(value, str) or len(value) > 4096:
                raise ValueError('Invalid connection setting.')
            if value.strip():
                values[field] = value.strip()
        client_id = values.get('client_id') or self.get(provider, 'client_id')
        if provider == 'youtube' and client_id and not re.fullmatch(r'[A-Za-z0-9._-]+\.apps\.googleusercontent\.com', client_id):
            raise ValueError('Use a Google OAuth client ID, not an API key.')
        if provider in ('instagram', 'facebook') and client_id and not client_id.isdigit():
            raise ValueError('The Meta app ID should contain only numbers.')
        redirect = values.get('redirect_uri') or self.get(provider, 'redirect_uri')
        if 'redirect_uri' in FIELDS[provider]:
            parsed = urlparse(redirect)
            local = parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1')
            if not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query or not (parsed.scheme == 'https' or local):
                raise ValueError('Use the exact approved HTTPS callback, or an explicitly approved loopback callback.')
        if not all(values.get(field) or self.get(provider, field) for field in FIELDS[provider]):
            raise ValueError('Complete the required connection fields first.')
        self.vault.save('_config_' + provider, values)
        if any(before[field] != self.get(provider, field) for field in FIELDS[provider]):
            self.vault.delete(provider)
        return self.info(provider)
