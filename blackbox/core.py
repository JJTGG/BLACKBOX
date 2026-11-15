from __future__ import annotations

import hashlib, json, sqlite3, threading, uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class Role(str, Enum):
    ADMINISTRATOR = 'administrator'
    COMMANDER = 'incident_commander'
    INVESTIGATOR = 'investigator'
    APPROVER = 'approver'
    OBSERVER = 'observer'


class Status(str, Enum):
    INTAKE = 'intake'
    VALIDATION = 'validation'
    INVESTIGATION = 'investigation'
    CORRELATION = 'correlation'
    RISK_ASSESSMENT = 'risk_assessment'
    HUMAN_REVIEW = 'human_review'
    REPORTING = 'reporting'
    RESOLUTION = 'resolution'
    SUSPENDED = 'suspended'
    CANCELLED = 'cancelled'


TRANSITIONS: dict[Status, set[Status]] = {
    Status.INTAKE: {Status.VALIDATION, Status.CANCELLED},
    Status.VALIDATION: {Status.INVESTIGATION, Status.SUSPENDED, Status.CANCELLED},
    Status.INVESTIGATION: {Status.CORRELATION, Status.SUSPENDED, Status.CANCELLED},
    Status.CORRELATION: {Status.RISK_ASSESSMENT, Status.SUSPENDED},
    Status.RISK_ASSESSMENT: {Status.HUMAN_REVIEW, Status.SUSPENDED},
    Status.HUMAN_REVIEW: {Status.REPORTING, Status.INVESTIGATION, Status.SUSPENDED},
    Status.REPORTING: {Status.RESOLUTION, Status.HUMAN_REVIEW},
    Status.RESOLUTION: set(),
    Status.SUSPENDED: {Status.VALIDATION, Status.INVESTIGATION, Status.CANCELLED},
    Status.CANCELLED: set(),
}


@dataclass(frozen=True)
class User:
    user_id: str
    role: Role


@dataclass(frozen=True)
class AgentMessage:
    message_id: str
    incident_id: str
    agent: str
    task: str
    input_fingerprint: str
    output: dict[str, Any]
    status: str
    created_at: str
    revision: int


class AuthorizationError(Exception): pass
class InvalidTransition(Exception): pass
class StaleResult(Exception): pass
class DuplicateIncident(Exception): pass


class Store:
    """SQLite persistence boundary. All writes are transactional and audit chained."""
    def __init__(self, path: str = ':memory:'):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.execute('PRAGMA foreign_keys = ON')
        self.migrate()

    def migrate(self) -> None:
        with self.lock, self.db:
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS incidents(
              incident_id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
              category TEXT NOT NULL, status TEXT NOT NULL, severity TEXT NOT NULL,
              revision INTEGER NOT NULL DEFAULT 0, intake_key TEXT UNIQUE NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence(
              evidence_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents ON DELETE CASCADE,
              kind TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL,
              trusted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks(
              task_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents ON DELETE CASCADE,
              agent TEXT NOT NULL, task TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
              revision INTEGER NOT NULL, output TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS findings(
              finding_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents ON DELETE CASCADE,
              kind TEXT NOT NULL, statement TEXT NOT NULL, supporting TEXT NOT NULL,
              contradicting TEXT NOT NULL, confidence TEXT NOT NULL, source_agent TEXT NOT NULL,
              revision INTEGER NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approvals(
              approval_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents ON DELETE CASCADE,
              action TEXT NOT NULL, status TEXT NOT NULL, requested_by TEXT NOT NULL,
              decided_by TEXT, created_at TEXT NOT NULL, decided_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit(
              event_id TEXT PRIMARY KEY, incident_id TEXT, actor TEXT NOT NULL, event_type TEXT NOT NULL,
              outcome TEXT NOT NULL, resource TEXT, metadata TEXT NOT NULL, correlation_id TEXT NOT NULL,
              previous_hash TEXT, event_hash TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_incident ON evidence(incident_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_incident ON tasks(incident_id);
            CREATE INDEX IF NOT EXISTS idx_audit_incident ON audit(incident_id);
            ''')

    def audit(self, incident_id: str | None, actor: str, event_type: str, outcome: str,
              resource: str = '', metadata: dict[str, Any] | None = None) -> str:
        event_id, now, correlation = str(uuid.uuid4()), utc_now(), str(uuid.uuid4())
        previous = self.db.execute('SELECT event_hash FROM audit ORDER BY created_at DESC LIMIT 1').fetchone()
        previous_hash = previous['event_hash'] if previous else ''
        body = json.dumps({'event_id': event_id, 'incident_id': incident_id, 'actor': actor,
                           'event_type': event_type, 'outcome': outcome, 'resource': resource,
                           'metadata': metadata or {}, 'correlation_id': correlation,
                           'previous_hash': previous_hash, 'created_at': now}, sort_keys=True)
        event_hash = hashlib.sha256(body.encode()).hexdigest()
        self.db.execute('INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (event_id, incident_id, actor, event_type, outcome, resource,
                         json.dumps(metadata or {}, sort_keys=True), correlation, previous_hash, event_hash, now))
        return event_id

    def create_incident(self, incident_id: str, title: str, description: str, category: str,
                        severity: str = 'unknown', intake_key: str | None = None, actor: str = 'intake-agent') -> None:
        key = intake_key or hashlib.sha256(f'{title}|{description}'.strip().lower().encode()).hexdigest()
        now = utc_now()
        with self.lock, self.db:
            try:
                self.db.execute('INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (incident_id, title, description, category, Status.INTAKE.value, severity, 0, key, now, now))
            except sqlite3.IntegrityError as exc:
                self.audit(incident_id, actor, 'incident.create.rejected', 'duplicate', metadata={'intake_key': key})
                raise DuplicateIncident(incident_id) from exc
            self.audit(incident_id, actor, 'incident.created', 'accepted', metadata={'category': category})

    def add_evidence(self, incident_id: str, kind: str, content: str, metadata: dict[str, Any] | None = None,
                     actor: str = 'intake-agent') -> str:
        evidence_id = str(uuid.uuid4())
        with self.lock, self.db:
            self.db.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?)',
                            (evidence_id, incident_id, kind, content, json.dumps(metadata or {}, sort_keys=True), 0, utc_now()))
            self.audit(incident_id, actor, 'evidence.ingested', 'accepted', evidence_id,
                       {'kind': kind, 'untrusted': True})
        return evidence_id

    def transition(self, incident_id: str, target: Status, actor: str, result: dict[str, Any] | None = None) -> None:
        with self.lock, self.db:
            row = self.db.execute('SELECT status, revision FROM incidents WHERE incident_id=?', (incident_id,)).fetchone()
            if not row: raise KeyError(incident_id)
            current = Status(row['status'])
            if target not in TRANSITIONS[current]:
                self.audit(incident_id, actor, 'state.transition.rejected', 'invalid', metadata={'from': current.value, 'to': target.value})
                raise InvalidTransition(f'{current.value} -> {target.value}')
            revision = row['revision'] + 1
            self.db.execute('UPDATE incidents SET status=?, revision=?, updated_at=? WHERE incident_id=? AND revision=?',
                            (target.value, revision, utc_now(), incident_id, row['revision']))
            self.audit(incident_id, actor, 'state.transition', 'accepted', metadata={'from': current.value, 'to': target.value, 'result': result or {}})

    def current_revision(self, incident_id: str) -> int:
        row = self.db.execute('SELECT revision FROM incidents WHERE incident_id=?', (incident_id,)).fetchone()
        if not row: raise KeyError(incident_id)
        return int(row['revision'])

    def save_finding(self, incident_id: str, finding: dict[str, Any], actor: str, revision: int) -> str:
        with self.lock, self.db:
            current = self.current_revision(incident_id)
            if revision < current: raise StaleResult(f'revision {revision} < {current}')
            fid = str(uuid.uuid4())
            self.db.execute('INSERT INTO findings VALUES (?,?,?,?,?,?,?,?,?,?)',
                (fid, incident_id, finding['kind'], finding['statement'], json.dumps(finding.get('supporting', [])),
                 json.dumps(finding.get('contradicting', [])), finding.get('confidence', 'unknown'), actor, revision, utc_now()))
            self.audit(incident_id, actor, 'finding.recorded', 'accepted', fid, {'revision': revision})
            return fid

    def request_approval(self, incident_id: str, action: str, requested_by: str) -> str:
        aid = str(uuid.uuid4())
        with self.lock, self.db:
            self.db.execute('INSERT INTO approvals VALUES (?,?,?,?,?,?,?)',
                            (aid, incident_id, action, 'pending', requested_by, None, utc_now(), None))
            self.audit(incident_id, requested_by, 'approval.requested', 'pending', aid, {'action': action})
        return aid

    def decide_approval(self, approval_id: str, user: User, approve: bool) -> None:
        if user.role not in {Role.APPROVER, Role.ADMINISTRATOR}: raise AuthorizationError('approval role required')
        with self.lock, self.db:
            row = self.db.execute('SELECT incident_id, status FROM approvals WHERE approval_id=?', (approval_id,)).fetchone()
            if not row: raise KeyError(approval_id)
            if row['status'] != 'pending': raise ValueError('approval already decided')
            status = 'approved' if approve else 'rejected'
            self.db.execute('UPDATE approvals SET status=?, decided_by=?, decided_at=? WHERE approval_id=?',
                            (status, user.user_id, utc_now(), approval_id))
            self.audit(row['incident_id'], user.user_id, 'approval.decided', status, approval_id)

    def verify_audit_chain(self) -> bool:
        rows = self.db.execute('SELECT * FROM audit ORDER BY created_at, rowid').fetchall()
        previous = ''
        for row in rows:
            body = json.dumps({'event_id': row['event_id'], 'incident_id': row['incident_id'], 'actor': row['actor'],
                'event_type': row['event_type'], 'outcome': row['outcome'], 'resource': row['resource'],
                'metadata': json.loads(row['metadata']), 'correlation_id': row['correlation_id'],
                'previous_hash': row['previous_hash'], 'created_at': row['created_at']}, sort_keys=True)
            if row['previous_hash'] != previous or hashlib.sha256(body.encode()).hexdigest() != row['event_hash']:
                return False
            previous = row['event_hash']
        return True

    def authorize(self, user: User, action: str) -> None:
        allowed = {
            'create_incident': {Role.ADMINISTRATOR, Role.COMMANDER, Role.INVESTIGATOR},
            'investigate': {Role.ADMINISTRATOR, Role.COMMANDER, Role.INVESTIGATOR},
            'approve': {Role.ADMINISTRATOR, Role.APPROVER},
            'admin': {Role.ADMINISTRATOR},
            'observe': set(Role),
        }
        if user.role not in allowed.get(action, set()): raise AuthorizationError(f'{user.role} cannot {action}')
