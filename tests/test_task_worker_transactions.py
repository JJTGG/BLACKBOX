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
  original=s.audit
  def fail(*args,**kwargs):raise RuntimeError('claim audit failure')
  s.audit=fail
  with pytest.raises(RuntimeError,match='claim audit failure'):w2.claim(tid)
  s.audit=original;s.db.close();r=Store(path);row=r.db.execute('SELECT status,lease_owner,attempts FROM tasks WHERE task_id=?',(tid,)).fetchone();assert row['status']=='leased' and row['lease_owner']=='w' and row['attempts']==1;assert r.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='task.recovery'").fetchone()[0]==0
 finally:os.unlink(path)

def test_recovery_inside_claim_is_one_outer_transaction():
 s=setup_store();w=TaskWorker(s,worker_id='w');tid=w.enqueue('TX-W','agent','task',0);w.claim(tid);s.db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE task_id=?",(tid,));seen=[]
 original=s.audit
 def observe(*args,**kwargs):
  seen.append((s._tx_depth,len(s._savepoints)));return original(*args,**kwargs)
 s.audit=observe;claimed=w.claim(tid);assert claimed and seen and all(depth==2 for depth,_ in seen);assert s.db.execute('SELECT status FROM tasks WHERE task_id=?',(tid,)).fetchone()['status']=='leased'
