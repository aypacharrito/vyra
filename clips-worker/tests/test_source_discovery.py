import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from test_queue import worker
import source_discovery as scout
from clip_engine import select_candidates

@pytest.mark.parametrize('raw,expected',[
 ('https://youtu.be/abcdefghijk?t=40','https://www.youtube.com/watch?v=abcdefghijk'),
 ('https://www.youtube.com/shorts/abcdefghijk','https://www.youtube.com/watch?v=abcdefghijk'),
 ('https://www.twitch.tv/creator/clip/ExampleClip','https://clips.twitch.tv/ExampleClip'),
 ('https://www.twitch.tv/videos/12345','https://www.twitch.tv/videos/12345'),
 ('https://archive.org/details/public-film','https://archive.org/details/public-film'),
])
def test_supported_urls_are_canonical(raw,expected): assert scout.canonical_url(raw)==expected

@pytest.mark.parametrize('raw',[
 'http://youtu.be/abcdefghijk','https://youtube.com.evil.test/watch?v=abcdefghijk',
 'https://user:pass@youtube.com/watch?v=abcdefghijk','https://127.0.0.1/video',
 'https://youtube.com:8443/watch?v=abcdefghijk','https://youtube.com/playlist?list=abc',
 'https://youtube.com/@channel','https://twitch.tv/creator','https://archive.org/details/../secret',
 None,'https://youtu.be/x','file:///etc/passwd',
])
def test_unsafe_or_unsupported_urls_rejected(raw):
 with pytest.raises(ValueError): scout.canonical_url(raw)


def test_missing_metrics_are_unknown_and_scores_bounded():
 now=datetime(2026,10,23,tzinfo=timezone.utc)
 rows=scout.rank([{'views':None},{'views':'100000','likes':'2000','comments':'500','subscribers':'1000','published_at':'2026-10-22T00:00:00Z'}],now)
 assert rows[0]['score'] in range(101) and rows[0]['confidence']=='more signals'
 assert rows[1]['score'] is None and rows[1]['signals']==[]


def test_scan_budget_cache_skip_imports_and_no_ai(worker,monkeypatch):
 env=vars(worker);calls=[]
 scout.save_settings(env,{'provider':'youtube','query':'stories','enabled':True})
 monkeypatch.setattr(scout,'youtube',lambda *_: calls.append(True) or [{'url':'https://www.youtube.com/watch?v=abcdefghijk','views':100}])
 monkeypatch.setattr(worker,'handle_post',lambda *_:pytest.fail('Discovery cannot publish'))
 first=scout.scan(env);second=scout.scan(env)
 assert len(calls)==1 and second['cached'] and len(first['items'])==1
 with worker.database() as conn: conn.execute('INSERT INTO source_imports VALUES (?,?,?)',(first['items'][0]['url'],'a'*18,1))
 assert scout.latest(env)['results']['items']==[]
 for i in range(scout.DAILY_LIMIT-1):
  scout.save_settings(env,{'provider':'youtube','query':'topic'+str(i)})
  scout.scan(env)
 scout.save_settings(env,{'provider':'youtube','query':'over budget'})
 with pytest.raises(ValueError,match='budget'): scout.scan(env)


def test_automatic_discovery_obeys_opt_in_and_cache(worker,monkeypatch):
 env=vars(worker);calls=[];monkeypatch.setattr(scout,'LAST_AUTO_ATTEMPT',0)
 monkeypatch.setattr(scout,'scan',lambda _:calls.append(True))
 scout.auto_scan(env);assert not calls
 scout.save_settings(env,{'provider':'youtube','query':'stories','enabled':True})
 scout.auto_scan(env);scout.auto_scan(env);assert len(calls)==1


def test_routes_csrf_import_requires_rights_and_refuses_duplicates(worker,monkeypatch):
 monkeypatch.setenv('OPENAI_API_KEY','fixture')
 monkeypatch.setattr(worker,'media_status',lambda:{'ready':True})
 monkeypatch.setattr(worker.threading,'Thread',lambda **_:SimpleNamespace(start=lambda:None))
 with TestClient(worker.app,base_url='http://127.0.0.1:8765') as client:
  headers={'x-vyra-csrf':worker.APP_TOKEN};body={'url':'https://youtu.be/abcdefghijk','authorized':True}
  assert client.post('/api/sources/import',json=body).status_code==403
  assert client.post('/api/sources/import',headers=headers,json={**body,'authorized':False}).status_code==400
  result=client.post('/api/sources/import',headers=headers,json=body)
  assert result.status_code==200
  worker.JOBS.clear()
  assert client.post('/api/sources/import',headers=headers,json=body).status_code==409
  assert client.post('/api/sources/import',headers=headers,json={**body,'url':'https://youtu.be/zyxwvutsrqp'}).status_code==200
  assert client.post('/api/sources/import',headers=headers,json={**body,'url':'https://youtu.be/11111111111'}).status_code==429
  assert client.get('/api/queue').json()==[]


def test_import_flows_to_clipping_saves_provenance_and_removes_download(worker,monkeypatch):
 url='https://www.youtube.com/watch?v=abcdefghijk';job='a'*18
 worker.JOBS[job]={'status':'processing'}
 def download(_,folder):
  folder.mkdir();path=folder/'source.mp4';path.write_bytes(b'fixture');return path
 def process(source,scratch,output,*_):
  assert source.read_bytes()==b'fixture';output.mkdir();(output/'manifest.json').write_text('{"clips":[]}')
  return {'clips':[]}
 monkeypatch.setattr(scout,'download',download);monkeypatch.setattr(worker,'process_video',process)
 worker.do_source_job(job,url,3,20,60)
 assert worker.JOBS[job]['status']=='done'
 assert json.loads((worker.OUTPUT/job/'manifest.json').read_text())['source']['url']==url
 assert not (worker.WORK/(job+'-import')).exists()


def test_failed_import_cleans_partial_and_can_retry(worker,monkeypatch):
 job='a'*18;url='https://www.youtube.com/watch?v=abcdefghijk';worker.JOBS[job]={'status':'processing'}
 with worker.database() as conn:conn.execute('INSERT INTO source_imports VALUES (?,?,?)',(url,job,1))
 def fail(_,folder):folder.mkdir();(folder/'source.part').write_bytes(b'partial');raise ValueError('Restricted source')
 monkeypatch.setattr(scout,'download',fail);worker.do_source_job(job,url,3,20,60)
 assert worker.JOBS[job]['status']=='error' and not (worker.WORK/(job+'-import')).exists()
 with worker.database() as conn:assert conn.execute('SELECT * FROM source_imports').fetchone() is None


def test_twitch_secret_is_encrypted_and_never_returned(worker):
 saved=scout.save_settings(vars(worker),{'provider':'twitch','query':'Minecraft','client_id':'client','client_secret':'fixture-secret'})
 assert saved['twitch_configured'] and 'fixture-secret' not in json.dumps(saved)
 assert b'fixture-secret' not in worker.VAULT.data_path.read_bytes()


def test_rubric_uses_one_bounded_call_valid_ids_and_fixed_weights():
 calls=[]
 def create(**kwargs):
  calls.append(kwargs)
  return SimpleNamespace(output_text=json.dumps({'clips':[
   {'id':0,'ratings':{'hook':5,'payoff':4,'emotion':3,'standalone':4,'editability':5},'title':'A payoff'},
   {'id':99999,'ratings':{}},
   {'id':1,'ratings':{'hook':5,'payoff':1,'emotion':5,'standalone':1,'editability':5}},
  ]}))
 groups=[{'start':i*10,'end':i*10+10,'text':'But why? Here is the surprising result.'} for i in range(1200)]
 result=select_candidates(groups,12000,5,20,60,SimpleNamespace(responses=SimpleNamespace(create=create)),'fixture',lambda *_:None)
 assert len(calls)==1 and len(json.loads(calls[0]['input']))<=24
 assert 'tools' not in calls[0] and calls[0]['store'] is False
 assert len(result)==1 and result[0]['selection']=='rubric-v1' and result[0]['score']==83
 assert 0<=result[0]['start']<result[0]['end']<=12000


def test_rubric_failure_returns_honestly_labeled_excerpts():
 def fail(**_):raise ValueError('Unavailable')
 result=select_candidates([{'start':0,'end':20,'text':'An ordinary transcript excerpt.'}],20,1,12,30,SimpleNamespace(responses=SimpleNamespace(create=fail)),'fixture',lambda *_:None)
 assert result[0]['score'] is None and result[0]['selection']=='transcript'


def test_downloader_fixed_options_and_access_filters(tmp_path,monkeypatch):
 import deno,yt_dlp,media_tools
 seen={}
 class Downloader:
  def __init__(self,options):seen.update(options)
  def __enter__(self):return self
  def __exit__(self,*_):pass
  def download(self,urls):assert urls==['https://www.youtube.com/watch?v=abcdefghijk']
 monkeypatch.setattr(yt_dlp,'YoutubeDL',Downloader)
 monkeypatch.setattr(deno,'find_deno_bin',lambda:'/fixture/deno')
 monkeypatch.setattr(media_tools,'tool_path',lambda _:'/fixture/ffmpeg')
 scout._download_child('https://youtu.be/abcdefghijk',tmp_path)
 assert seen['noplaylist'] and seen['remote_components']==set() and seen['retries']==1
 assert 'cookiefile' not in seen and 'postprocessors' not in seen
 check=seen['match_filter']
 assert check({'duration':30}) is None
 assert check({'duration':7201}) and check({'has_drm':True,'duration':30}) and check({'is_live':True,'duration':30})
 with pytest.raises(ValueError,match='2 GB'):seen['progress_hooks'][0]({'downloaded_bytes':3*1024**3})


def test_download_timeout_uses_separate_process_without_shell(tmp_path,monkeypatch):
 import subprocess
 monkeypatch.setattr(scout.shutil,'disk_usage',lambda _:SimpleNamespace(free=4*1024**3))
 def run(args,**kwargs):
  assert '--download' in args and kwargs['timeout']==1200 and 'shell' not in kwargs
  raise subprocess.TimeoutExpired(args,1200)
 monkeypatch.setattr(scout.subprocess,'run',run)
 with pytest.raises(ValueError,match='timed out'):scout.download('https://youtu.be/abcdefghijk',tmp_path/'source')


def test_youtube_scout_batches_twenty_candidates_and_reads_only_metadata(monkeypatch):
 calls=[]
 def get(url,**kwargs):
  calls.append((url,kwargs));params=kwargs['params']
  if url.endswith('/search'):
   assert params['maxResults']==20 and params['type']=='video'
   return {'items':[{'id':{'videoId':'abcdefghijk'}}]}
  if url.endswith('/videos'):
   return {'items':[{'id':'abcdefghijk','snippet':{'channelId':'channel','title':'Title','channelTitle':'Creator','publishedAt':'2026-10-22T00:00:00Z'},'statistics':{'viewCount':'1000'}}]}
  if url.endswith('/channels'):return {'items':[{'id':'channel','statistics':{'subscriberCount':'100'}}]}
  pytest.fail(url)
 monkeypatch.setattr(scout,'get_json',get)
 result=scout.youtube(SimpleNamespace(token=lambda _:('fixture',{})),'stories',datetime.now(timezone.utc))
 assert len(calls)==3 and result[0]['subscribers']=='100' and result[0]['likes'] is None


def test_invalid_twitch_config_does_not_change_saved_pattern(worker):
 env=vars(worker);before=scout.settings(env)
 with pytest.raises(ValueError):scout.save_settings(env,{'provider':'twitch','query':'game','client_id':'incomplete'})
 assert scout.settings(env)==before
