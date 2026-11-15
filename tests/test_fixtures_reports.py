import json
from blackbox.core import Role, Store, User
from blackbox.fixtures import seed
from blackbox.orchestrator import Orchestrator
from blackbox.reporting import build_report


def test_seed_cases_are_isolated_and_reports_preserve_unknowns():
    store = Store()
    seed(store)
    assert store.db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0] == 2
    assert store.db.execute("SELECT COUNT(*) FROM evidence WHERE incident_id='BBX-001'").fetchone()[0] == 6
    assert store.db.execute("SELECT COUNT(*) FROM evidence WHERE incident_id='BBX-002'").fetchone()[0] == 5
    report = build_report(store, 'BBX-001')
    assert report['confidence_assessments']['overall'] == 'low_to_medium'
    assert any('outbound' in item.lower() for item in report['outstanding_questions'])
    assert report['approval_history'] == []


def test_orchestration_creates_audited_findings_for_fixture():
    store = Store(); seed(store)
    rows = [dict(r) for r in store.db.execute("SELECT * FROM evidence WHERE incident_id='BBX-001'")]
    Orchestrator(store).run_case('BBX-001', rows, User('commander', Role.COMMANDER))
    assert store.db.execute("SELECT COUNT(*) FROM findings WHERE incident_id='BBX-001'").fetchone()[0] >= 4
    assert store.verify_audit_chain()
