from __future__ import annotations

import json
from .core import Store


def build_report(store: Store, incident_id: str) -> dict:
    incident = store.db.execute('SELECT * FROM incidents WHERE incident_id=?', (incident_id,)).fetchone()
    if not incident: raise KeyError(incident_id)
    evidence = [dict(row) for row in store.db.execute('SELECT * FROM evidence WHERE incident_id=? ORDER BY created_at', (incident_id,))]
    findings = [dict(row) for row in store.db.execute('SELECT * FROM findings WHERE incident_id=? ORDER BY created_at', (incident_id,))]
    approvals = [dict(row) for row in store.db.execute('SELECT * FROM approvals WHERE incident_id=? ORDER BY created_at', (incident_id,))]
    audit = [dict(row) for row in store.db.execute('SELECT event_id,event_type,actor,outcome,resource,created_at FROM audit WHERE incident_id=? ORDER BY rowid', (incident_id,))]
    hypotheses = [f for f in findings if f['kind'] == 'hypothesis']
    security = [f for f in findings if f['kind'] == 'security']
    return {
        'executive_summary': incident['description'],
        'incident_overview': {'incident_id': incident['incident_id'], 'title': incident['title'], 'category': incident['category'], 'status': incident['status']},
        'severity_assessment': {'severity': incident['severity'], 'confidence': 'unknown', 'reason': 'No independent impact-calibration evidence supplied.'},
        'business_impact': 'Payment or authentication impact is reported in evidence; scope remains unverified.',
        'reconstructed_timeline': [{'at': item['created_at'], 'source': item['kind'], 'statement': item['content']} for item in evidence],
        'confirmed_facts': [f['statement'] for f in findings if f['kind'] in {'observed', 'measured'}],
        'competing_root_cause_hypotheses': [{'statement': h['statement'], 'supporting': json.loads(h['supporting']), 'contradicting': json.loads(h['contradicting']), 'confidence': h['confidence']} for h in hypotheses],
        'security_findings': [f['statement'] for f in security],
        'recommended_containment_actions': ['preserve evidence', 'require human approval before any external or infrastructure action'],
        'recovery_plan': ['validate dependencies and telemetry', 'review approved remediation after human review'],
        'remediation_priorities': [],
        'outstanding_questions': ['Which dependency or component caused the observed impact?', 'Is the outbound destination authorized?', 'What is the verified scope of business impact?'],
        'confidence_assessments': {'overall': 'low_to_medium', 'basis': 'Controlled fixture contains incomplete evidence and explicit unknowns.'},
        'approval_history': approvals,
        'audit_references': audit,
    }
