import os
import sqlite3
import tempfile
import threading
import time

import pytest

from blackbox.core import DuplicateIncident, Store


def test_nested_success_commits_once_and_survives_reopen():
    fd, path = tempfile.mkstemp(); os.close(fd)
    try:
        store = Store(path)
        with store.transaction():
            store.db.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?)", ('TX-1','title','body','ops','intake','unknown',0,'tx-key','now','now'))
            with store.transaction():
                store.audit('TX-1', 'test', 'nested.event', 'accepted')
        store.db.close()
        reopened = Store(path)
        assert reopened.db.execute("SELECT COUNT(*) FROM incidents WHERE incident_id='TX-1'").fetchone()[0] == 1
        assert reopened.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='nested.event'").fetchone()[0] == 1
        assert reopened.verify_audit_chain()
    finally:
        os.unlink(path)


def test_outer_failure_rolls_back_domain_and_nested_audit():
    store = Store()
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.db.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?)", ('TX-2','title','body','ops','intake','unknown',0,'tx-key-2','now','now'))
            with store.transaction():
                store.audit('TX-2', 'test', 'nested.event', 'accepted')
            raise RuntimeError('force outer rollback')
    assert store.db.execute("SELECT COUNT(*) FROM incidents WHERE incident_id='TX-2'").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='nested.event'").fetchone()[0] == 0


def test_nested_failure_rolls_back_only_savepoint():
    store = Store()
    with store.transaction():
        store.db.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?)", ('TX-3','title','body','ops','intake','unknown',0,'tx-key-3','now','now'))
        with pytest.raises(RuntimeError):
            with store.transaction():
                store.audit('TX-3', 'test', 'discarded.event', 'accepted')
                raise RuntimeError('force nested rollback')
        store.audit('TX-3', 'test', 'kept.event', 'accepted')
    assert store.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='discarded.event'").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='kept.event'").fetchone()[0] == 1


def test_transaction_lock_serializes_shared_connection():
    store = Store(); entered = threading.Event(); release = threading.Event(); observed = []
    def first():
        with store.transaction():
            store.db.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?)", ('TX-4','title','body','ops','intake','unknown',0,'tx-key-4','now','now'))
            entered.set(); release.wait(2)
    def second():
        entered.wait(2); started = time.monotonic(); store.current_revision('TX-4')
        observed.append(time.monotonic() - started)
    a = threading.Thread(target=first); b = threading.Thread(target=second)
    a.start(); b.start(); assert entered.wait(2); time.sleep(0.05); assert not observed; release.set(); a.join(); b.join(); assert observed and observed[0] >= 0.04


def test_duplicate_rejection_audit_survives_reopen():
    fd, path = tempfile.mkstemp(); os.close(fd)
    try:
        store = Store(path); store.create_incident('TX-D1','same','same','ops')
        with pytest.raises(DuplicateIncident): store.create_incident('TX-D2','same','same','ops')
        assert store.db.execute("SELECT COUNT(*) FROM incidents WHERE incident_id='TX-D2'").fetchone()[0] == 0
        store.db.close(); reopened = Store(path)
        assert reopened.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='incident.create.rejected'").fetchone()[0] == 1
        assert reopened.verify_audit_chain()
    finally:
        os.unlink(path)
