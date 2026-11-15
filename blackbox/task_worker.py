from __future__ import annotations
import json,socket,uuid
from datetime import datetime,timedelta,timezone
from typing import Callable
from .core import Store,utc_now

def expires(minutes=5):return(datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat().replace('+00:00','Z')
class TaskWorker:
 def __init__(self,store,worker_id=None,lease_minutes=5,max_attempts=3):
  self.store,self.worker_id,self.lease_minutes,self.max_attempts=store,worker_id or f'{socket.gethostname()}:{uuid.uuid4()}',lease_minutes,max_attempts
  with store.transaction():
   for n,d in (('lease_owner','TEXT'),('lease_until','TEXT'),('last_error','TEXT'),('fence_token','TEXT'),('max_attempts','INTEGER')):
    if not self._has(n):store.db.execute(f'ALTER TABLE tasks ADD COLUMN {n} {d}')
 def _has(self,n):return any(r['name']==n for r in self.store.db.execute('PRAGMA table_info(tasks)'))
 def enqueue(self,incident_id,agent,task,revision):
  tid=str(uuid.uuid4());now=utc_now()
  with self.store.transaction():
   self.store.db.execute('INSERT INTO tasks(task_id,incident_id,agent,task,status,attempts,revision,output,created_at,updated_at,max_attempts,lease_owner,lease_until,last_error,fence_token) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tid,incident_id,agent,task,'pending',0,revision,None,now,now,self.max_attempts,None,None,None,None))
   self.store.audit(incident_id,'orchestrator','task.enqueued','accepted',tid,{'agent':agent,'task':task,'max_attempts':self.max_attempts})
  return tid
 def recover_expired(self):
  with self.store.transaction():
   rows=self.store.db.execute("SELECT task_id,incident_id,attempts,max_attempts FROM tasks WHERE status='leased' AND lease_until < ?",(utc_now(),)).fetchall();count=0
   for r in rows:
    budget=r['max_attempts'] or self.max_attempts;status='failed' if r['attempts']>=budget else 'pending';self.store.db.execute("UPDATE tasks SET status=?,lease_owner=NULL,lease_until=NULL,fence_token=NULL,updated_at=?,last_error=? WHERE task_id=? AND status='leased'",(status,utc_now(),'lease expired' if status=='failed' else None,r['task_id']));self.store.audit(r['incident_id'],self.worker_id,'task.recovery',status,r['task_id'],{'attempts':r['attempts'],'max_attempts':budget});count+=1
   return count
 def claim(self,task_id=None):
  with self.store.transaction():
   self.recover_expired();q="SELECT * FROM tasks WHERE status='pending' AND attempts < COALESCE(max_attempts,?)";p=[self.max_attempts]
   if task_id:q+=' AND task_id=?';p.append(task_id)
   q+=' ORDER BY created_at LIMIT 1';row=self.store.db.execute(q,p).fetchone()
   if not row:return None
   token=str(uuid.uuid4());lease=expires(self.lease_minutes);changed=self.store.db.execute("UPDATE tasks SET status='leased',attempts=attempts+1,lease_owner=?,lease_until=?,fence_token=?,updated_at=? WHERE task_id=? AND status='pending' AND attempts < COALESCE(max_attempts,?)",(self.worker_id,lease,token,utc_now(),row['task_id'],self.max_attempts)).rowcount
   if not changed:return None
   claimed=dict(row);claimed.update(status='leased',lease_owner=self.worker_id,lease_until=lease,fence_token=token,attempts=row['attempts']+1);self.store.audit(claimed['incident_id'],self.worker_id,'task.claimed','accepted',claimed['task_id'],{'fence_token':token,'max_attempts':row['max_attempts'] or self.max_attempts});return claimed
 def heartbeat(self,task_id,fence_token):
  with self.store.transaction():
   if not self.store.db.execute("UPDATE tasks SET lease_until=?,updated_at=? WHERE task_id=? AND status='leased' AND lease_owner=? AND fence_token=? AND lease_until >= ?",(expires(self.lease_minutes),utc_now(),task_id,self.worker_id,fence_token,utc_now())).rowcount:raise RuntimeError('lease lost')
 def complete(self,task_id,fence_token,output):
  with self.store.transaction():
   if not self.store.db.execute("UPDATE tasks SET status='completed',output=?,lease_owner=NULL,lease_until=NULL,fence_token=NULL,updated_at=? WHERE task_id=? AND status='leased' AND lease_owner=? AND fence_token=? AND lease_until >= ?",(json.dumps(output,sort_keys=True),utc_now(),task_id,self.worker_id,fence_token,utc_now())).rowcount:raise RuntimeError('lease lost or task not owned')
   self.store.audit(None,self.worker_id,'task.completed','accepted',task_id)
 def fail(self,task_id,fence_token,error):
  with self.store.transaction():
   row=self.store.db.execute("SELECT incident_id,attempts,max_attempts FROM tasks WHERE task_id=? AND status='leased' AND lease_owner=? AND fence_token=? AND lease_until >= ?",(task_id,self.worker_id,fence_token,utc_now())).fetchone()
   if not row:raise RuntimeError('lease lost or task not owned')
   budget=row['max_attempts'] or self.max_attempts;status='pending' if row['attempts']<budget else 'failed';self.store.db.execute('UPDATE tasks SET status=?,last_error=?,lease_owner=NULL,lease_until=NULL,fence_token=NULL,updated_at=? WHERE task_id=?',(status,error[:500],utc_now(),task_id));self.store.audit(row['incident_id'],self.worker_id,'task.failed',status,task_id,{'attempts':row['attempts'],'max_attempts':budget})
 def run_once(self,handler:Callable[[dict],dict]):
  task=self.claim()
  if not task:return False
  try:self.heartbeat(task['task_id'],task['fence_token']);self.complete(task['task_id'],task['fence_token'],handler(task))
  except Exception as exc:
   try:self.fail(task['task_id'],task['fence_token'],type(exc).__name__)
   except RuntimeError:pass
  return True
