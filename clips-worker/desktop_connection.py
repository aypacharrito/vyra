"""Refresh a desktop-owned worker after its user saves a replacement key.

Only the Windows account's encrypted VYRA file is read. No credential is
returned by worker HTTP APIs or written to the worker's environment file.
"""
import os
import threading
from pathlib import Path

_lock = threading.Lock()
_profile = os.getenv('VYRA_DESKTOP_PROFILE')
_path = Path(_profile) / 'api-key.dpapi' if _profile else None
_stamp = _path.stat().st_mtime_ns if _path and _path.exists() else None


def refresh_desktop_connection():
    global _stamp
    if os.name != 'nt' or _path is None:
        return
    with _lock:
        stamp = _path.stat().st_mtime_ns if _path.exists() else None
        if stamp == _stamp:
            return
        if stamp is None:
            os.environ.pop('OPENAI_API_KEY', None)
        else:
            from credential_protection import windows_key
            try:
                key = windows_key(_path.read_bytes(), False).decode('utf-8')
            except (OSError, RuntimeError, UnicodeError):
                return
            if not key.startswith('sk-') or not 20 <= len(key) <= 8192:
                return
            os.environ['OPENAI_API_KEY'] = key
        _stamp = stamp
