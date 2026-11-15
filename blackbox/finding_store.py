from __future__ import annotations
import json,uuid
from .core import Store,utc_now
class FindingStore:
 def __init__(self,store:Store):
  self.store=store
  with store.lock:
   cols={r['name'] for r in store.db.execute('PRAGMA table_info(findings)')}
   for name,definition in [('message_id','TEXT'),('evidence_refs',"TEXT NOT NULL DEFAULT '[]'"),('unsupported','INTEGER NOT NULL DEFAULT 0'),('claim_json',"TEXT NOT NULL DEFAULT '{}'"),('created_at','TEXT')]:
    if name not in cols:store.db.execute(f'ALTER TABLE findings ADD COLUMN {name} {definition}')
 def save(self,incident_id,finding,actor,revision):
  with self.store.transaction():
   if revision<self.store.current_revision(incident_id):raise ValueError('stale finding')
   refs=finding.get('evidence',[]);fid=uuid.uuid4().hex;now=utc_now();self.store.db.execute('''INSERT INTO findings(finding_id,incident_id,kind,statement,supporting,contradicting,confidence,source_agent,revision,created_at,message_id,evidence_refs,unsupported,claim_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(fid,incident_id,finding.get('kind','unknown'),finding['statement'],json.dumps([r for r in refs if r.get('relation')=='supports',],sort_keys=True),json.dumps([r for r in refs if r.get('relation')=='contradicts'],sort_keys=True),finding.get('confidence','unknown'),actor,revision,now,finding.get('message_id'),json.dumps(refs,sort_keys=True),int(bool(finding.get('unsupported'))),json.dumps(finding.get('claim',{}),sort_keys=True)))
   self.store._audit_locked(incident_id,actor,'finding.recorded','accepted',fid,{'revision':revision,'unsupported':bool(finding.get('unsupported'))});return fid
 def get(self,incident_id):
  with self.store.lock:return[dict(r) for r in self.store.db.execute('SELECT * FROM findings WHERE incident_id=? ORDER BY created_at',(incident_id,))]