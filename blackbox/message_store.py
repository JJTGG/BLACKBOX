from __future__ import annotations
import hashlib,json
from .core import Store
class MessageStore:
 def __init__(self,store:Store):
  self.store=store
  with store.lock,store.db:
   store.db.execute('''CREATE TABLE IF NOT EXISTS specialist_messages(message_id TEXT NOT NULL,revision INTEGER NOT NULL,incident_id TEXT NOT NULL,agent TEXT NOT NULL,task TEXT NOT NULL,input_fingerprint TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL,message_hash TEXT NOT NULL,PRIMARY KEY(message_id,revision))''')
   store.db.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_specialist_message_revision ON specialist_messages(message_id,revision)')
 def save(self,message):
  payload={'message_id':message.message_id,'incident_id':message.incident_id,'agent':message.agent,'task':message.task,'input_fingerprint':message.input_fingerprint,'revision':message.revision,'status':message.status,'created_at':message.created_at,'output':message.output}; raw=json.dumps(payload,sort_keys=True,separators=(',',':')); digest=hashlib.sha256(raw.encode()).hexdigest()
  with self.store.lock,self.store.db:
   existing=self.store.db.execute('SELECT message_hash FROM specialist_messages WHERE message_id=? AND revision=?',(message.message_id,message.revision)).fetchone()
   if existing:
    if existing['message_hash']!=digest: raise ValueError('message replacement rejected')
    return digest
   self.store.db.execute('INSERT INTO specialist_messages VALUES(?,?,?,?,?,?,?,?,?,?,?)',(message.message_id,message.revision,message.incident_id,message.agent,message.task,message.input_fingerprint,message.status,message.created_at,json.dumps(message.output,sort_keys=True),digest))
  return digest
 def get(self,message_id,revision=None):
  q='SELECT * FROM specialist_messages WHERE message_id=?'; p=[message_id]
  if revision is not None:q+=' AND revision=?';p.append(revision)
  q+=' ORDER BY revision DESC LIMIT 1'; row=self.store.db.execute(q,p).fetchone()
  if not row: raise KeyError(message_id)
  d=dict(row);d['output']=json.loads(d.pop('payload'));return d
 def verify(self,message):
  payload={k:message[k] for k in ('message_id','incident_id','agent','task','input_fingerprint','revision','status','created_at','output')}; raw=json.dumps(payload,sort_keys=True,separators=(',',':'));return hashlib.sha256(raw.encode()).hexdigest()==message['message_hash']
