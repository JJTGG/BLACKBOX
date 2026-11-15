import hashlib, json, os, tempfile, threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest
from blackbox.agents import make_agents
from blackbox.core import Role, Store, User
from blackbox.http_api import Authenticator, serve
from blackbox.validation import CommanderReconciler, ContractError, IndependentAuditor
from blackbox.task_worker import TaskWorker


def evidence(store, incident='BBX-R', content='retry evidence'):
    store.create_incident(incident, 'remediation', 'test', 'ops')
    eid=store.add_evidence(incident,'log',content)
    return [dict(store.db.execute('select * from evidence where evidence_id=?',(eid,)).fetchone())]

def ref(eid, relation='supports'):
    return {'evidence_id':eid,'relation':relation,'note':'direct source statement'}

def msg(agent,mid,finding): return {'agent':agent,'message_id':mid,'output':{'findings':[finding]}}

def test_agent_does_not_invent_evidence_references():
    store=Store(); ev=evidence(store)
    out=make_agents(store)['engineering_investigation'].run('BBX-R','hypotheses',ev,0)
    assert any(f['unsupported'] and f['evidence']==[] for f in out.output['findings'])

def test_invalid_and_semantically_unrelated_evidence_are_not_accepted():
    with pytest.raises(ContractError): CommanderReconciler().reconcile([msg('a','m',{'kind':'hypothesis','statement':'claim','confidence':'low','evidence':[ref('missing')]})],{'real'})
    with pytest.raises(ContractError): CommanderReconciler().reconcile([msg('a','m',{'kind':'hypothesis','statement':'claim','confidence':'low','evidence':[ref('e1')]})],{'e1'})

def test_unsupported_finding_survives_reconciliation_as_unsupported():
    f={'kind':'hypothesis','statement':'unknown cause','confidence':'unknown','unsupported':True,'evidence':[]}
    result=CommanderReconciler().reconcile([msg('a','m',f)],{'e1'})
    assert result['findings'][0]['unsupported'] is True
    assert result['relationships'][0]['type']=='insufficient_evidence'

def test_auditor_rejects_tampered_statement_and_evidence_relation():
    original={'kind':'measured','statement':'observed','confidence':'medium','evidence':[ref('e1')]}
    messages=[msg('observability','m1',original)]
    for tampered in [dict(original,statement='fabricated'),dict(original,evidence=[ref('e1','contradicts')]),dict(original)]:
        if tampered is original: continue
        rec={'findings':[dict(tampered,source_agent='observability',message_id='m1')]}
        assert IndependentAuditor().review(rec,messages,{'e1'})['status']=='rejected'

def test_message_persists_and_reopens_with_integrity():
    from blackbox.message_store import MessageStore
    fd,path=tempfile.mkstemp(); os.close(fd)
    try:
        store=Store(path); ev=evidence(store); message=make_agents(store)['observability'].run('BBX-R','analyze_logs',ev,0)
        MessageStore(store).save(message); store.db.close()
        reopened=Store(path); loaded=MessageStore(reopened).get(message.message_id)
        assert loaded['message_id']==message.message_id and MessageStore(reopened).verify(loaded)
    finally: os.unlink(path)

def test_worker_heartbeat_fences_expired_owner():
    store=Store(); evidence(store,'BBX-W')
    old=TaskWorker(store,worker_id='old',lease_minutes=1); task=old.enqueue('BBX-W','a','t',0); claimed=old.claim()
    store.db.execute("update tasks set lease_until='2000-01-01T00:00:00Z' where task_id=?",(task,))
    new=TaskWorker(store,worker_id='new',lease_minutes=1); assert new.claim()['task_id']==task
    with pytest.raises(RuntimeError): old.complete(task,{})

def test_expired_exhausted_task_is_terminal():
    store=Store(); evidence(store,'BBX-E')
    w=TaskWorker(store,worker_id='w',max_attempts=1); task=w.enqueue('BBX-E','a','t',0); w.claim(); store.db.execute("update tasks set lease_until='2000-01-01T00:00:00Z' where task_id=?",(task,)); assert w.recover_expired()==1
    assert w.claim() is None

def test_http_auth_expiry_and_role_are_enforced():
    secret='test-secret'; auth=Authenticator({'observer':(hashlib.sha256(b'pw').hexdigest(),Role.OBSERVER)},secret=secret,ttl_seconds=1)
    token=auth.login('observer','pw'); assert auth.verify(token).role==Role.OBSERVER
    import time; time.sleep(1.1)
    with pytest.raises(Exception): auth.verify(token)
