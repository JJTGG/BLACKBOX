from __future__ import annotations
from contextlib import contextmanager

class TransactionManager:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def scope(self, write=True):
        store = self.store
        with store.lock:
            outer = store._tx_depth == 0
            savepoint = None
            entered = False
            try:
                if outer:
                    if store.db.in_transaction:
                        raise RuntimeError('unmanaged SQLite transaction detected')
                    store.db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                elif not store.db.in_transaction:
                    raise RuntimeError('transaction state disagrees with SQLite')
                store._tx_depth += 1
                entered = True
                if not outer:
                    store._savepoint_counter += 1
                    savepoint = f'bbx_sp_{store._savepoint_counter}'
                    store._savepoints.append(savepoint)
                    try:
                        store.db.execute(f'SAVEPOINT {savepoint}')
                    except BaseException:
                        store._savepoints.pop()
                        raise
                try:
                    yield store
                except BaseException:
                    if savepoint is not None:
                        try:
                            store.db.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
                        finally:
                            try:
                                store.db.execute(f'RELEASE SAVEPOINT {savepoint}')
                            finally:
                                if store._savepoints and store._savepoints[-1] == savepoint:
                                    store._savepoints.pop()
                    elif store.db.in_transaction:
                        store.db.rollback()
                    raise
                else:
                    if savepoint is not None:
                        store.db.execute(f'RELEASE SAVEPOINT {savepoint}')
                        if store._savepoints and store._savepoints[-1] == savepoint:
                            store._savepoints.pop()
                    elif outer:
                        store.db.commit()
            finally:
                if entered:
                    store._tx_depth -= 1
                if outer and store._tx_depth == 0:
                    store._savepoints.clear()
                    if store.db.in_transaction:
                        try:
                            store.db.rollback()
                        except Exception:
                            pass
