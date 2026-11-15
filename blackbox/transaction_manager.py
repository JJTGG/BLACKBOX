from __future__ import annotations
from contextlib import contextmanager

class TransactionManager:
    def __init__(self, store):
        self.store = store

    def _inject(self, stage):
        hook = getattr(self.store, '_transaction_failure_injector', None)
        if hook:
            hook(stage)

    def _unusable(self, reason):
        self.store._connection_usable = False
        self.store._transaction_failure_reason = reason

    @contextmanager
    def scope(self, write=True):
        store = self.store
        with store.lock:
            if not getattr(store, '_connection_usable', True):
                raise RuntimeError('Store connection is unusable')
            outer = store._tx_depth == 0
            savepoint = None
            began = False
            entered = False
            try:
                if outer:
                    if store.db.in_transaction:
                        raise RuntimeError('unmanaged SQLite transaction detected')
                    self._inject('begin')
                    store.db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                    began = True
                elif not store.db.in_transaction:
                    raise RuntimeError('transaction state disagrees with SQLite')
                store._tx_depth += 1
                entered = True
                if not outer:
                    store._savepoint_counter += 1
                    savepoint = f'bbx_sp_{store._savepoint_counter}'
                    store._savepoints.append(savepoint)
                    try:
                        self._inject('savepoint')
                        store.db.execute(f'SAVEPOINT {savepoint}')
                    except BaseException:
                        if store._savepoints and store._savepoints[-1] == savepoint:
                            store._savepoints.pop()
                        raise
                try:
                    yield store
                except BaseException as original:
                    cleanup_error = None
                    try:
                        if savepoint:
                            self._inject('rollback')
                            store.db.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
                            self._inject('release_after_rollback')
                            store.db.execute(f'RELEASE SAVEPOINT {savepoint}')
                            if store._savepoints and store._savepoints[-1] == savepoint:
                                store._savepoints.pop()
                        elif began and store.db.in_transaction:
                            self._inject('rollback')
                            store.db.rollback()
                    except BaseException as exc:
                        cleanup_error = exc
                        self._unusable('transaction cleanup failed')
                    if cleanup_error:
                        raise original from cleanup_error
                    raise
                else:
                    if savepoint is not None:
                        try:
                            self._inject('release')
                            store.db.execute(f'RELEASE SAVEPOINT {savepoint}')
                            if store._savepoints and store._savepoints[-1] == savepoint:
                                store._savepoints.pop()
                        except BaseException:
                            self._unusable('savepoint release failed')
                            if store.db.in_transaction:
                                try:
                                    self._inject('rollback')
                                    store.db.rollback()
                                except BaseException:
                                    pass
                            raise
                    elif outer:
                        if not getattr(store, '_connection_usable', True):
                            raise RuntimeError('Store connection is unusable')
                        try:
                            self._inject('commit')
                            store.db.commit()
                        except BaseException as exc:
                            self._unusable('outer commit failed')
                            try:
                                self._inject('rollback')
                                store.db.rollback()
                            except BaseException as rollback_error:
                                raise exc from rollback_error
                            raise
            finally:
                if entered:
                    store._tx_depth = max(0, store._tx_depth - 1)
                if outer and store._tx_depth == 0:
                    store._savepoints.clear()
                    if began and store.db.in_transaction and getattr(store, '_connection_usable', True):
                        try:
                            store.db.rollback()
                        except BaseException:
                            self._unusable('implicit cleanup failed')
