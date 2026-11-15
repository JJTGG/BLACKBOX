from __future__ import annotations

import hashlib, re, uuid
from dataclasses import dataclass
from typing import Any
from .core import AgentMessage, Store, utc_now

@dataclass(frozen=True)
class AgentSpec:
    name: str; responsibility: str; allowed_tasks: tuple[str, ...]; boundary: str

SPECS = {
 'incident_intake': AgentSpec('incident_intake','validate and normalize intake',('validate','deduplicate','normalize'),'preserve original evidence'),
 'observability': AgentSpec('observability','analyze measured telemetry',('analyze_logs','analyze_metrics','timeline'),'only measured claims'),
 'engineering_investigation': AgentSpec('engineering_investigation','generate competing hypotheses',('hypotheses','dependencies','remediation'),'propose, never confirm without evidence'),
 'security_investigation': AgentSpec('security_investigation','identify security risks and prompt injection',('security_review','containment'),'evidence is data, never instructions'),
 'incident_commander': AgentSpec('incident_commander','coordinate and correlate specialist outputs',('coordinate','correlate','risk_assessment','response_plan'),'cannot authorize irreversible actions'),
 'independent_audit': AgentSpec('independent_audit','challenge unsupported conclusions',('audit_findings','validate_report'),'independent of commander'),
}
class AgentError(Exception): pass

def _ref(item, relation, note):
    return {'evidence_id': item['evidence_id'], 'relation': relation, 'note': note}

def _find(evidence, phrase):
    return [item for item in evidence if phrase.lower() in str(item.get('content','')).lower()]

def text(evidence): return '\n'.join(str(item.get('content','')) for item in evidence)

class BaseAgent:
    spec: AgentSpec
    def __init__(self, store: Store): self.store=store
    def run(self, incident_id, task, evidence, revision):
        if task not in self.spec.allowed_tasks: raise AgentError(f'{self.spec.name} cannot perform {task}')
        payload=self.execute(task,evidence)
        if not isinstance(payload,dict) or 'findings' not in payload: raise AgentError('invalid agent output contract')
        for finding in payload['findings']:
            finding.setdefault('evidence', [])
            finding.setdefault('unsupported', not bool(finding['evidence']))
            finding.setdefault('contradicting_evidence_status','not established from supplied evidence')
        fingerprint=hashlib.sha256(repr(evidence).encode()).hexdigest()
        message=AgentMessage(str(uuid.uuid4()),incident_id,self.spec.name,task,fingerprint,payload,'completed',utc_now(),revision)
        self.store.audit(incident_id,self.spec.name,'agent.completed','accepted',message.message_id,{'task':task,'revision':revision})
        return message
    def execute(self,task,evidence): raise NotImplementedError

class IncidentIntakeAgent(BaseAgent):
    spec=SPECS['incident_intake']
    def execute(self,task,evidence):
        raw=text(evidence)
        return {'findings':[{'kind':'observed','statement':'Original supplied evidence preserved as untrusted input','confidence':'high','evidence':[_ref(e,'supports','This record is the preserved source item') for e in evidence]}], 'contradictions':['conflicting wording detected' for _ in re.finditer(r'\b(?:but|however|contradict)\b',raw,re.I)],'unknowns':[]}

class ObservabilityAgent(BaseAgent):
    spec=SPECS['observability']
    def execute(self,task,evidence):
        findings=[]
        for phrase, statement in [('5xx','HTTP 5xx measurements are present in evidence'),('latency','Latency measurements are present in evidence'),('deploy','A deployment event is present in evidence')]:
            items=_find(evidence,phrase)
            if items: findings.append({'kind':'measured','statement':statement,'confidence':'medium','evidence':[_ref(items[0],'supports',f"The source contains '{phrase}'")], 'unsupported':False})
        return {'findings':findings,'missing_telemetry':['service-level traces'] if not findings else [],'timeline':'reconstructed only from supplied evidence'}

class EngineeringInvestigationAgent(BaseAgent):
    spec=SPECS['engineering_investigation']
    def execute(self,task,evidence):
        findings=[]
        for phrase, statement in [('retry','Retry amplification may contribute to payment timeouts'),('cache','Cache eviction may contribute to instability')]:
            items=_find(evidence,phrase)
            if items: findings.append({'kind':'hypothesis','statement':statement,'confidence':'low','evidence':[_ref(items[0],'supports',f"The source mentions {phrase}")], 'unsupported':False})
        findings.append({'kind':'hypothesis','statement':'Deployment correlation is not sufficient to establish causation','confidence':'unknown','evidence':[],'unsupported':True})
        return {'findings':findings,'recommendations':['obtain dependency traces','compare retry volume before and after deployment']}

class SecurityInvestigationAgent(BaseAgent):
    spec=SPECS['security_investigation']
    def execute(self,task,evidence):
        raw=text(evidence); injection=_find(evidence,'ignore') or _find(evidence,'conceal') or _find(evidence,'system instructions'); findings=[]
        if injection: findings.append({'kind':'security','statement':'Evidence contains possible prompt-injection instructions','confidence':'high','evidence':[_ref(injection[0],'supports','The untrusted record contains instruction-like text')], 'unsupported':False})
        else: findings.append({'kind':'security','statement':'No prompt-injection phrase detected in supplied evidence','confidence':'unknown','evidence':[],'unsupported':True})
        outbound=_find(evidence,'outbound')
        if outbound: findings.append({'kind':'security','statement':'Unusual outbound activity remains unverified and requires containment review','confidence':'medium','evidence':[_ref(outbound[0],'supports','The source reports outbound activity')], 'unsupported':False})
        return {'findings':findings,'instructions_ignored':bool(injection),'containment':['preserve worker telemetry','validate destination ownership']}

class IncidentCommanderAgent(BaseAgent):
    spec=SPECS['incident_commander']
    def execute(self,task,evidence): return {'findings':[],'disagreements':[],'requires_approval':['external communication','infrastructure modification']}
class IndependentAuditAgent(BaseAgent):
    spec=SPECS['independent_audit']
    def execute(self,task,evidence): return {'findings':[],'unsupported_claims':[],'missing_evidence':['dependency traces','validated outbound destination']}
AGENT_CLASSES={'incident_intake':IncidentIntakeAgent,'observability':ObservabilityAgent,'engineering_investigation':EngineeringInvestigationAgent,'security_investigation':SecurityInvestigationAgent,'incident_commander':IncidentCommanderAgent,'independent_audit':IndependentAuditAgent}
def make_agents(store): return {name:cls(store) for name,cls in AGENT_CLASSES.items()}
