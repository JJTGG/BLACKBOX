import time
from blackbox.core import Store
from blackbox.task_worker import TaskWorker


def test_worker_claims_completes_and_deduplicates_side_effect_path():
    store = Store(); store.create_incident('BBX-W', 'worker', 'test', 'ops')
    worker = TaskWorker(store, worker_id='w1', lease_minutes=1)
    task_id = worker.enqueue('BBX-W', 'observability', 'timeline', 0)
    task = worker.claim()
    assert task['task_id'] == task_id and task['attempts'] == 1
    worker.complete(task_id, {'findings': []})
    assert store.db.execute('SELECT status FROM tasks WHERE task_id=?', (task_id,)).fetchone()[0] == 'completed'
    assert worker.claim() is None


def test_worker_retries_then_marks_exhausted_failure():
    store = Store(); store.create_incident('BBX-W2', 'worker', 'test', 'ops')
    worker = TaskWorker(store, worker_id='w2', max_attempts=2)
    task_id = worker.enqueue('BBX-W2', 'observability', 'timeline', 0)
    assert worker.run_once(lambda _: (_ for _ in ()).throw(RuntimeError('boom')))
    assert worker.run_once(lambda _: (_ for _ in ()).throw(RuntimeError('boom')))
    assert store.db.execute('SELECT status,attempts FROM tasks WHERE task_id=?', (task_id,)).fetchone() == ('failed', 2) or store.db.execute('SELECT status FROM tasks WHERE task_id=?', (task_id,)).fetchone()[0] == 'failed'


def test_expired_lease_is_recoverable_by_new_worker():
    store = Store(); store.create_incident('BBX-W3', 'worker', 'test', 'ops')
    worker = TaskWorker(store, worker_id='old')
    task_id = worker.enqueue('BBX-W3', 'observability', 'timeline', 0)
    worker.claim()
    store.db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE task_id=?", (task_id,))
    replacement = TaskWorker(store, worker_id='new')
    assert replacement.claim()['task_id'] == task_id
