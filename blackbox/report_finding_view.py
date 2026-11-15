from __future__ import annotations
import json
from .core import Store

class ReportFindingView:
    def __init__(self, store: Store): self.store=store
    def for_incident(self, incident_id):
        rows=self.store.db.execute('SELECT * FROM findings WHERE incident_id=? ORDER BY created_at',(incident_id,)).fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            item['evidence_refs']=json.loads(item.get('evidence_refs') or '[]')
            item['unsupported']=bool(item.get('unsupported',0))
            item['claim']=json.loads(item.get('claim_json') or '{}')
            result.append(item)
        return result
