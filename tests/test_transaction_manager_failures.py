import os
import sqlite3
import tempfile

import pytest

from blackbox.core import Store


def insert_incident(store, incident_id):
    store.db.execute(
        "INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?)",
        (incident_id, 'title', 'body', 'ops', 'intake', 'unknown', 0,
         f'key-{incident_id}', 'now', 'now'),
    )


def independent_count(path, table, value):
    db = sqlite3.connect(path)
    try:
        return db.execute(f"SELECT COUNT(*) FROM {table} WHERE incident_id=?", (value,)).fetchone()[0]
    finally:
        db.close()


def test_savepoint_creation_failure_restores_state_and_outer_remains_safe():
    store = Store()
    def fail(stage):
        if stage == 'savepoint':
            raise RuntimeError('savepoint injection')
    store._transaction_failure_injector = fail
    with store.transaction():
        insert_incident(store, 'FAIL-SP')
        with pytest.raises(RuntimeError, match='savepoint injection'):
            with store.transaction():
                insert_incident(store, 'NESTED-SP')
        assert store._tx_depth == 1
        assert store._savepoints == []
    assert store._tx_depth == 0
    assert store.db.execute("SELECT COUNT(*) FROM incidents WHERE incident_id='FAIL-SP'").fetchone()[0] == 1
    assert store.db.execute("SELECT COUNT(*) FROM incidents WHERE incident_id='NESTED-SP'").fetchone()[0] == 0


def test_release_failure_cannot_commit_nested_or_outer_work():
    fd, path = tempfile.mkstemp(); os.close(fd)
    try:
        store = Store(path)
        def fail(stage):
            if stage == 'release':
                raise RuntimeError('release injection')
        store._transaction_failure_injector = fail
        with pytest.raises(RuntimeError, match='release injection'):
            with store.transaction():
                insert_incident(store, 'FAIL-REL')
                with store.transaction():
                    insert_incident(store, 'NESTED-REL')
        assert store._tx_depth == 0
        assert store._savepoints == []
        assert store._connection_usable is False
        assert independent_count(path, 'incidents', 'FAIL-REL') == 0
        assert independent_count(path, 'incidents', 'NESTED-REL') == 0
    finally:
        try: store.db.close()
        except UnboundLocalError: pass
        os.unlink(path)


def test_caught_nested_release_failure_rejects_writes_and_outer_success():
    fd, path = tempfile.mkstemp(); os.close(fd)
    try:
        store = Store(path)
        def fail(stage):
            if stage == 'release':
                raise RuntimeError('release injection')
        store._transaction_failure_injector = fail
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            with store.transaction():
                insert_incident(store, 'CAUGHT-OUTER')
                with pytest.raises(RuntimeError, match='release injection'):
                    with store.transaction():
                        insert_incident(store, 'CAUGHT-NESTED')
                insert_incident(store, 'AFTER-FAILURE')
        assert store._tx_depth == 0
        assert store._savepoints == []
        assert store._connection_usable is False
        assert independent_count(path, 'incidents', 'CAUGHT-OUTER') == 0
        assert independent_count(path, 'incidents', 'CAUGHT-NESTED') == 0
        assert independent_count(path, 'incidents', 'AFTER-FAILURE') == 0
    finally:
        try: store.db.close()
        except UnboundLocalError: pass
        os.unlink(path)


def test_outer_commit_failure_rolls_back_and_preserves_original_error():
    fd, path = tempfile.mkstemp(); os.close(fd)
    try:
        store = Store(path)
        def fail(stage):
            if stage == 'commit':
                raise RuntimeError('commit injection')
        store._transaction_failure_injector = fail
        with pytest.raises(RuntimeError, match='commit injection'):
            with store.transaction():
                insert_incident(store, 'FAIL-COMMIT')
        assert store._tx_depth == 0
        assert store._savepoints == []
        assert store._connection_usable is False
        assert independent_count(path, 'incidents', 'FAIL-COMMIT') == 0
    finally:
        try: store.db.close()
        except UnboundLocalError: pass
        os.unlink(path)


def test_rollback_failure_preserves_original_error_and_marks_unusable():
    fd, path = tempfile.mkstemp(); os.close(fd)
    try:
        store = Store(path)
        def fail(stage):
            if stage == 'rollback':
                raise RuntimeError('rollback injection')
        store._transaction_failure_injector = fail
        with pytest.raises(ValueError, match='original failure'):
            with store.transaction():
                insert_incident(store, 'FAIL-ROLLBACK')
                raise ValueError('original failure')
        assert store._tx_depth == 0
        assert store._savepoints == []
        assert store._connection_usable is False
        assert independent_count(path, 'incidents', 'FAIL-ROLLBACK') == 0
    finally:
        try: store.db.close()
        except UnboundLocalError: pass
        os.unlink(path)
