from __future__ import annotations
import json, os, threading
from .agents import make_agents
from .core import Status, Store, User
from .message_store import MessageStore
from .validation import CommanderReconciler, IndependentAuditor
from .task_worker import TaskWorker

class Orchestrator:
    def __init__(self,store,max_attempts=2): self.store,self.max_attempts,self.agents=store,max_attempts,make_agents(store); self.messages=MessageStore(store); self.worker=TaskWorker(store,worker_id='orchestrator',max_attempts=max_attempts)
    def invoke(self,incident_id,agent_name,task,evidence,revision):
        if agent_name not in self.agents: raise KeyError(agent_name)
        self.store.audit(incident_id,'orchestrator','agent.invoked','started',metadata={'agent':agent_name,'task':task,'revision':revision})
        task_id=self.worker.enqueue(incident_id,agent_name,task,revision)
        claimed=self.worker.claim()
        if not claimed: raise RuntimeError('unable to claim durable agent task')
        try:
            msg=self.agents[agent_name].run(incident_id,task,evidence,revision); self.messages.save(msg); self.worker.complete(task_id,{'message_id':msg.message_id}); return self.messages.get(msg.message_id)
        except Exception as exc: self.worker.fail(task_id,type(exc).__name__); raise
    def run_case(self,incident_id,evidence,actor:User):
        self.store.authorize(actor,'investigate'); self.store.transition(incident_id,Status.VALIDATION,actor.user_id); self.store.transition(incident_id,Status.INVESTIGATION,actor.user_id); revision=self.store.current_revision(incident_id)
        messages=[self.invoke(incident_id,'incident_intake','validate',evidence,revision)]
        work=[('observability','analyze_logs'),('engineering_investigation','hypotheses'),('security_investigation','security_review')]
        with __import__('concurrent.futures').futures.ThreadPoolExecutor(max_workers=3) as pool: messages.extend(f.result() for f in [pool.submit(self.invoke,incident_id,a,t,evidence,revision) for a,t in work])
        ids={e['evidence_id'] for e in evidence}; reconciliation=CommanderReconciler().reconcile(messages,ids); audit=IndependentAuditor().review(reconciliation,messages,ids)
        self.store.audit(incident_id,'incident_commander','reconciliation.completed','accepted',metadata={'relationships':reconciliation['relationships']}); self.store.audit(incident_id,'independent_audit','reconciliation.reviewed',audit['status'],metadata={'rejected':audit['rejected']})
        if audit['status']=='rejected': raise ValueError('independent audit rejected reconciliation')
        self.store.transition(incident_id,Status.CORRELATION,'incident_commander'); self.store.transition(incident_id,Status.RISK_ASSESSMENT,'incident_commander'); self.store.transition(incident_id,Status.HUMAN_REVIEW,'incident_commander')
        return {'specialist_messages':messages,'reconciliation':reconciliation,'audit':audit}
    def request_sensitive_action(self,incident_id,action,actor): self.store.authorize(actor,'investigate'); return self.store.request_approval(incident_id,action,actor.user_id)
