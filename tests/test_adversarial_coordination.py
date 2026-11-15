import pytest
from blackbox.validation import CommanderReconciler, ContractError, IndependentAuditor

def msg(agent,mid,findings): return {'agent':agent,'message_id':mid,'output':{'findings':findings}}
def ref(eid,relation='supports',excerpt=None): return {'evidence_id':eid,'relation':relation,'note':'directly observed','excerpt':excerpt or ('deployment evidence' if eid=='e1' else 'infrastructure evidence')}
def records(): return [{'evidence_id':'e1','content':'deployment evidence'},{'evidence_id':'e2','content':'infrastructure evidence'}]

def test_commander_preserves_sources():
 r=CommanderReconciler().reconcile([msg('observability','m1',[{'kind':'measured','statement':'deployment correlated','confidence':'medium','evidence':[ref('e1')]}]),msg('engineering_investigation','m2',[{'kind':'hypothesis','statement':'infrastructure anomaly','confidence':'low','evidence':[ref('e2')]}])],records()); assert {x['source_agent'] for x in r['findings']}=={'observability','engineering_investigation'}

def test_excerpt_copied_from_another_record_is_rejected():
 with pytest.raises(ContractError): CommanderReconciler().reconcile([msg('a','m',[{'kind':'hypothesis','statement':'cause','confidence':'low','evidence':[ref('e2',excerpt='deployment evidence')]}])],records())

def test_missing_evidence_is_rejected():
 with pytest.raises(ContractError): CommanderReconciler().reconcile([msg('a','m',[{'kind':'hypothesis','statement':'cause','confidence':'high','evidence':[]}])],records())

def test_authentic_audit_accepts_and_tampering_rejects():
 f={'kind':'measured','statement':'observed','confidence':'medium','evidence':[ref('e1')],'claim':{'subject':'gateway','predicate':'state','value':'degraded'}};m=[msg('observability','m1',[f])];auth={'findings':[dict(f,source_agent='observability',message_id='m1')]};assert IndependentAuditor().review(auth,m,records())['status']=='accepted'
 for bad in [dict(f,statement='forged'),dict(f,evidence=[ref('e1','contradicts')]),dict(f,claim={'subject':'worker','predicate':'state','value':'degraded'})]: assert IndependentAuditor().review({'findings':[dict(bad,source_agent='observability',message_id='m1')]},m,records())['status']=='rejected'
