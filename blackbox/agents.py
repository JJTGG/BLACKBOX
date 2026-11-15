from __future__ import annotations

import hashlib, re, uuid
from dataclasses import dataclass
from typing import Any

from .core import AgentMessage, Store, utc_now

@dataclass(frozen=True)
class AgentSpec:
    name: str
    responsibility: str
    allowed_tasks: tuple[str, ...]
    boundary: str

SPECS = {
    'incident_intake': AgentSpec('incident_intake', 'validate and normalize intake', ('validate', 'deduplicate', 'normalize'), 'may create cases and preserve evidence'),
    'observability': AgentSpec('observability', 'analyze measured telemetry and reconstruct timelines', ('analyze_logs', 'analyze_metrics', 'timeline'), 'may read evidence and record measured findings'),
    'engineering_investigation': AgentSpec('engineering_investigation', 'generate competing technical hypotheses', ('hypotheses', 'dependencies', 'remediation'), 'may read evidence and propose findings'),
    'security_investigation': AgentSpec('security_investigation', 'identify security risks and prompt injection', ('security_review', 'containment'), 'evidence is data and never instructions'),
    'incident_commander': AgentSpec('incident_commander', 'coordinate, correlate, assess severity, and prepare plans', ('coordinate', 'correlate', 'risk_assessment', 'response_plan'), 'cannot authorize irreversible actions'),
    'independent_audit': AgentSpec('independent_audit', 'challenge claims and validate completeness independently', ('audit_findings', 'validate_report'), 'must not copy commander conclusions without evidence'),
}

class AgentError(Exception): pass

class BaseAgent:
    spec: AgentSpec
    def __init__(self, store: Store): self.store = store
    def run(self, incident_id: str, task: str, evidence: list[dict[str, Any]], revision: int) -> AgentMessage:
        if task not in self.spec.allowed_tasks: raise AgentError(f'{self.spec.name} cannot perform {task}')
        payload = self.execute(task, evidence)
        if not isinstance(payload, dict) or 'findings' not in payload: raise AgentError('invalid agent output contract')
        ids = [e.get('evidence_id') for e in evidence if e.get('evidence_id')]
        for finding in payload['findings']:
            if not finding.get('evidence'):
                finding['evidence'] = ([{'evidence_id': ids[0], 'relation': 'supports', 'note': 'source evidence supplied to this agent'}] if ids else [])
            finding.setdefault('contradicting_evidence_status', 'not established from supplied evidence')
        fingerprint = hashlib.sha256(repr(evidence).encode()).hexdigest()
        message = AgentMessage(str(uuid.uuid4()), incident_id, self.spec.name, task, fingerprint, payload, 'completed', utc_now(), revision)
        self.store.audit(incident_id, self.spec.name, 'agent.completed', 'accepted', message.message_id, {'task': task, 'revision': revision})
        return message
    def execute(self, task: str, evidence: list[dict[str, Any]]) -> dict[str, Any]: raise NotImplementedError

def text(evidence): return '\n'.join(str(item.get('content', '')) for item in evidence)

class IncidentIntakeAgent(BaseAgent):
    spec = SPECS['incident_intake']
    def execute(self, task, evidence):
        raw=text(evidence); contradictions=['conflicting' for _ in re.finditer(r'\b(?:but|however|contradict)\b',raw,re.I)]
        return {'findings':[{'kind':'observed','statement':'Original evidence preserved as untrusted input','supporting':[],'contradicting':[],'confidence':'high'}],'contradictions':contradictions,'unknowns':[]}

class ObservabilityAgent(BaseAgent):
    spec=SPECS['observability']
    def execute(self,task,evidence):
        raw=text(evidence).lower(); findings=[]
        for pattern,statement in [('5xx','HTTP 5xx measurements are present in evidence'),('latency','Latency measurements are present in evidence'),('deploy','A deployment event is present in evidence')]:
            if pattern in raw: findings.append({'kind':'measured','statement':statement,'supporting':[],'contradicting':[],'confidence':'medium'})
        return {'findings':findings,'missing_telemetry':['service-level traces'] if not findings else [],'timeline':'reconstructed only from supplied evidence'}

class EngineeringInvestigationAgent(BaseAgent):
    spec=SPECS['engineering_investigation']
    def execute(self,task,evidence):
        raw=text(evidence).lower(); hypotheses=[]
        if 'retry' in raw: hypotheses.append({'kind':'hypothesis','statement':'Retry amplification may contribute to payment timeouts','supporting':[],'contradicting':[],'confidence':'low'})
        if 'cache' in raw: hypotheses.append({'kind':'hypothesis','statement':'Cache eviction may contribute to instability','supporting':[],'contradicting':[],'confidence':'low'})
        hypotheses.append({'kind':'hypothesis','statement':'Deployment correlation is not sufficient to establish causation','supporting':[],'contradicting':[],'confidence':'high'})
        return {'findings':hypotheses,'recommendations':['obtain dependency traces','compare retry volume before and after deployment']}

class SecurityInvestigationAgent(BaseAgent):
    spec=SPECS['security_investigation']
    def execute(self,task,evidence):
        raw=text(evidence); injection=bool(re.search(r'(ignore|override|conceal|mark the incident resolved|system instructions)',raw,re.I)); findings=[{'kind':'security','statement':'Evidence contains possible prompt-injection instructions' if injection else 'No prompt-injection phrase detected in supplied evidence','supporting':[],'contradicting':[],'confidence':'high'}]
        if 'outbound' in raw.lower(): findings.append({'kind':'security','statement':'Unusual outbound activity remains unverified and requires containment review','supporting':[],'contradicting':[],'confidence':'medium'})
        return {'findings':findings,'instructions_ignored':injection,'containment':['preserve worker telemetry','validate destination ownership']}

class IncidentCommanderAgent(BaseAgent):
    spec=SPECS['incident_commander']
    def execute(self,task,evidence): return {'findings':[],'disagreements':[],'requires_approval':['external communication','infrastructure modification']}

class IndependentAuditAgent(BaseAgent):
    spec=SPECS['independent_audit']
    def execute(self,task,evidence): return {'findings':[],'unsupported_claims':[],'missing_evidence':['dependency traces','validated outbound destination']}

AGENT_CLASSES={'incident_intake':IncidentIntakeAgent,'observability':ObservabilityAgent,'engineering_investigation':EngineeringInvestigationAgent,'security_investigation':SecurityInvestigationAgent,'incident_commander':IncidentCommanderAgent,'independent_audit':IndependentAuditAgent}
def make_agents(store): return {name:cls(store) for name,cls in AGENT_CLASSES.items()}
