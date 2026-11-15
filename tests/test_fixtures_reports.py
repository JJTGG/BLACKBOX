import json, tempfile, os
import pytest
from blackbox.core import Store, Role, User
from blackbox.fixtures import seed
from blackbox.orchestrator import Orchestrator
from blackbox.reporting import build_report

def test_seed_cases_are_isolated():
 s=Store();seed(s);assert s.db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0]==2

def test_integrated_orchestration_persists_messages_and_findings():
 s=Store();seed(s);rows=[dict(r) for r in s.db.execute("SELECT * FROM evidence WHERE incident_id='BBX-001'")];result=Orchestrator(s).run_case('BBX-001',rows,User('commander',Role.COMMANDER));assert result['specialist_messages'];assert s.db.execute("SELECT COUNT(*) FROM specialist_messages WHERE incident_id='BBX-001'").fetchone()[0]>=4;assert s.db.execute("SELECT COUNT(*) FROM findings WHERE incident_id='BBX-001'").fetchone()[0]>=1

def test_report_queries_run_in_one_read_transaction():
 s=Store();seed(s);seen=[]
 def trace(statement):
  normalized=statement.lstrip().upper()
  if normalized.startswith(('SELECT * FROM INCIDENTS','SELECT * FROM EVIDENCE','SELECT * FROM FINDINGS','SELECT * FROM APPROVALS','SELECT EVENT_ID,EVENT_TYPE,ACTOR,OUTCOME,RESOURCE,CREATED_AT FROM AUDIT')):
   seen.append((normalized.split(' WHERE ',1)[0],s._tx_depth,len(s._savepoints),s.db.in_transaction))
 s.db.set_trace_callback(trace)
 try:
  report=build_report(s,'BBX-001')
 finally:
  s.db.set_trace_callback(None)
 assert report['incident_overview']['incident_id']=='BBX-001'
 assert len(seen)==5
 assert all((depth,savepoints,active)==(1,0,True) for _,depth,savepoints,active in seen)
 assert {query for query,_,_,_ in seen}=={'SELECT * FROM INCIDENTS','SELECT * FROM EVIDENCE','SELECT * FROM FINDINGS','SELECT * FROM APPROVALS','SELECT EVENT_ID,EVENT_TYPE,ACTOR,OUTCOME,RESOURCE,CREATED_AT FROM AUDIT'}

def test_report_missing_incident_preserves_key_error():
 s=Store()
 with pytest.raises(KeyError):
  build_report(s,'MISSING-REPORT')
