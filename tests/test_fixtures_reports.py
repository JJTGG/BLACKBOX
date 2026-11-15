import json, tempfile, os
from blackbox.core import Store, Role, User
from blackbox.fixtures import seed
from blackbox.orchestrator import Orchestrator
from blackbox.reporting import build_report

def test_seed_cases_are_isolated():
 s=Store();seed(s);assert s.db.execute('SELECT COUNT(*) FROM incidents').fetchone()[0]==2

def test_integrated_orchestration_persists_messages_and_findings():
 s=Store();seed(s);rows=[dict(r) for r in s.db.execute("SELECT * FROM evidence WHERE incident_id='BBX-001'")];result=Orchestrator(s).run_case('BBX-001',rows,User('commander',Role.COMMANDER));assert result['specialist_messages'];assert s.db.execute("SELECT COUNT(*) FROM specialist_messages WHERE incident_id='BBX-001'").fetchone()[0]>=4;assert s.db.execute("SELECT COUNT(*) FROM findings WHERE incident_id='BBX-001'").fetchone()[0]>=1
