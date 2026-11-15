import pytest
from blackbox.validation import CommanderReconciler, ContractError, IndependentAuditor


def msg(agent, mid, findings):
    return {'agent': agent, 'message_id': mid, 'output': {'findings': findings}}


def ref(eid, relation='supports'):
    return {'evidence_id': eid, 'relation': relation, 'note': 'directly observed in fixture'}


def test_commander_preserves_specialist_sources():
    messages = [msg('observability', 'm1', [{'kind': 'measured', 'statement': 'deployment correlated with errors', 'confidence': 'medium', 'evidence': [ref('e1')]}]), msg('engineering_investigation', 'm2', [{'kind': 'hypothesis', 'statement': 'infrastructure anomaly may contribute', 'confidence': 'low', 'evidence': [ref('e2')]}])]
    result = CommanderReconciler().reconcile(messages, {'e1', 'e2'})
    assert {x['source_agent'] for x in result['findings']} == {'observability', 'engineering_investigation'}


def test_finding_without_evidence_is_rejected():
    messages = [msg('engineering_investigation', 'm1', [{'kind': 'hypothesis', 'statement': 'confirmed root cause', 'confidence': 'high', 'evidence': []}])]
    with pytest.raises(ContractError): CommanderReconciler().reconcile(messages, {'e1'})


def test_audit_rejects_unsupported_finding():
    messages = [msg('observability', 'm1', [{'kind': 'measured', 'statement': 'observed', 'confidence': 'medium', 'evidence': [ref('e1')]}])]
    reconciliation = {'findings': [{'kind': 'conclusion', 'statement': 'unsupported conclusion', 'confidence': 'high', 'evidence': [], 'source_agent': 'observability', 'message_id': 'm1'}]}
    result = IndependentAuditor().review(reconciliation, messages, {'e1'})
    assert result['status'] == 'rejected'


def test_audit_rejects_mismatched_agent():
    messages = [msg('observability', 'm1', [{'kind': 'measured', 'statement': 'observed', 'confidence': 'medium', 'evidence': [ref('e1')]}])]
    reconciliation = {'findings': [{'kind': 'measured', 'statement': 'observed', 'confidence': 'medium', 'evidence': [ref('e1')], 'source_agent': 'commander', 'message_id': 'm1'}]}
    assert IndependentAuditor().review(reconciliation, messages, {'e1'})['status'] == 'rejected'
