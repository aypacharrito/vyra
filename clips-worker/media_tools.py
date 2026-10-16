"""Resolve VYRA's private video engine without depending on a refreshed PATH."""
import os
import shutil
from pathlib import Path

VERSION = '9.0.2'


def tool_path(name):
    if name not in ('ffmpeg', 'ffprobe'):
        raise ValueError('Unknown video tool')
    suffix = '.exe' if os.name == 'nt' else ''
    directories = []
    if os.getenv('VYRA_MEDIA_TOOLS'):
        directories.append(Path(os.environ['VYRA_MEDIA_TOOLS']))
    if os.name == 'nt' and os.getenv('LOCALAPPDATA'):
        directories.append(Path(os.environ['LOCALAPPDATA']) / 'VYRA' / 'Media' / ('ffmpeg-' + VERSION) / 'bin')
    for directory in directories:
        candidate = directory / (name + suffix)
        if candidate.is_file():
            return str(candidate.resolve())
    return shutil.which(name)


def media_status():
    ready = bool(tool_path('ffmpeg') and tool_path('ffprobe'))
    return {'ready': ready, 'message': 'Video engine ready' if ready else 'Video tools need repair. Choose Repair video tools in VYRA.'}
