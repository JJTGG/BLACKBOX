from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from .agents import make_agents
from .core import Status, User
from .message_store import MessageStore
from .finding_store import FindingStore
from .task_worker import TaskWorker
from .validation import CommanderReconciler, IndependentAuditor

class Orchestrator:
    def __init__(self, store, max_attempts=2):
        self.store=store
        self.agents=make_agents(store)
        self.messages=MessageStore(store)
        self.findings=FindingStore(store)
        self.worker=TaskWorker(store,worker_id='orchestrator',max_attempts=max_attempts)
    def invoke(self,incident_id,agent_name,task,evidence,revision):
        task_id=self.worker.enqueue(incident_id,agent_name,task,revision)
        claim=self.worker.claim(task_id)
        if not claim or claim['task_id']!=task_id: raise RuntimeError('exact task claim failed')
        fence=claim['fence_token']
        try:
            self.worker.heartbeat(task_id,fence)
            message=self.agents[agent_name].run(incident_id,task,evidence,revision)
            self.messages.save(message)
            stored=self.messages.get(message.message_id,message.revision)
            if not self.messages.verify(stored): raise ValueError('persisted message integrity failure')
            identity=(stored['incident_id'],stored['agent'],stored['task'],stored['revision'])
            if identity!=(incident_id,agent_name,task,revision): raise ValueError('persisted message identity mismatch')
            self.worker.complete(task_id,fence,{'message_id':message.message_id})
            return stored
        except Exception as exc:
            try: self.worker.fail(task_id,fence,type(exc).__name__)
            except RuntimeError: pass
            raise
    def run_case(self,incident_id,evidence,actor:User):
        self.store.authorize(actor,'investigate')
        self.store.transition(incident_id,Status.VALIDATION,actor.user_id)
        self.store.transition(incident_id,Status.INVESTIGATION,actor.user_id)
        revision=self.store.current_revision(incident_id)
        messages=[self.invoke(incident_id,'incident_intake','validate',evidence,revision)]
        work=[('observability','analyze_logs'),('engineering_investigation','hypotheses'),('security_investigation','security_review')]
        with ThreadPoolExecutor(max_workers=3) as pool:
            messages.extend(f.result() for f in [pool.submit(self.invoke,incident_id,a,t,evidence,revision) for a,t in work])
        for message in messages:
            if not self.messages.verify(message): raise ValueError('message verification failed before reconciliation')
        records=[dict(x) for x in evidence]
        reconciliation=CommanderReconciler().reconcile(messages,records)
        audit=IndependentAuditor().review(reconciliation,messages,records)
        for finding in audit['accepted']:
            self.findings.save(incident_id,finding,finding['source_agent'],revision)
        if audit['status']=='rejected': raise ValueError('independent audit rejected reconciliation')
        self.store.transition(incident_id,Status.CORRELATION,'incident_commander')
        self.store.transition(incident_id,Status.RISK_ASSESSMENT,'incident_commander')
        self.store.transition(incident_id,Status.HUMAN_REVIEW,'incident_commander')
        return {'specialist_messages':messages,'reconciliation':reconciliation,'audit':audit}
    def request_sensitive_action(self,incident_id,action,actor):
        self.store.authorize(actor,'investigate')
        return self.store.request_approval(incident_id,action,actor.user_id)
