import threading
from blackbox.transactional import TransactionalStore


def test_parallel_audit_appends_remain_chain_valid():
    store = TransactionalStore()
    errors=[]
    def write(i):
        try: store.audit('BBX-T', f'agent-{i}', 'test.event', 'accepted', metadata={'i': i})
        except Exception as exc: errors.append(exc)
    threads=[threading.Thread(target=write, args=(i,)) for i in range(20)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert not errors
    assert store.verify_audit_chain()
    assert store.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0] == 20
