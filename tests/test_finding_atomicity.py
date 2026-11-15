import os,tempfile
from blackbox.core import Store,Role,User
from blackbox.finding_store import FindingStore

def test_finding_and_audit_persist_across_reopen():
 fd,path=tempfile.mkstemp();os.close(fd)
 try:
  s=Store(path);s.create_incident('BBX-F','finding','durable','ops');s.transition('BBX-F',__import__('blackbox.core',fromlist=['Status']).Status.VALIDATION,'test');f={'kind':'hypothesis','statement':'possible cause','confidence':'low','unsupported':False,'message_id':'m1','evidence':[{'evidence_id':'e1','relation':'supports','note':'observed','excerpt':'observed'}],'claim':{'subject':'gateway','predicate':'state','value':'degraded'}}
  s.add_evidence('BBX-F','log','observed');FindingStore(s).save('BBX-F',f,'agent',1);s.db.close();r=Store(path);row=r.db.execute("SELECT * FROM findings WHERE incident_id='BBX-F'").fetchone();assert row['message_id']=='m1' and row['unsupported']==0 and 'observed' in row['evidence_refs'];assert r.db.execute("SELECT COUNT(*) FROM audit WHERE event_type='finding.recorded'").fetchone()[0]==1;assert r.verify_audit_chain()
 finally:os.unlink(path)
