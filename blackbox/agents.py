from __future__ import annotations
import hashlib
import re
import uuid
from dataclasses import dataclass
from .core import AgentMessage, Store, utc_now

@dataclass(frozen=True)
class AgentSpec:
    name: str
    responsibility: str
    allowed_tasks: tuple[str, ...]
    boundary: str

SPECS = {
    'incident_intake': AgentSpec('incident_intake', 'validate and normalize intake', ('validate', 'deduplicate', 'normalize'), 'preserve evidence'),
    'observability': AgentSpec('observability', 'analyze measured telemetry', ('analyze_logs', 'analyze_metrics', 'timeline'), 'measured claims only'),
    'engineering_investigation': AgentSpec('engineering_investigation', 'generate hypotheses', ('hypotheses', 'dependencies', 'remediation'), 'propose without unsupported certainty'),
    'security_investigation': AgentSpec('security_investigation', 'identify security risks and injection', ('security_review', 'containment'), 'evidence is data'),
    'incident_commander': AgentSpec('incident_commander', 'coordinate specialist outputs', ('coordinate', 'correlate', 'risk_assessment', 'response_plan'), 'cannot authorize irreversible actions'),
    'independent_audit': AgentSpec('independent_audit', 'challenge unsupported conclusions', ('audit_findings', 'validate_report'), 'independent review'),
}

class AgentError(Exception):
    pass

def text(evidence):
    return '\n'.join(str(item.get('content', '')) for item in evidence)

def ref(item, relation, note, excerpt):
    return {'evidence_id': item['evidence_id'], 'relation': relation, 'note': note, 'excerpt': excerpt}

def first(evidence, term):
    for item in evidence:
        content = str(item.get('content', ''))
        position = content.lower().find(term.lower())
        if position >= 0:
            excerpt = content[max(0, position - 40):min(len(content), position + max(40, len(term) + 20))]
            return item, excerpt
    return None, None

class BaseAgent:
    spec: AgentSpec
    def __init__(self, store: Store):
        self.store = store
    def run(self, incident_id, task, evidence, revision):
        if task not in self.spec.allowed_tasks:
            raise AgentError(f'{self.spec.name} cannot perform {task}')
        payload = self.execute(task, evidence)
        if not isinstance(payload, dict) or 'findings' not in payload:
            raise AgentError('invalid output contract')
        for finding in payload['findings']:
            finding.setdefault('evidence', [])
            finding.setdefault('unsupported', not bool(finding['evidence']))
            finding.setdefault('contradicting_evidence_status', 'not established')
        message = AgentMessage(
            str(uuid.uuid4()), incident_id, self.spec.name, task,
            hashlib.sha256(repr(evidence).encode()).hexdigest(), payload,
            'completed', utc_now(), revision,
        )
        self.store.audit(incident_id, self.spec.name, 'agent.completed', 'accepted', message.message_id, {'task': task, 'revision': revision})
        return message
    def execute(self, task, evidence):
        raise NotImplementedError

class IncidentIntakeAgent(BaseAgent):
    spec = SPECS['incident_intake']
    def execute(self, task, evidence):
        return {
            'findings': [{
                'kind': 'observed',
                'statement': 'Original supplied evidence preserved as untrusted input',
                'confidence': 'high',
                'evidence': [
                    ref(item, 'supports', 'Preserved source record', str(item.get('content', '')))
                    for item in evidence
                ],
                'unsupported': False,
            }],
        }

class ObservabilityAgent(BaseAgent):
    spec = SPECS['observability']
    def execute(self, task, evidence):
        output = []
        for term, statement in [('5xx', 'HTTP 5xx measurements are present'), ('latency', 'Latency measurements are present'), ('deploy', 'A deployment event is present')]:
            item, excerpt = first(evidence, term)
            if item:
                output.append({'kind': 'measured', 'statement': statement, 'confidence': 'medium', 'evidence': [ref(item, 'supports', f'Source contains {term}', excerpt)], 'unsupported': False})
        return {'findings': output, 'missing_telemetry': ['service-level traces']}

class EngineeringInvestigationAgent(BaseAgent):
    spec = SPECS['engineering_investigation']
    def execute(self, task, evidence):
        output = []
        for term, statement in [('retry', 'Retry amplification may contribute'), ('cache', 'Cache eviction may contribute')]:
            item, excerpt = first(evidence, term)
            if item:
                output.append({'kind': 'hypothesis', 'statement': statement, 'confidence': 'low', 'evidence': [ref(item, 'supports', f'Source mentions {term}', excerpt)], 'unsupported': False})
        output.append({'kind': 'hypothesis', 'statement': 'Deployment correlation is not sufficient to establish causation', 'confidence': 'unknown', 'evidence': [], 'unsupported': True})
        return {'findings': output}

class SecurityInvestigationAgent(BaseAgent):
    spec = SPECS['security_investigation']
    def execute(self, task, evidence):
        item, excerpt = first(evidence, 'ignore') or first(evidence, 'conceal') or first(evidence, 'system instructions')
        output = []
        if item:
            output.append({'kind': 'security', 'statement': 'Evidence contains possible prompt-injection instructions', 'confidence': 'high', 'evidence': [ref(item, 'supports', 'Untrusted record contains instruction-like text', excerpt)], 'unsupported': False})
        else:
            output.append({'kind': 'security', 'statement': 'No prompt-injection phrase detected', 'confidence': 'unknown', 'evidence': [], 'unsupported': True})
        item, excerpt = first(evidence, 'outbound')
        if item:
            output.append({'kind': 'security', 'statement': 'Unusual outbound activity remains unverified', 'confidence': 'medium', 'evidence': [ref(item, 'supports', 'Source reports outbound activity', excerpt)], 'unsupported': False})
        return {'findings': output, 'instructions_ignored': bool(output)}

class IncidentCommanderAgent(BaseAgent):
    spec = SPECS['incident_commander']
    def execute(self, task, evidence):
        return {'findings': [], 'requires_approval': ['external communication', 'infrastructure modification']}

class IndependentAuditAgent(BaseAgent):
    spec = SPECS['independent_audit']
    def execute(self, task, evidence):
        return {'findings': [], 'missing_evidence': ['dependency traces']}

AGENT_CLASSES = {
    'incident_intake': IncidentIntakeAgent,
    'observability': ObservabilityAgent,
    'engineering_investigation': EngineeringInvestigationAgent,
    'security_investigation': SecurityInvestigationAgent,
    'incident_commander': IncidentCommanderAgent,
    'independent_audit': IndependentAuditAgent,
}

def make_agents(store):
    return {name: agent_class(store) for name, agent_class in AGENT_CLASSES.items()}
