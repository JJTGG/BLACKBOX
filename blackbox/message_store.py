from __future__ import annotations
import hashlib, json, re
from .core import Store

class MessageStore:
    def __init__(self, store: Store):
        self.store=store
        with store.lock,store.db:
            store.db.execute('''CREATE TABLE IF NOT EXISTS specialist_messages(message_id TEXT PRIMARY KEY,incident_id TEXT NOT NULL,agent TEXT NOT NULL,task TEXT NOT NULL,input_fingerprint TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL,message_hash TEXT NOT NULL)''')
    def save(self,message):
        payload={'message_id':message.message_id,'incident_id':message.incident_id,'agent':message.agent,'task':message.task,'input_fingerprint':message.input_fingerprint,'revision':message.revision,'status':message.status,'created_at':message.created_at,'output':message.output}
        raw=json.dumps(payload,sort_keys=True,separators=(',',':')); digest=hashlib.sha256(raw.encode()).hexdigest()
        with self.store.lock,self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO specialist_messages VALUES(?,?,?,?,?,?,?,?,?,?)',(message.message_id,message.incident_id,message.agent,message.task,message.input_fingerprint,message.revision,message.status,message.created_at,json.dumps(message.output,sort_keys=True),digest))
        return digest
    def get(self,message_id):
        row=self.store.db.execute('SELECT * FROM specialist_messages WHERE message_id=?',(message_id,)).fetchone()
        if not row: raise KeyError(message_id)
        data=dict(row); data['output']=json.loads(data['payload']); return {'message_id':data['message_id'],'incident_id':data['incident_id'],'agent':data['agent'],'task':data['task'],'input_fingerprint':data['input_fingerprint'],'revision':data['revision'],'status':data['status'],'created_at':data['created_at'],'output':data['output'],'message_hash':data['message_hash']}
    def verify(self,message):
        payload={k:message[k] for k in ('message_id','incident_id','agent','task','input_fingerprint','revision','status','created_at','output')}
        raw=json.dumps(payload,sort_keys=True,separators=(',',':'))
        return hashlib.sha256(raw.encode()).hexdigest()==message['message_hash']
