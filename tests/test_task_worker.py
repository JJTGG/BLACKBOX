from blackbox.core import Store
from blackbox.task_worker import TaskWorker

def setup(incident):
 s=Store();s.create_incident(incident,'worker','test','ops');return s

def test_exact_claim_and_fencing():
 s=setup('BBX-W');w=TaskWorker(s,worker_id='same');first_id=w.enqueue('BBX-W','a','first',0);second_id=w.enqueue('BBX-W','a','second',0);first=w.claim(first_id);assert first['task_id']==first_id;w.complete(first_id,first['fence_token'],{});second=w.claim(second_id);assert second['task_id']==second_id;assert first['fence_token']!=second['fence_token']

def test_exhaustion_and_stale_owner():
 s=setup('BBX-X');old=TaskWorker(s,worker_id='same',max_attempts=1);tid=old.enqueue('BBX-X','a','t',0);first=old.claim(tid);s.db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE task_id=?",(tid,));new=TaskWorker(s,worker_id='same');assert new.recover_expired()==1;assert new.claim(tid) is None
