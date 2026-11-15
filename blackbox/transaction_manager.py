from contextlib import contextmanager

class TransactionManager:
    """Savepoint-aware transaction state for a Store-owned SQLite connection."""
    def __init__(self, store):
        self.store = store

    @contextmanager
    def scope(self, write=True):
        with self.store.lock:
            outer = self.store._tx_depth == 0
            if outer:
                if self.store.db.in_transaction:
                    raise RuntimeError('unmanaged SQLite transaction detected')
                self.store.db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            elif not self.store.db.in_transaction:
                raise RuntimeError('transaction depth disagrees with SQLite state')
            self.store._tx_depth += 1
            savepoint = None
            if not outer:
                self.store._savepoint_counter += 1
                savepoint = f'bbx_sp_{self.store._savepoint_counter}'
                self.store._savepoints.append(savepoint)
                self.store.db.execute(f'SAVEPOINT {savepoint}')
            try:
                yield
                if savepoint:
                    self.store.db.execute(f'RELEASE SAVEPOINT {savepoint}')
                    self.store._savepoints.pop()
                self.store._tx_depth -= 1
                if outer:
                    self.store.db.commit()
            except BaseException:
                try:
                    if savepoint:
                        self.store.db.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
                        self.store.db.execute(f'RELEASE SAVEPOINT {savepoint}')
                        self.store._savepoints.pop()
                    elif self.store.db.in_transaction:
                        self.store.db.rollback()
                finally:
                    self.store._tx_depth = max(0, self.store._tx_depth - 1)
                    if outer:
                        self.store._savepoints.clear()
                raise
            finally:
                if outer and self.store._tx_depth == 0:
                    self.store._savepoints.clear()
