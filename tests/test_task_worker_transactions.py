import sqlite3
import tempfile
import os
import pytest
from blackbox.core import Store
from blackbox.task_worker import TaskWorker

def setup_store(path=':memory:'):
 s=Store(path);s.create_incident('TX-W','worker','test','ops');return s

def test_enqueue_audit_failure_rolls_back_task_and_audit():
 s=setup_store();original=s.audit
 def fail(*args,**kwargs):raise RuntimeError('audit failure')
 s.audit=fail
 with pytest.raises(RuntimeError,match='audit failure'):TaskWorker(s).enqueue('TX-W','agent','task',0)
 assert s.db.execute("SELECT COUNT(*) FROM tasks WHERE incident_id='TX-W'").fetchone()[0]==0
 assert s.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='task.enqueued'").fetchone()[0]==0
 s.audit=original

def test_claim_audit_failure_rolls_back_claim_and_recovery():
 fd,path=tempfile.mkstemp();os.close(fd)
 try:
  s=setup_store(path);w=TaskWorker(s,worker_id='w');tid=w.enqueue('TX-W','agent','task',0);first=w.claim(tid);s.db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE task_id=?",(tid,));w2=TaskWorker(s,worker_id='w2')
  original=s.audit;recovery_seen=[]
  def fail_claim(*args,**kwargs):
   event_type=kwargs.get('event_type',args[2] if len(args)>2 else None)
   if event_type=='task.recovery':
    recovery_seen.append(event_type);return original(*args,**kwargs)
   if event_type=='task.claimed':raise RuntimeError('claim audit failure')
   return original(*args,**kwargs)
  s.audit=fail_claim
  with pytest.raises(RuntimeError,match='claim audit failure'):w2.claim(tid)
  assert recovery_seen==['task.recovery']
  s.audit=original;s.db.close();r=Store(path);row=r.db.execute('SELECT status,lease_owner,attempts FROM tasks WHERE task_id=?',(tid,)).fetchone();assert row['status']=='leased' and row['lease_owner']=='w' and row['attempts']==1;assert r.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='task.recovery'").fetchone()[0]==0;assert r.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='task.claimed' AND resource=?",(tid,)).fetchone()[0]==1
 finally:os.unlink(path)

def test_recovery_inside_claim_is_one_outer_transaction():
 s=setup_store();w=TaskWorker(s,worker_id='w');tid=w.enqueue('TX-W','agent','task',0);w.claim(tid);s.db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE task_id=?",(tid,));seen=[]
 original=s.audit
 def observe(*args,**kwargs):
  event_type=kwargs.get('event_type',args[2] if len(args)>2 else None)
  seen.append((event_type,s._tx_depth,len(s._savepoints),s.db.in_transaction));return original(*args,**kwargs)
 s.audit=observe;claimed=w.claim(tid);assert claimed
 recovery=[x for x in seen if x[0]=='task.recovery'];claim=[x for x in seen if x[0]=='task.claimed'];assert recovery==[('task.recovery',2,1,True)];assert claim==[('task.claimed',1,0,True)]
 assert s.db.execute('SELECT status FROM tasks WHERE task_id=?',(tid,)).fetchone()['status']=='leased'
