import threading
from blackbox.core import Store
from blackbox.task_worker import TaskWorker


def test_concurrent_claimers_get_one_task_only_once():
    store=Store(); store.create_incident('BBX-CLAIM','claim','test','ops')
    first=TaskWorker(store,worker_id='first'); second=TaskWorker(store,worker_id='second')
    first.enqueue('BBX-CLAIM','observability','timeline',0)
    claimed=[]
    threads=[threading.Thread(target=lambda w: claimed.append(w.claim()),args=(worker,)) for worker in (first,second)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len([task for task in claimed if task]) == 1
