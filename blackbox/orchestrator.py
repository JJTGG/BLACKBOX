from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from .agents import make_agents
from .core import Status, Store, User
from .validation import CommanderReconciler, IndependentAuditor

class Orchestrator:
    def __init__(self, store: Store, max_attempts: int = 2): self.store,self.max_attempts,self.agents=store,max_attempts,make_agents(store)
    def invoke(self, incident_id, agent_name, task, evidence, revision):
        if agent_name not in self.agents: raise KeyError(agent_name)
        self.store.audit(incident_id,'orchestrator','agent.invoked','started',metadata={'agent':agent_name,'task':task,'revision':revision})
        for attempt in range(1,self.max_attempts+1):
            try:
                msg=self.agents[agent_name].run(incident_id,task,evidence,revision)
                self.store.audit(incident_id,agent_name,'agent.output.persisted','accepted',msg.message_id,{'task':task})
                return {'message_id':msg.message_id,'incident_id':msg.incident_id,'agent':msg.agent,'task':msg.task,'revision':msg.revision,'output':msg.output}
            except Exception as exc:
                self.store.audit(incident_id,agent_name,'agent.failed','retry' if attempt<self.max_attempts else 'escalated',metadata={'attempt':attempt,'error':type(exc).__name__})
                if attempt==self.max_attempts: raise
    def investigate_parallel(self,incident_id,evidence,revision):
        work=[('observability','analyze_logs'),('engineering_investigation','hypotheses'),('security_investigation','security_review')]
        with ThreadPoolExecutor(max_workers=3) as pool: return [f.result() for f in as_completed([pool.submit(self.invoke,incident_id,a,t,evidence,revision) for a,t in work])]
    def run_case(self,incident_id,evidence,actor:User):
        self.store.authorize(actor,'investigate'); self.store.transition(incident_id,Status.VALIDATION,actor.user_id); self.store.transition(incident_id,Status.INVESTIGATION,actor.user_id); rev=self.store.current_revision(incident_id)
        intake=self.invoke(incident_id,'incident_intake','validate',evidence,rev); specialists=self.investigate_parallel(incident_id,evidence,rev); messages=[intake,*specialists]; evidence_ids={e['evidence_id'] for e in evidence}
        reconciliation=CommanderReconciler().reconcile(messages,evidence_ids); self.store.audit(incident_id,'incident_commander','reconciliation.completed','accepted',metadata={'contributors':reconciliation['contributors'],'disagreements':reconciliation['disagreements']})
        audit=IndependentAuditor().review(reconciliation,messages,evidence_ids); self.store.audit(incident_id,'independent_audit','reconciliation.reviewed',audit['status'],metadata={'rejected':audit['rejected'],'unsupported':audit['unsupported']})
        if audit['status']=='rejected': raise ValueError('independent audit rejected reconciliation')
        self.store.transition(incident_id,Status.CORRELATION,'incident_commander'); self.store.transition(incident_id,Status.RISK_ASSESSMENT,'incident_commander'); self.store.transition(incident_id,Status.HUMAN_REVIEW,'incident_commander')
        return {'specialist_messages':messages,'reconciliation':reconciliation,'audit':audit}
    def request_sensitive_action(self,incident_id,action,actor):
        self.store.authorize(actor,'investigate'); self.store.audit(incident_id,actor.user_id,'action.proposed','blocked_pending_approval',metadata={'action':action}); return self.store.request_approval(incident_id,action,actor.user_id)
