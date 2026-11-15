from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .agents import BaseAgent, make_agents
from .core import Status, Store, User


class Orchestrator:
    """Application-level durable coordination boundary; no native agent runtime is assumed."""
    def __init__(self, store: Store, max_attempts: int = 2):
        self.store, self.max_attempts = store, max_attempts
        self.agents = make_agents(store)

    def invoke(self, incident_id: str, agent_name: str, task: str, evidence: list[dict[str, Any]], revision: int):
        if agent_name not in self.agents: raise KeyError(agent_name)
        self.store.audit(incident_id, 'orchestrator', 'agent.invoked', 'started', metadata={'agent': agent_name, 'task': task, 'revision': revision})
        for attempt in range(1, self.max_attempts + 1):
            try:
                message = self.agents[agent_name].run(incident_id, task, evidence, revision)
                for finding in message.output['findings']:
                    self.store.save_finding(incident_id, finding, agent_name, revision)
                return message
            except Exception as exc:
                self.store.audit(incident_id, agent_name, 'agent.failed', 'retry' if attempt < self.max_attempts else 'escalated', metadata={'attempt': attempt, 'error': type(exc).__name__})
                if attempt == self.max_attempts: raise

    def investigate_parallel(self, incident_id: str, evidence: list[dict[str, Any]], revision: int):
        work = [('observability', 'analyze_logs'), ('engineering_investigation', 'hypotheses'), ('security_investigation', 'security_review')]
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self.invoke, incident_id, agent, task, evidence, revision) for agent, task in work]
            return [future.result() for future in as_completed(futures)]

    def run_case(self, incident_id: str, evidence: list[dict[str, Any]], actor: User):
        self.store.authorize(actor, 'investigate')
        self.store.transition(incident_id, Status.VALIDATION, actor.user_id)
        self.store.transition(incident_id, Status.INVESTIGATION, actor.user_id)
        revision = self.store.current_revision(incident_id)
        self.invoke(incident_id, 'incident_intake', 'validate', evidence, revision)
        messages = self.investigate_parallel(incident_id, evidence, revision)
        self.invoke(incident_id, 'incident_commander', 'coordinate', evidence, revision)
        self.store.transition(incident_id, Status.CORRELATION, 'incident_commander')
        self.store.transition(incident_id, Status.RISK_ASSESSMENT, 'incident_commander')
        self.invoke(incident_id, 'independent_audit', 'audit_findings', evidence, self.store.current_revision(incident_id))
        self.store.transition(incident_id, Status.HUMAN_REVIEW, 'incident_commander')
        return messages

    def request_sensitive_action(self, incident_id: str, action: str, actor: User) -> str:
        self.store.authorize(actor, 'investigate')
        self.store.audit(incident_id, actor.user_id, 'action.proposed', 'blocked_pending_approval', metadata={'action': action})
        return self.store.request_approval(incident_id, action, actor.user_id)
