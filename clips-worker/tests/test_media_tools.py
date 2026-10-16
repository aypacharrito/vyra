import os
from pathlib import Path
import media_tools


def test_private_engine_works_without_path(tmp_path,monkeypatch):
    monkeypatch.setenv('VYRA_MEDIA_TOOLS',str(tmp_path))
    monkeypatch.setenv('PATH','')
    monkeypatch.delenv('LOCALAPPDATA',raising=False)
    suffix='.exe' if os.name=='nt' else ''
    (tmp_path/('ffmpeg'+suffix)).write_bytes(b'fixture')
    assert not media_tools.media_status()['ready']
    (tmp_path/('ffprobe'+suffix)).write_bytes(b'fixture')
    assert media_tools.media_status()['ready']
    assert Path(media_tools.tool_path('ffmpeg')).parent==tmp_path
