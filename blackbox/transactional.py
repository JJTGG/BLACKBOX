from __future__ import annotations

import hashlib, json, threading
from .core import Store

class TransactionalStore(Store):
    """Store variant with explicit SQLite transactions and serialized audit-chain appends.

    A re-entrant process lock serializes audit head reads and inserts. SQLite's
    connection context commits successful mutations and rolls back exceptions;
    this variant uses DEFERRED transactions instead of autocommit, so a domain
    mutation and its audit event commit or roll back together.
    """
    def __init__(self, path=':memory:'):
        super().__init__(path)
        self.db.isolation_level = 'DEFERRED'
        self.audit_lock = threading.RLock()

    def audit(self, incident_id, actor, event_type, outcome, resource='', metadata=None):
        with self.audit_lock:
            return super().audit(incident_id, actor, event_type, outcome, resource, metadata)

    def audit_chain_head(self):
        with self.audit_lock:
            row = self.db.execute('SELECT event_hash FROM audit ORDER BY rowid DESC LIMIT 1').fetchone()
            return row['event_hash'] if row else ''
