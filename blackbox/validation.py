from __future__ import annotations

import json, sqlite3, threading, uuid
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    relation: str
    note: str

class ContractError(ValueError): pass
class AuditRejected(ContractError): pass


def _refs(raw: list[dict[str, Any]], evidence_ids: set[str]) -> list[EvidenceRef]:
    result=[]
    for item in raw:
        if item.get('evidence_id') not in evidence_ids or item.get('relation') not in {'supports','contradicts'} or not item.get('note'):
            raise ContractError('finding evidence references must name known evidence and explain relation')
        result.append(EvidenceRef(item['evidence_id'], item['relation'], item['note']))
    return result


def validate_finding(finding: dict[str, Any], evidence_ids: set[str]) -> dict[str, Any]:
    if not finding.get('statement') or finding.get('confidence') not in {'unknown','low','medium','high'}:
        raise ContractError('finding requires statement and bounded confidence')
    refs=_refs(finding.get('evidence', []), evidence_ids)
    if not refs and finding.get('kind') in {'hypothesis','conclusion','assessment','security'}:
        raise ContractError('causal, security, and assessment findings require evidence references')
    return {**finding, 'evidence': [r.__dict__ for r in refs]}

class CommanderReconciler:
    """Consumes persisted specialist outputs; it does not infer from raw labels alone."""
    def reconcile(self, messages: list[dict[str, Any]], evidence_ids: set[str]) -> dict[str, Any]:
        findings=[]
        for message in messages:
            for finding in message.get('output', {}).get('findings', []):
                findings.append({**validate_finding(finding, evidence_ids), 'source_agent': message['agent'], 'message_id': message['message_id']})
        groups={}
        for finding in findings: groups.setdefault(finding['statement'], []).append(finding)
        disagreements=[]
        for statement, group in groups.items():
            sources={f['source_agent'] for f in group}
            if len(sources)>1: disagreements.append({'statement':statement,'sources':sorted(sources)})
        return {'findings': findings, 'disagreements': disagreements, 'requires_human_review': bool(disagreements), 'contributors': sorted({f['source_agent'] for f in findings})}

class IndependentAuditor:
    """Evaluates commander output against original specialist messages and evidence independently."""
    def review(self, reconciliation: dict[str, Any], messages: list[dict[str, Any]], evidence_ids: set[str]) -> dict[str, Any]:
        source_by_id={m['message_id']:m for m in messages}; rejected=[]; accepted=[]
        for finding in reconciliation.get('findings', []):
            try: validate_finding(finding, evidence_ids)
            except ContractError as exc: rejected.append({'statement':finding.get('statement',''), 'reason':str(exc)}); continue
            source=source_by_id.get(finding.get('message_id'))
            if not source or finding.get('source_agent') != source.get('agent'):
                rejected.append({'statement':finding['statement'],'reason':'missing or mismatched source message'}); continue
            accepted.append(finding)
        unsupported=[f['statement'] for f in reconciliation.get('findings', []) if f not in accepted]
        return {'status':'rejected' if rejected else 'accepted','accepted':accepted,'rejected':rejected,'unsupported':unsupported,'missing_evidence':[] if accepted else ['valid specialist evidence references']}
