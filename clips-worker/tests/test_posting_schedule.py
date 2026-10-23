import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from test_queue import worker,seed_clip_and_account
import posting_schedule as slots
import post_assistant


def second_clip(worker,body):
 folder=worker.OUTPUT/body['job_id'];path=folder/'manifest.json';data=json.loads(path.read_text())
 data['clips'].append({**data['clips'][0],'file':'clip_02.mp4'})
 path.write_text(json.dumps(data));(folder/'clip_02.mp4').write_bytes(b'second clip')
 return {**body,'filename':'clip_02.mp4'}


def test_manual_reservations_reject_nearby_time_but_allow_other_platform(worker,monkeypatch):
 body=seed_clip_and_account(worker,monkeypatch);other=second_clip(worker,body)
 first=datetime.now(timezone.utc)+timedelta(days=1)
 worker.make_post({**body,'confirm':True,'scheduled_at':first.isoformat()},True)
 with pytest.raises(worker.HTTPException) as error:
  worker.make_post({**other,'confirm':True,'scheduled_at':(first+timedelta(minutes=15)).isoformat()},True)
 assert error.value.status_code==409 and '90 minutes' in error.value.detail
 assert len(worker.read_posts())==1
 free=worker.make_post({**other,'confirm':True,'scheduled_at':(first+timedelta(minutes=90)).isoformat()},True)
 assert free['status']=='approved'
 cross=worker.make_post({**body,'platform':'facebook','visibility':'reels','confirm':True,'scheduled_at':first.isoformat()},True)
 assert cross['platform']=='facebook'


def test_concurrent_manual_reservations_cannot_take_same_slot(worker,monkeypatch):
 body=seed_clip_and_account(worker,monkeypatch);other=second_clip(worker,body)
 when=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
 def reserve(b):
  try:return worker.make_post({**b,'confirm':True,'scheduled_at':when},True)['id']
  except worker.HTTPException:return None
 with ThreadPoolExecutor(2) as pool:results=list(pool.map(reserve,[body,other]))
 assert sum(x is not None for x in results)==1 and len(worker.read_posts())==1


def test_reopened_overdue_queue_spaces_actual_delivery_not_old_schedule(worker,monkeypatch):
 body=seed_clip_and_account(worker,monkeypatch);other=second_clip(worker,body)
 now=datetime.now(timezone.utc)
 first=worker.make_post({**body,'confirm':True,'scheduled_at':(now+timedelta(days=1)).isoformat()},True)
 second=worker.make_post({**other,'confirm':True,'scheduled_at':(now+timedelta(days=1,minutes=90)).isoformat()},True)
 with worker.database() as conn:
  conn.execute("UPDATE postings SET scheduled_at=?",((now-timedelta(days=1)).isoformat(),))
 calls=[];monkeypatch.setattr(worker,'handle_post',lambda row:calls.append(row['id']) or {'id':'remote'})
 monkeypatch.setattr(worker,'maintenance',lambda:None)
 worker.deliver(first['id']);worker.deliver(second['id'])
 assert calls==[first['id']]
 saved=next(x for x in worker.read_posts() if x['id']==second['id'])
 assert saved['status']=='approved' and datetime.fromisoformat(saved['scheduled_at'])>=now+timedelta(minutes=89)
 # A new process/database connection still sees the actual delivery slot.
 with worker.database() as conn:
  occupied=slots.occupied(conn,'youtube')
  assert any(abs((when-now).total_seconds())<5 for when in occupied)


def test_transfers_serialized_globally_without_losing_queued_post(worker,monkeypatch):
 body=seed_clip_and_account(worker,monkeypatch)
 first=worker.make_post({**body,'confirm':True},False)
 second=worker.make_post({**body,'platform':'facebook','visibility':'reels','confirm':True},False)
 entered=threading.Event();finish=threading.Event();calls=[]
 def send(row):
  calls.append(row['id']);entered.set();assert finish.wait(5);return {'id':'remote'}
 monkeypatch.setattr(worker,'handle_post',send);monkeypatch.setattr(worker,'maintenance',lambda:None)
 thread=threading.Thread(target=worker.deliver,args=(first['id'],));thread.start();assert entered.wait(5)
 worker.deliver(second['id'])
 assert calls==[first['id']]
 assert next(x for x in worker.read_posts() if x['id']==second['id'])['status']=='approved'
 finish.set();thread.join(5);worker.deliver(second['id'])
 assert calls==[first['id'],second['id']]


def test_failed_attempt_not_automatically_retried_and_reserves_window(worker,monkeypatch):
 body=seed_clip_and_account(worker,monkeypatch);other=second_clip(worker,body)
 post=worker.make_post({**body,'confirm':True},False)
 monkeypatch.setattr(worker,'handle_post',lambda *_:(_ for _ in ()).throw(ValueError('Unknown remote result')))
 worker.deliver(post['id']);worker.deliver(post['id'])
 assert worker.read_posts()[0]['status']=='needs_review'
 with pytest.raises(worker.HTTPException,match='90 minutes'):worker.make_post({**other,'confirm':True},False)
 assert worker.clip_path(body['job_id'],body['filename']).exists()
 assert len(worker.library()[0]['clips'])==2


def test_cancelled_reservation_frees_time_and_restores_review_clip(worker,monkeypatch):
 body=seed_clip_and_account(worker,monkeypatch)
 post=worker.make_post({**body,'confirm':True},False)
 assert worker.library()==[] and worker.clip_path(body['job_id'],body['filename']).exists()
 worker.cancel(post['id'])
 assert len(worker.library()[0]['clips'])==1
 worker.make_post({**body,'confirm':True},False)


def test_failed_destination_verification_restores_library_while_preserving_file(worker,monkeypatch):
 body=seed_clip_and_account(worker,monkeypatch);post=worker.make_post({**body,'confirm':True},False)
 with worker.database() as conn:conn.execute("UPDATE postings SET status='submitted' WHERE id=?",(post['id'],))
 assert worker.library()==[]
 worker.store_checks({post['id']:{'verified':True,'state':'failed','checked_at':worker.utc_now()}})
 assert worker.library() and worker.clip_path(body['job_id'],body['filename']).exists()


def test_automatic_suggestion_includes_recent_actual_delivery(worker,monkeypatch):
 body=seed_clip_and_account(worker,monkeypatch);other=second_clip(worker,body)
 now=datetime.now(timezone.utc);post=worker.make_post({**body,'confirm':True},False)
 with worker.database() as conn:
  conn.execute("UPDATE postings SET status='submitted' WHERE id=?",(post['id'],))
  conn.execute('INSERT INTO delivery_slots VALUES (?,?,?)',(post['id'],'youtube',now.isoformat()))
 captured=[]
 monkeypatch.setattr(post_assistant,'choose_time',lambda platform,zone,history,queued:captured.extend(queued) or {'scheduled_at':(now+timedelta(hours=3)).isoformat()})
 monkeypatch.setattr(post_assistant,'account_history',lambda *_:{})
 monkeypatch.setattr(post_assistant,'create_copy',lambda *_:{'title':'Title','caption':'Caption','ai_generated':False})
 post_assistant.prepare(vars(worker),{**other,'timezone':'UTC'})
 assert now.isoformat() in captured


def test_next_free_handles_reservations_on_both_sides_and_exact_gap():
 now=datetime(2026,10,22,12,tzinfo=timezone.utc)
 assert slots.next_free(now,[now-timedelta(minutes=30),now+timedelta(minutes=90)])==now+timedelta(minutes=180)
 assert slots.next_free(now,[now-timedelta(minutes=90)])==now


def test_one_failed_destination_restores_clip_even_if_another_succeeded(worker,monkeypatch):
 body=seed_clip_and_account(worker,monkeypatch)
 first=worker.make_post({**body,'confirm':True},False)
 second=worker.make_post({**body,'platform':'facebook','visibility':'reels','confirm':True},False)
 with worker.database() as conn:conn.execute("UPDATE postings SET status='submitted'")
 worker.store_checks({first['id']:{'verified':True,'state':'public','checked_at':worker.utc_now()},second['id']:{'verified':True,'state':'failed','checked_at':worker.utc_now()}})
 assert worker.library() and worker.clip_path(body['job_id'],body['filename']).exists()
 assert next(x for x in worker.queue() if x['id']==second['id'])['local_copy']=='saved'
