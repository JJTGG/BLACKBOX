from blackbox.core import Role, Status, Store, User


def test_approval_request_is_persisted_and_decidable():
    store = Store()
    store.create_incident('BBX-APPROVAL', 'Approval test', 'Test', 'governance')
    approval = store.request_approval('BBX-APPROVAL', 'deploy remediation', 'commander')
    assert store.db.execute('SELECT status FROM approvals WHERE approval_id=?', (approval,)).fetchone()[0] == 'pending'
    store.decide_approval(approval, User('approver', Role.APPROVER), False)
    assert store.db.execute('SELECT status FROM approvals WHERE approval_id=?', (approval,)).fetchone()[0] == 'rejected'


def test_investigation_progression_stops_at_human_review():
    store = Store()
    store.create_incident('BBX-LIFE', 'Lifecycle', 'Test', 'availability')
    for target in [Status.VALIDATION, Status.INVESTIGATION, Status.CORRELATION, Status.RISK_ASSESSMENT, Status.HUMAN_REVIEW]:
        store.transition('BBX-LIFE', target, 'commander')
    assert store.db.execute('SELECT status FROM incidents WHERE incident_id=?', ('BBX-LIFE',)).fetchone()[0] == Status.HUMAN_REVIEW.value
