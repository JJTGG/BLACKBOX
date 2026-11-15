import multiprocessing
import os
import queue
import tempfile
import threading

from blackbox.core import Store
from blackbox.task_worker import TaskWorker


def _claim_in_process(database_path, task_id, worker_id, barrier, results):
    store = Store(database_path)
    try:
        worker = TaskWorker(store, worker_id=worker_id)
        barrier.wait(timeout=20)
        task = worker.claim(task_id)
        results.put((worker_id, task is not None), timeout=10)
    finally:
        store.db.close()


def test_concurrent_claimers_get_one_task_only_once():
    store=Store(); store.create_incident('BBX-CLAIM','claim','test','ops')
    first=TaskWorker(store,worker_id='first'); second=TaskWorker(store,worker_id='second')
    first.enqueue('BBX-CLAIM','observability','timeline',0)
    claimed=[]
    threads=[threading.Thread(target=lambda w: claimed.append(w.claim()),args=(worker,)) for worker in (first,second)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len([task for task in claimed if task]) == 1


def test_multiprocess_claimers_get_one_task_only_once():
    fd, database_path = tempfile.mkstemp(suffix='.sqlite3')
    os.close(fd)
    context = multiprocessing.get_context('spawn')
    processes = []
    results = context.Queue()
    barrier = context.Barrier(2)
    try:
        store = Store(database_path)
        store.create_incident('BBX-MP-CLAIM', 'claim', 'test', 'ops')
        task_id = TaskWorker(store, worker_id='creator').enqueue(
            'BBX-MP-CLAIM', 'observability', 'timeline', 0,
        )
        store.db.close()

        for worker_id in ('process-first', 'process-second'):
            process = context.Process(
                target=_claim_in_process,
                args=(database_path, task_id, worker_id, barrier, results),
            )
            processes.append(process)
            process.start()

        claimed_by = []
        received = []
        try:
            for _ in processes:
                result = results.get(timeout=30)
                received.append(result)
                if result[1]:
                    claimed_by.append(result[0])
        finally:
            for process in processes:
                process.join(timeout=20)
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=10)

        assert len(received) == 2
        assert len(claimed_by) == 1
        assert all(process.exitcode == 0 for process in processes)

        reopened = Store(database_path)
        try:
            row = reopened.db.execute(
                'SELECT status,attempts,lease_owner FROM tasks WHERE task_id=?',
                (task_id,),
            ).fetchone()
            assert row['status'] == 'leased'
            assert row['attempts'] == 1
            assert row['lease_owner'] == claimed_by[0]
            assert reopened.db.execute(
                "SELECT COUNT(*) FROM audit WHERE event_type='task.claimed' AND resource=?",
                (task_id,),
            ).fetchone()[0] == 1
        finally:
            reopened.db.close()
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join(timeout=10)
        results.close()
        results.join_thread()
        try:
            os.unlink(database_path)
        except FileNotFoundError:
            pass
