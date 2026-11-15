import os
import sqlite3
import tempfile

from blackbox.core import Store
from blackbox.task_worker import TaskWorker


def _legacy_task_schema(db):
    db.executescript('''
        CREATE TABLE tasks(
            task_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, agent TEXT NOT NULL,
            task TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL, output TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')


def _task_row(store, task_id):
    return store.db.execute(
        'SELECT status, attempts, max_attempts, lease_owner FROM tasks WHERE task_id=?',
        (task_id,),
    ).fetchone()


def test_legacy_records_are_backfilled_atomically_and_preserve_budgets():
    store = Store()
    store.create_incident('BBX-BUDGET', 'budget', 'test', 'ops')
    _legacy_task_schema(store.db)
    store.db.execute(
        "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?)",
        ('legacy', 'BBX-BUDGET', 'agent', 'task', 'pending', 0, 0, None,
         '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z'),
    )
    worker = TaskWorker(store, worker_id='first', max_attempts=4)
    assert _task_row(store, 'legacy')['max_attempts'] == 4

    worker.db = None if False else worker.store.db
    second = TaskWorker(store, worker_id='second', max_attempts=9)
    assert _task_row(store, 'legacy')['max_attempts'] == 4


def test_existing_null_budget_is_backfilled_and_non_null_is_unchanged():
    store = Store()
    store.create_incident('BBX-NULL', 'budget', 'test', 'ops')
    TaskWorker(store, worker_id='schema', max_attempts=5)
    now = '2025-01-01T00:00:00Z'
    store.db.execute(
        "INSERT INTO tasks(task_id,incident_id,agent,task,status,attempts,revision,output,created_at,updated_at,max_attempts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ('null', 'BBX-NULL', 'agent', 'task', 'pending', 0, 0, None, now, now, None),
    )
    store.db.execute(
        "INSERT INTO tasks(task_id,incident_id,agent,task,status,attempts,revision,output,created_at,updated_at,max_attempts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ('fixed', 'BBX-NULL', 'agent', 'task', 'pending', 0, 0, None, now, now, 2),
    )
    TaskWorker(store, worker_id='backfill', max_attempts=7)
    assert _task_row(store, 'null')['max_attempts'] == 7
    assert _task_row(store, 'fixed')['max_attempts'] == 2


def test_claim_recovery_and_failure_use_persisted_budget():
    store = Store()
    store.create_incident('BBX-AUTHORITATIVE', 'budget', 'test', 'ops')
    owner = TaskWorker(store, worker_id='owner', max_attempts=2)
    task_id = owner.enqueue('BBX-AUTHORITATIVE', 'agent', 'task', 0)
    first = owner.claim(task_id)
    assert first['attempts'] == 1
    store.db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE task_id=?", (task_id,))

    different = TaskWorker(store, worker_id='different', max_attempts=1)
    assert different.recover_expired() == 1
    assert _task_row(store, task_id)['status'] == 'pending'
    second = different.claim(task_id)
    assert second['attempts'] == 2
    store.db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE task_id=?", (task_id,))
    assert different.recover_expired() == 1
    row = _task_row(store, task_id)
    assert row['status'] == 'failed'
    assert row['attempts'] == 2
