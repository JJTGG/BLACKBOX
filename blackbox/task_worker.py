from __future__ import annotations

import json
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from .core import Store, utc_now


def expires(minutes: int = 5) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat().replace('+00:00', 'Z')


class TaskWorker:
    """Durable task queue using SQLite compare-and-set claims and expiring leases."""
    def __init__(self, store: Store, worker_id: str | None = None, lease_minutes: int = 5, max_attempts: int = 3):
        self.store, self.worker_id, self.lease_minutes, self.max_attempts = store, worker_id or f'{socket.gethostname()}:{uuid.uuid4()}', lease_minutes, max_attempts
        with self.store.lock, self.store.db:
            self.store.db.execute('ALTER TABLE tasks ADD COLUMN lease_owner TEXT') if not self._has('lease_owner') else None
            self.store.db.execute('ALTER TABLE tasks ADD COLUMN lease_until TEXT') if not self._has('lease_until') else None
            self.store.db.execute('ALTER TABLE tasks ADD COLUMN last_error TEXT') if not self._has('last_error') else None

    def _has(self, name: str) -> bool:
        return any(row['name'] == name for row in self.store.db.execute('PRAGMA table_info(tasks)'))

    def enqueue(self, incident_id: str, agent: str, task: str, revision: int) -> str:
        task_id = str(uuid.uuid4())
        with self.store.lock, self.store.db:
            self.store.db.execute('INSERT INTO tasks(task_id,incident_id,agent,task,status,attempts,revision,output,created_at,updated_at,lease_owner,lease_until,last_error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (task_id, incident_id, agent, task, 'pending', 0, revision, None, utc_now(), utc_now(), None, None, None))
            self.store.audit(incident_id, 'orchestrator', 'task.enqueued', 'accepted', task_id, {'agent': agent, 'task': task})
        return task_id

    def recover_expired(self) -> int:
        with self.store.lock, self.store.db:
            cursor = self.store.db.execute("UPDATE tasks SET status='pending', lease_owner=NULL, lease_until=NULL, updated_at=? WHERE status='leased' AND lease_until < ?", (utc_now(), utc_now()))
            if cursor.rowcount: self.store.audit(None, self.worker_id, 'task.recovery', 'accepted', metadata={'count': cursor.rowcount})
            return cursor.rowcount

    def claim(self) -> dict | None:
        with self.store.lock, self.store.db:
            self.recover_expired()
            row = self.store.db.execute("SELECT * FROM tasks WHERE status='pending' AND attempts < ? ORDER BY created_at LIMIT 1", (self.max_attempts,)).fetchone()
            if not row: return None
            lease = expires(self.lease_minutes)
            changed = self.store.db.execute("UPDATE tasks SET status='leased', attempts=attempts+1, lease_owner=?, lease_until=?, updated_at=? WHERE task_id=? AND status='pending'", (self.worker_id, lease, utc_now(), row['task_id'])).rowcount
            if not changed: return None
            claimed = dict(row); claimed.update(status='leased', lease_owner=self.worker_id, lease_until=lease, attempts=row['attempts'] + 1)
            self.store.audit(claimed['incident_id'], self.worker_id, 'task.claimed', 'accepted', claimed['task_id'], {'lease_until': lease})
            return claimed

    def complete(self, task_id: str, output: dict) -> None:
        with self.store.lock, self.store.db:
            changed = self.store.db.execute("UPDATE tasks SET status='completed', output=?, lease_owner=NULL, lease_until=NULL, updated_at=? WHERE task_id=? AND status='leased' AND lease_owner=?", (json.dumps(output, sort_keys=True), utc_now(), task_id, self.worker_id)).rowcount
            if not changed: raise RuntimeError('task is not leased by this worker')
            self.store.audit(None, self.worker_id, 'task.completed', 'accepted', task_id)

    def fail(self, task_id: str, error: str) -> None:
        with self.store.lock, self.store.db:
            row = self.store.db.execute('SELECT incident_id,attempts FROM tasks WHERE task_id=? AND lease_owner=?', (task_id, self.worker_id)).fetchone()
            if not row: raise RuntimeError('task is not leased by this worker')
            status = 'pending' if row['attempts'] < self.max_attempts else 'failed'
            self.store.db.execute('UPDATE tasks SET status=?, last_error=?, lease_owner=NULL, lease_until=NULL, updated_at=? WHERE task_id=?', (status, error[:500], utc_now(), task_id))
            self.store.audit(row['incident_id'], self.worker_id, 'task.failed', status, task_id, {'attempts': row['attempts']})

    def run_once(self, handler: Callable[[dict], dict]) -> bool:
        task = self.claim()
        if not task: return False
        try: self.complete(task['task_id'], handler(task))
        except Exception as exc: self.fail(task['task_id'], type(exc).__name__)
        return True
