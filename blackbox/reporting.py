from __future__ import annotations
import json
from .core import Store

def build_report(store,incident_id):
 incident=store.db.execute('SELECT * FROM incidents WHERE incident_id=?',(incident_id,)).fetchone()
 if not incident: raise KeyError(incident_id)
 evidence=[dict(r) for r in store.db.execute('SELECT * FROM evidence WHERE incident_id=? ORDER BY created_at',(incident_id,))]
 findings=[dict(r) for r in store.db.execute('SELECT * FROM findings WHERE incident_id=? ORDER BY created_at',(incident_id,))]
 approvals=[dict(r) for r in store.db.execute('SELECT * FROM approvals WHERE incident_id=? ORDER BY created_at',(incident_id,))]
 audit=[dict(r) for r in store.db.execute('SELECT event_id,event_type,actor,outcome,resource,created_at FROM audit WHERE incident_id=? ORDER BY rowid',(incident_id,))]
 def parse_json(row,key,default):
  try:return json.loads(row[key])
  except (TypeError,KeyError,json.JSONDecodeError):return default
 def finding_view(row):
  return {'finding_id':row['finding_id'],'kind':row['kind'],'statement':row['statement'],'source_agent':row['source_agent'],'message_id':row.get('message_id'),'evidence_refs':parse_json(row,'evidence_refs',[]),'supporting':parse_json(row,'supporting',[]),'contradicting':parse_json(row,'contradicting',[]),'claim':parse_json(row,'claim_json',{}),'confidence':row['confidence'],'unsupported':bool(row.get('unsupported',0)),'revision':row['revision'],'created_at':row['created_at']}
 all_findings=[finding_view(f) for f in findings]
 return {'executive_summary':incident['description'],'incident_overview':{'incident_id':incident['incident_id'],'title':incident['title'],'category':incident['category'],'status':incident['status']},'severity_assessment':{'severity':incident['severity'],'confidence':'unknown','reason':'No independent impact-calibration evidence supplied.'},'business_impact':'Reported impact remains unverified.','reconstructed_timeline':[{'at':x['created_at'],'source':x['kind'],'statement':x['content']} for x in evidence],'confirmed_facts':[f['statement'] for f in all_findings if f['kind'] in {'observed','measured'}],'findings':all_findings,'competing_root_cause_hypotheses':[f for f in all_findings if f['kind']=='hypothesis'],'security_findings':[f for f in all_findings if f['kind']=='security'],'recommended_containment_actions':['preserve evidence','require human approval before external or infrastructure action'],'recovery_plan':['validate dependencies and telemetry'],'remediation_priorities':[],'outstanding_questions':['Which dependency caused the observed impact?','Is the outbound destination authorized?'],'confidence_assessments':{'overall':'low_to_medium','basis':'Evidence may be incomplete.'},'approval_history':approvals,'audit_references':audit}
