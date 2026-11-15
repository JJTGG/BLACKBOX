from __future__ import annotations
import json, socket, uuid
from datetime import datetime, timedelta, timezone
from typing import Callable
from .core import Store, utc_now

def expires(minutes=5): return (datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat().replace('+00:00','Z')
class TaskWorker:
    def __init__(self,store,worker_id=None,lease_minutes=5,max_attempts=3):
        self.store,self.worker_id,self.lease_minutes,self.max_attempts=store,worker_id or f'{socket.gethostname()}:{uuid.uuid4()}',lease_minutes,max_attempts
        with store.lock,store.db:
            for name,definition in [('lease_owner','TEXT'),('lease_until','TEXT'),('last_error','TEXT')]:
                if not self._has(name): store.db.execute(f'ALTER TABLE tasks ADD COLUMN {name} {definition}')
    def _has(self,name): return any(row['name']==name for row in self.store.db.execute('PRAGMA table_info(tasks)'))
    def enqueue(self,incident_id,agent,task,revision):
        task_id=str(uuid.uuid4())
        with self.store.lock,self.store.db:
            now=utc_now(); self.store.db.execute('INSERT INTO tasks(task_id,incident_id,agent,task,status,attempts,revision,output,created_at,updated_at,lease_owner,lease_until,last_error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(task_id,incident_id,agent,task,'pending',0,revision,None,now,now,None,None,None)); self.store.audit(incident_id,'orchestrator','task.enqueued','accepted',task_id,{'agent':agent,'task':task})
        return task_id
    def recover_expired(self):
        with self.store.lock,self.store.db:
            rows=self.store.db.execute("SELECT task_id,incident_id,attempts FROM tasks WHERE status='leased' AND lease_until < ?",(utc_now(),)).fetchall(); count=0
            for row in rows:
                status='failed' if row['attempts']>=self.max_attempts else 'pending'; self.store.db.execute('UPDATE tasks SET status=?,lease_owner=NULL,lease_until=NULL,updated_at=?,last_error=? WHERE task_id=? AND status=\'leased\'',(status,utc_now(),'lease expired' if status=='failed' else None,row['task_id'])); self.store.audit(row['incident_id'],self.worker_id,'task.recovery',status,row['task_id'],{'attempts':row['attempts']}); count+=1
            return count
    def claim(self):
        with self.store.lock,self.store.db:
            self.recover_expired(); row=self.store.db.execute("SELECT * FROM tasks WHERE status='pending' AND attempts < ? ORDER BY created_at LIMIT 1",(self.max_attempts,)).fetchone()
            if not row:return None
            lease=expires(self.lease_minutes); changed=self.store.db.execute("UPDATE tasks SET status='leased',attempts=attempts+1,lease_owner=?,lease_until=?,updated_at=? WHERE task_id=? AND status='pending'",(self.worker_id,lease,utc_now(),row['task_id'])).rowcount
            if not changed:return None
            claimed=dict(row); claimed.update(status='leased',lease_owner=self.worker_id,lease_until=lease,attempts=row['attempts']+1); self.store.audit(claimed['incident_id'],self.worker_id,'task.claimed','accepted',claimed['task_id'],{'lease_until':lease}); return claimed
    def heartbeat(self,task_id):
        with self.store.lock,self.store.db:
            changed=self.store.db.execute("UPDATE tasks SET lease_until=?,updated_at=? WHERE task_id=? AND status='leased' AND lease_owner=? AND lease_until >= ?",(expires(self.lease_minutes),utc_now(),task_id,self.worker_id,utc_now())).rowcount
            if not changed: raise RuntimeError('lease lost')
            return True
    def complete(self,task_id,output):
        with self.store.lock,self.store.db:
            changed=self.store.db.execute("UPDATE tasks SET status='completed',output=?,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE task_id=? AND status='leased' AND lease_owner=? AND lease_until >= ?",(json.dumps(output,sort_keys=True),utc_now(),task_id,self.worker_id,utc_now())).rowcount
            if not changed: raise RuntimeError('lease lost or task not owned')
            self.store.audit(None,self.worker_id,'task.completed','accepted',task_id)
    def fail(self,task_id,error):
        with self.store.lock,self.store.db:
            row=self.store.db.execute("SELECT incident_id,attempts FROM tasks WHERE task_id=? AND status='leased' AND lease_owner=? AND lease_until >= ?",(task_id,self.worker_id,utc_now())).fetchone()
            if not row: raise RuntimeError('lease lost or task not owned')
            status='pending' if row['attempts']<self.max_attempts else 'failed'; self.store.db.execute('UPDATE tasks SET status=?,last_error=?,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE task_id=?',(status,error[:500],utc_now(),task_id)); self.store.audit(row['incident_id'],self.worker_id,'task.failed',status,task_id,{'attempts':row['attempts']})
    def run_once(self,handler:Callable[[dict],dict]):
        task=self.claim()
        if not task:return False
        try:self.complete(task['task_id'],handler(task))
        except Exception as exc:
            try:self.fail(task['task_id'],type(exc).__name__)
            except RuntimeError: pass
        return True
