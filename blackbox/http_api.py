from __future__ import annotations
import base64, hashlib, hmac, json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from .core import AuthorizationError, Role, User

class Authenticator:
    def __init__(self, users=None, secret=None, ttl_seconds=None):
        if users is None: raise ValueError('explicit users are required')
        if not secret: raise ValueError('explicit signing secret is required')
        self.users=users; self.secret=secret.encode(); self.ttl_seconds=ttl_seconds or int(os.environ.get('BLACKBOX_SESSION_TTL_SECONDS','900'))
    def login(self,user_id,password):
        record=self.users.get(user_id)
        if not record or not hmac.compare_digest(record[0],hashlib.sha256(password.encode()).hexdigest()): raise AuthorizationError('invalid credentials')
        exp=int(time.time())+self.ttl_seconds; payload=f'{user_id}:{record[1].value}:{exp}'.encode(); body=base64.urlsafe_b64encode(payload).decode().rstrip('='); sig=hmac.new(self.secret,body.encode(),hashlib.sha256).hexdigest(); return body+'.'+sig
    def verify(self,token):
        try: body,sig=token.split('.',1); raw=base64.urlsafe_b64decode(body+'==='); user_id,role,expiry=raw.decode().split(':',2)
        except (ValueError,UnicodeDecodeError): raise AuthorizationError('malformed session')
        if not hmac.compare_digest(sig,hmac.new(self.secret,body.encode(),hashlib.sha256).hexdigest()) or int(expiry)<int(time.time()): raise AuthorizationError('invalid or expired session')
        return User(user_id,Role(role))

class API:
    def __init__(self,store,auth): self.store,self.auth=store,auth
    def get_incident(self,incident_id,user):
        self.store.authorize(user,'observe'); row=self.store.db.execute('SELECT incident_id,title,description,status,severity FROM incidents WHERE incident_id=?',(incident_id,)).fetchone()
        if not row: raise KeyError(incident_id)
        return dict(row)
    def propose_action(self,incident_id,action,user):
        self.store.authorize(user,'investigate'); return {'approval_id':self.store.request_approval(incident_id,action,user.user_id),'status':'pending'}

class Handler(BaseHTTPRequestHandler):
    api=None
    def _json(self,status,payload):
        body=json.dumps(payload).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def _user(self):
        token=self.headers.get('Authorization','')
        if not token.startswith('Bearer '): raise AuthorizationError('bearer token required')
        return self.api.auth.verify(token[7:])
    def do_GET(self):
        try:
            user=self._user(); parts=urlparse(self.path).path.strip('/').split('/')
            if len(parts)==2 and parts[0]=='incidents': return self._json(200,self.api.get_incident(parts[1],user))
            return self._json(404,{'error':'not found'})
        except AuthorizationError: return self._json(401,{'error':'unauthorized'})
        except KeyError: return self._json(404,{'error':'not found'})
    def do_POST(self):
        try:
            user=self._user(); parts=urlparse(self.path).path.strip('/').split('/'); length=int(self.headers.get('Content-Length','0')); body=json.loads(self.rfile.read(length) or b'{}')
            if len(parts)==3 and parts[0]=='incidents' and parts[2]=='actions': return self._json(202,self.api.propose_action(parts[1],body.get('action',''),user))
            return self._json(404,{'error':'not found'})
        except AuthorizationError: return self._json(401,{'error':'unauthorized'})
        except (ValueError,TypeError,json.JSONDecodeError): return self._json(400,{'error':'invalid request'})
    def log_message(self,*args): return

def serve(store,auth,host='127.0.0.1',port=8080):
    Handler.api=API(store,auth); return ThreadingHTTPServer((host,port),Handler)
