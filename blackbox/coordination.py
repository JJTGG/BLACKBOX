from __future__ import annotations

from .validation import CommanderReconciler, IndependentAuditor


def reconcile_specialist_outputs(messages, evidence_ids):
    """Incident Commander boundary: consume structured specialist messages."""
    return CommanderReconciler().reconcile(messages, evidence_ids)


def audit_commander_output(reconciliation, messages, evidence_ids):
    """Independent Audit boundary: inspect original messages and commander output."""
    return IndependentAuditor().review(reconciliation, messages, evidence_ids)
