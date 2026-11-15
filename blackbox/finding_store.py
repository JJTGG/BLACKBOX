from __future__ import annotations
import json
from .core import Store

class FindingStore:
    """Compatibility persistence adapter for provenance-rich findings."""
    def __init__(self, store: Store):
        self.store = store
        with store.lock, store.db:
            for name, definition in [
                ('message_id','TEXT'), ('evidence_refs',"TEXT NOT NULL DEFAULT '[]'"),
                ('unsupported','INTEGER NOT NULL DEFAULT 0'), ('claim_json',"TEXT NOT NULL DEFAULT '{}'"),
            ]:
                cols={r['name'] for r in store.db.execute('PRAGMA table_info(findings)')}
                if name not in cols: store.db.execute(f'ALTER TABLE findings ADD COLUMN {name} {definition}')
    def save(self, incident_id, finding, actor, revision):
        if revision < self.store.current_revision(incident_id): raise ValueError('stale finding')
        refs=finding.get('evidence',[])
        with self.store.lock, self.store.db:
            fid=__import__('uuid').uuid4().hex
            self.store.db.execute('''INSERT INTO findings
              (finding_id,incident_id,kind,statement,supporting,contradicting,confidence,source_agent,revision,created_at,message_id,evidence_refs,unsupported,claim_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (fid,incident_id,finding.get('kind','unknown'),finding['statement'],json.dumps([r for r in refs if r.get('relation')=='supports'],sort_keys=True),json.dumps([r for r in refs if r.get('relation')=='contradicts'],sort_keys=True),finding.get('confidence','unknown'),actor,revision,__import__('blackbox.core',fromlist=['utc_now']).utc_now(),finding.get('message_id'),json.dumps(refs,sort_keys=True),int(bool(finding.get('unsupported'))),json.dumps(finding.get('claim',{}),sort_keys=True)))
            return fid
    def get(self, incident_id):
        return [dict(r) for r in self.store.db.execute('SELECT * FROM findings WHERE incident_id=? ORDER BY created_at',(incident_id,))]
