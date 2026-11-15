import hashlib, os, tempfile
import pytest
from blackbox.agents import make_agents
from blackbox.core import Role, Store
from blackbox.validation import CommanderReconciler, ContractError, IndependentAuditor
from blackbox.task_worker import TaskWorker

def evidence(store, incident='BBX-R', content='retry evidence'):
    store.create_incident(incident, 'remediation', 'test', 'ops')
    eid=store.add_evidence(incident,'log',content)
    row=dict(store.db.execute('select * from evidence where evidence_id=?',(eid,)).fetchone())
    return [row]

def ref(eid, relation='supports', excerpt='retry evidence'):
    return {'evidence_id':eid,'relation':relation,'note':'direct source statement','excerpt':excerpt}

def msg(agent,mid,finding): return {'agent':agent,'message_id':mid,'output':{'findings':[finding]}}

def test_agent_does_not_invent_evidence_references():
    store=Store(); ev=evidence(store)
    out=make_agents(store)['engineering_investigation'].run('BBX-R','hypotheses',ev,0)
    assert any(f['unsupported'] and f['evidence']==[] for f in out.output['findings'])

def test_invalid_ids_and_excerpts_are_rejected_but_semantics_remain_explicit():
    records=[{'evidence_id':'real','content':'unrelated fact'}]
    claim={'kind':'hypothesis','statement':'claim','confidence':'low','evidence':[ref('missing')]}
    with pytest.raises(ContractError): CommanderReconciler().reconcile([msg('a','m',claim)],records)
    claim={'kind':'hypothesis','statement':'claim','confidence':'low','evidence':[ref('real',excerpt='not present')]}
    with pytest.raises(ContractError): CommanderReconciler().reconcile([msg('a','m',claim)],records)
    claim={'kind':'hypothesis','statement':'claim','confidence':'low','evidence':[ref('real',excerpt='unrelated fact')]}
    result=CommanderReconciler().reconcile([msg('a','m',claim)],records)
    assert result['findings'][0]['evidence'][0]['relation']=='supports'
    assert result['findings'][0]['semantic_support']=='unverified'

def test_unsupported_finding_survives_reconciliation_as_unsupported():
    f={'kind':'hypothesis','statement':'unknown cause','confidence':'unknown','unsupported':True,'evidence':[]}
    result=CommanderReconciler().reconcile([msg('a','m',f)],[{'evidence_id':'e1','content':'x'}])
    assert result['findings'][0]['unsupported'] is True
    assert any(x['type']=='insufficient_evidence' for x in result['relationships'])

def test_auditor_accepts_authentic_and_rejects_tampering():
    original={'kind':'measured','statement':'observed','confidence':'medium','evidence':[ref('e1')], 'claim':{'subject':'gateway','predicate':'observed','value':'error'}}
    messages=[msg('observability','m1',original)]
    authentic={'findings':[dict(original,source_agent='observability',message_id='m1')]}
    assert IndependentAuditor().review(authentic,messages,[{'evidence_id':'e1','content':'retry evidence'}])['status']=='accepted'
    for tampered in [dict(original,statement='fabricated'),dict(original,evidence=[ref('e1','contradicts')]),dict(original,claim={'subject':'worker','predicate':'observed','value':'error'})]:
        rec={'findings':[dict(tampered,source_agent='observability',message_id='m1')]}
        assert IndependentAuditor().review(rec,messages,[{'evidence_id':'e1','content':'retry evidence'}])['status']=='rejected'

def test_message_persists_and_reopens_with_integrity():
    from blackbox.message_store import MessageStore
    fd,path=tempfile.mkstemp(); os.close(fd)
    try:
        store=Store(path); ev=evidence(store); message=make_agents(store)['observability'].run('BBX-R','analyze_logs',ev,0)
        MessageStore(store).save(message); store.db.close(); reopened=Store(path); loaded=MessageStore(reopened).get(message.message_id)
        assert loaded['message_id']==message.message_id and MessageStore(reopened).verify(loaded)
    finally: os.unlink(path)

def test_worker_heartbeat_fences_expired_owner():
    store=Store(); evidence(store,'BBX-W'); old=TaskWorker(store,worker_id='same',lease_minutes=1); task=old.enqueue('BBX-W','a','t',0); first=old.claim(task); store.db.execute("update tasks set lease_until='2000-01-01T00:00:00Z' where task_id=?",(task,)); new=TaskWorker(store,worker_id='same',lease_minutes=1); second=new.claim(task)
    assert first['fence_token'] != second['fence_token']
    with pytest.raises(RuntimeError): old.complete(task,{})
    new.complete(task,{})

def test_expired_exhausted_task_is_terminal():
    store=Store(); evidence(store,'BBX-E'); w=TaskWorker(store,worker_id='w',max_attempts=1); task=w.enqueue('BBX-E','a','t',0); w.claim(task); store.db.execute("update tasks set lease_until='2000-01-01T00:00:00Z' where task_id=?",(task,)); assert w.recover_expired()==1; assert w.claim(task) is None
