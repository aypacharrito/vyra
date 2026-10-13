from pathlib import Path
import tempfile
from clip_engine import groups,parse_json,subtitles_ass,time_ass,probe

def test_ass_clock():
    assert time_ass(62.137) == '0:01:02.14'
    assert time_ass(-5) == '0:00:00.00'

def test_grouping():
    words=[{'start':float(i),'end':float(i)+.5,'word':'word'} for i in range(40)]
    paragraphs=groups(words)
    assert paragraphs[0]['start']==0 and len(paragraphs)>=3

def test_json():
    assert parse_json('```json\n{"clips": []}\n```') == {'clips': []}

def test_subtitles_escape():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'test.ass'
        subtitles_ass([{'start':3.0,'end':4.0,'word':'bad{\\}text'}],2,6,p)
        t=p.read_text(encoding='utf-8-sig')
        assert 'badtext' in t and 'Dialogue:' in t


def test_spoken_word_highlight_follows_word_timestamps():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / 'captions.ass'
        subtitles_ass([
            {'start': 5.0, 'end': 5.4, 'word': 'Hello'},
            {'start': 5.5, 'end': 6.0, 'word': 'VYRA'},
        ], 5.0, 7.0, p)
        text = p.read_text(encoding='utf-8-sig')
        events = [line for line in text.splitlines() if line.startswith('Dialogue:')]
        assert len(events) == 2
        assert '0:00:00.00,0:00:00.50' in events[0]
        assert r'{\c&H00D9F579&}Hello{\c&H00FFFFFF&} VYRA' in events[0]
        assert r'Hello {\c&H00D9F579&}VYRA{\c&H00FFFFFF&}' in events[1]
