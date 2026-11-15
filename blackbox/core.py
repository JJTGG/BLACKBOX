from __future__ import annotations
import hashlib,json,sqlite3,threading,uuid
from contextlib import contextmanager
from datetime import datetime,timezone
from enum import Enum

def utc_now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
class Role(str,Enum): ADMINISTRATOR='administrator';COMMANDER='incident_commander';INVESTIGATOR='investigator';APPROVER='approver';OBSERVER='observer'
class Status(str,Enum): INTAKE='intake';VALIDATION='validation';INVESTIGATION='investigation';CORRELATION='correlation';RISK_ASSESSMENT='risk_assessment';HUMAN_REVIEW='human_review';REPORTING='reporting';RESOLUTION='resolution';SUSPENDED='suspended';CANCELLED='cancelled'
TRANSITIONS={Status.INTAKE:{Status.VALIDATION,Status.CANCELLED},Status.VALIDATION:{Status.INVESTIGATION,Status.SUSPENDED,Status.CANCELLED},Status.INVESTIGATION:{Status.CORRELATION,Status.SUSPENDED,Status.CANCELLED},Status.CORRELATION:{Status.RISK_ASSESSMENT,Status.SUSPENDED},Status.RISK_ASSESSMENT:{Status.HUMAN_REVIEW,Status.SUSPENDED},Status.HUMAN_REVIEW:{Status.REPORTING,Status.INVESTIGATION,Status.SUSPENDED},Status.REPORTING:{Status.RESOLUTION,Status.HUMAN_REVIEW},Status.RESOLUTION:set(),Status.SUSPENDED:{Status.VALIDATION,Status.INVESTIGATION,Status.CANCELLED},Status.CANCELLED:set()}
class User:
 def __init__(self,user_id,role):self.user_id,self.role=user_id,role
class AgentMessage:
 def __init__(self,message_id,incident_id,agent,task,input_fingerprint,output,status,created_at,revision):self.message_id,self.incident_id,self.agent,self.task,self.input_fingerprint,self.output,self.status,self.created_at,self.revision=message_id,incident_id,agent,task,input_fingerprint,output,status,created_at,revision
class AuthorizationError(Exception):pass
class InvalidTransition(Exception):pass
class StaleResult(Exception):pass
class DuplicateIncident(Exception):pass
class Store:
 def __init__(self,path=':memory:'):
  self.db=sqlite3.connect(path,check_same_thread=False,isolation_level=None,timeout=30);self.db.row_factory=sqlite3.Row;self.lock=threading.RLock();self._tx_depth=0;self._savepoints=[];self._savepoint_counter=0;self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA busy_timeout=30000');self.migrate()
 @contextmanager
 def transaction(self,write=True):
  with self.lock:
   outer=self._tx_depth==0
   if outer:
    if self.db.in_transaction:raise RuntimeError('unmanaged SQLite transaction detected')
    self.db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
   elif not self.db.in_transaction:raise RuntimeError('transaction state mismatch')
   self._tx_depth+=1;sp=None
   if not outer:
    self._savepoint_counter+=1;sp=f'bbx_sp_{self._savepoint_counter}';self._savepoints.append(sp);self.db.execute(f'SAVEPOINT {sp}')
   try:
    yield self
    if sp:self.db.execute(f'RELEASE SAVEPOINT {sp}');self._savepoints.pop()
    self._tx_depth-=1
    if outer:self.db.commit()
   except BaseException:
    try:
     if sp:self.db.execute(f'ROLLBACK TO SAVEPOINT {sp}');self.db.execute(f'RELEASE SAVEPOINT {sp}');self._savepoints.pop()
     elif self.db.in_transaction:self.db.rollback()
    finally:self._tx_depth=max(0,self._tx_depth-1);self._savepoints.clear() if outer else None
    raise
   finally:
    if outer and self._tx_depth==0:self._savepoints.clear()
 def migrate(self):
  with self.lock:
   if self.db.in_transaction:raise RuntimeError('migration inside transaction')
   self.db.executescript('''CREATE TABLE IF NOT EXISTS incidents(incident_id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,category TEXT NOT NULL,status TEXT NOT NULL,severity TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,intake_key TEXT UNIQUE NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS evidence(evidence_id TEXT PRIMARY KEY,incident_id TEXT NOT NULL REFERENCES incidents ON DELETE CASCADE,kind TEXT NOT NULL,content TEXT NOT NULL,metadata TEXT NOT NULL,trusted INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS tasks(task_id TEXT PRIMARY KEY,incident_id TEXT NOT NULL REFERENCES incidents ON DELETE CASCADE,agent TEXT NOT NULL,task TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL,output TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS findings(finding_id TEXT PRIMARY KEY,incident_id TEXT NOT NULL REFERENCES incidents ON DELETE CASCADE,kind TEXT NOT NULL,statement TEXT NOT NULL,supporting TEXT NOT NULL,contradicting TEXT NOT NULL,confidence TEXT NOT NULL,source_agent TEXT NOT NULL,revision INTEGER NOT NULL,created_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS approvals(approval_id TEXT PRIMARY KEY,incident_id TEXT NOT NULL REFERENCES incidents ON DELETE CASCADE,action TEXT NOT NULL,status TEXT NOT NULL,requested_by TEXT NOT NULL,decided_by TEXT,created_at TEXT NOT NULL,decided_at TEXT);CREATE TABLE IF NOT EXISTS audit(event_id TEXT PRIMARY KEY,incident_id TEXT,actor TEXT NOT NULL,event_type TEXT NOT NULL,outcome TEXT NOT NULL,resource TEXT,metadata TEXT NOT NULL,correlation_id TEXT NOT NULL,previous_hash TEXT,event_hash TEXT NOT NULL,created_at TEXT NOT NULL);''')
   cols={r['name'] for r in self.db.execute('PRAGMA table_info(findings)')}
   for n,d in [('message_id','TEXT'),('evidence_refs',"TEXT NOT NULL DEFAULT '[]'"),('unsupported','INTEGER NOT NULL DEFAULT 0'),('claim_json',"TEXT NOT NULL DEFAULT '{}'"),('created_at','TEXT')]:
    if n not in cols:self.db.execute(f'ALTER TABLE findings ADD COLUMN {n} {d}')
 def _audit_locked(self,incident_id,actor,event_type,outcome,resource='',metadata=None):
  eid,now,cid=str(uuid.uuid4()),utc_now(),str(uuid.uuid4());r=self.db.execute('SELECT event_hash FROM audit ORDER BY rowid DESC LIMIT 1').fetchone();prev=r['event_hash'] if r else '';body={'event_id':eid,'incident_id':incident_id,'actor':actor,'event_type':event_type,'outcome':outcome,'resource':resource,'metadata':metadata or {},'correlation_id':cid,'previous_hash':prev,'created_at':now};h=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest();self.db.execute('INSERT INTO audit VALUES(?,?,?,?,?,?,?,?,?,?,?)',(eid,incident_id,actor,event_type,outcome,resource,json.dumps(metadata or {},sort_keys=True),cid,prev,h,now));return eid
 def audit(self,*args,**kwargs):
  with self.transaction():return self._audit_locked(*args,**kwargs)
 def create_incident(self,incident_id,title,description,category,severity='unknown',intake_key=None,actor='intake-agent'):
  key=intake_key or hashlib.sha256(f'{title}|{description}'.strip().lower().encode()).hexdigest();now=utc_now()
  try:
   with self.transaction():self.db.execute('INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?,?,?)',(incident_id,title,description,category,Status.INTAKE.value,severity,0,key,now,now));self._audit_locked(incident_id,actor,'incident.created','accepted',metadata={'category':category})
  except sqlite3.IntegrityError as exc:
   with self.transaction():self._audit_locked(incident_id,actor,'incident.create.rejected','duplicate',metadata={'intake_key':key})
   raise DuplicateIncident(incident_id) from exc
 def add_evidence(self,incident_id,kind,content,metadata=None,actor='intake-agent'):
  eid=str(uuid.uuid4())
  with self.transaction():self.db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?)',(eid,incident_id,kind,content,json.dumps(metadata or {},sort_keys=True),0,utc_now()));self._audit_locked(incident_id,actor,'evidence.ingested','accepted',eid,{'kind':kind,'untrusted':True})
  return eid
 def transition(self,incident_id,target,actor,result=None):
  with self.transaction():
   row=self.db.execute('SELECT status,revision FROM incidents WHERE incident_id=?',(incident_id,)).fetchone();
   if not row:raise KeyError(incident_id)
   current=Status(row['status'])
   if target not in TRANSITIONS[current]:self._audit_locked(incident_id,actor,'state.transition.rejected','invalid',metadata={'from':current.value,'to':target.value});raise InvalidTransition(f'{current.value}->{target.value}')
   self.db.execute('UPDATE incidents SET status=?,revision=?,updated_at=? WHERE incident_id=? AND revision=?',(target.value,row['revision']+1,utc_now(),incident_id,row['revision']));self._audit_locked(incident_id,actor,'state.transition','accepted',metadata={'from':current.value,'to':target.value,'result':result or {}})
 def current_revision(self,incident_id):
  with self.lock:
   row=self.db.execute('SELECT revision FROM incidents WHERE incident_id=?',(incident_id,)).fetchone();
   if not row:raise KeyError(incident_id)
   return int(row['revision'])
 def save_finding(self,incident_id,finding,actor,revision):
  with self.transaction():
   if revision<self.current_revision(incident_id):raise StaleResult()
   refs=finding.get('evidence',[]);fid=str(uuid.uuid4());self.db.execute('INSERT INTO findings(finding_id,incident_id,kind,statement,supporting,contradicting,confidence,source_agent,revision,created_at,message_id,evidence_refs,unsupported,claim_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(fid,incident_id,finding.get('kind','unknown'),finding['statement'],json.dumps([r for r in refs if r.get('relation')=='supports'],sort_keys=True),json.dumps([r for r in refs if r.get('relation')=='contradicts'],sort_keys=True),finding.get('confidence','unknown'),actor,revision,utc_now(),finding.get('message_id'),json.dumps(refs,sort_keys=True),int(bool(finding.get('unsupported'))),json.dumps(finding.get('claim',{}),sort_keys=True)));self._audit_locked(incident_id,actor,'finding.recorded','accepted',fid,{'revision':revision,'unsupported':bool(finding.get('unsupported'))});return fid
 def request_approval(self,incident_id,action,requested_by):
  aid=str(uuid.uuid4())
  with self.transaction():self.db.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?)',(aid,incident_id,action,'pending',requested_by,None,utc_now(),None));self._audit_locked(incident_id,requested_by,'approval.requested','pending',aid,{'action':action})
  return aid
 def decide_approval(self,approval_id,user,approve):
  if user.role not in {Role.APPROVER,Role.ADMINISTRATOR}:raise AuthorizationError('approval role required')
  with self.transaction():
   row=self.db.execute('SELECT incident_id,status FROM approvals WHERE approval_id=?',(approval_id,)).fetchone();
   if not row:raise KeyError(approval_id)
   if row['status']!='pending':raise ValueError('approval already decided')
   status='approved' if approve else 'rejected';self.db.execute('UPDATE approvals SET status=?,decided_by=?,decided_at=? WHERE approval_id=?',(status,user.user_id,utc_now(),approval_id));self._audit_locked(row['incident_id'],user.user_id,'approval.decided',status,approval_id)
 def verify_audit_chain(self):
  with self.lock:
   previous=''
   for row in self.db.execute('SELECT * FROM audit ORDER BY rowid').fetchall():
    body={'event_id':row['event_id'],'incident_id':row['incident_id'],'actor':row['actor'],'event_type':row['event_type'],'outcome':row['outcome'],'resource':row['resource'],'metadata':json.loads(row['metadata']),'correlation_id':row['correlation_id'],'previous_hash':row['previous_hash'],'created_at':row['created_at']}
    if row['previous_hash']!=previous or hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()!=row['event_hash']:return False
    previous=row['event_hash']
  return True
 def authorize(self,user,action):
  allowed={'create_incident':{Role.ADMINISTRATOR,Role.COMMANDER,Role.INVESTIGATOR},'investigate':{Role.ADMINISTRATOR,Role.COMMANDER,Role.INVESTIGATOR},'approve':{Role.ADMINISTRATOR,Role.APPROVER},'admin':{Role.ADMINISTRATOR},'observe':set(Role)}
  if user.role not in allowed.get(action,set()):raise AuthorizationError(f'{user.role} cannot {action}')
