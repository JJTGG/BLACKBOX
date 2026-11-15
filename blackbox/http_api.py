from __future__ import annotations

import base64, hashlib, hmac, json, os, secrets, sqlite3, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from .core import AuthorizationError, Role, Store, User

class Authenticator:
    def __init__(self, users=None, secret=None):
        self.users = users or {'admin': (hashlib.sha256(b'admin-dev-only').hexdigest(), Role.ADMINISTRATOR), 'observer': (hashlib.sha256(b'observer-dev-only').hexdigest(), Role.OBSERVER)}
        self.secret = (secret or os.environ.get('BLACKBOX_SESSION_SECRET', 'development-only')).encode()
    def login(self, user_id, password):
        record=self.users.get(user_id)
        if not record or not hmac.compare_digest(record[0], hashlib.sha256(password.encode()).hexdigest()): raise AuthorizationError('invalid credentials')
        payload=f'{user_id}:{record[1].value}:{int(time.time())}'.encode(); body=base64.urlsafe_b64encode(payload).decode().rstrip('='); sig=hmac.new(self.secret,body.encode(),hashlib.sha256).hexdigest(); return body+'.'+sig
    def verify(self, token):
        body,sig=token.split('.',1)
        if not hmac.compare_digest(sig,hmac.new(self.secret,body.encode(),hashlib.sha256).hexdigest()): raise AuthorizationError('invalid session')
        user_id,role,_=base64.urlsafe_b64decode(body+'===').decode().split(':',2); return User(user_id,Role(role))

class API:
    def __init__(self, store, auth): self.store,self.auth=store,auth
    def get_incident(self, incident_id, user):
        self.store.authorize(user,'observe')
        row=self.store.db.execute('SELECT incident_id,title,description,status,severity FROM incidents WHERE incident_id=?',(incident_id,)).fetchone()
        if not row: return {'error':'not found'}
        return dict(row)
    def propose_action(self, incident_id, action, user):
        self.store.authorize(user,'investigate'); return {'approval_id': self.store.request_approval(incident_id,action,user.user_id), 'status':'pending'}

class Handler(BaseHTTPRequestHandler):
    api=None
    def _json(self,status,payload):
        body=json.dumps(payload).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        try:
            token=self.headers.get('Authorization','').removeprefix('Bearer ').strip(); user=self.api.auth.verify(token)
            parts=urlparse(self.path).path.strip('/').split('/')
            if len(parts)==2 and parts[0]=='incidents': return self._json(200,self.api.get_incident(parts[1],user))
            return self._json(404,{'error':'not found'})
        except (AuthorizationError, ValueError): return self._json(401,{'error':'unauthorized'})
    def do_POST(self): return self._json(501,{'error':'not implemented'})
    def log_message(self,*args): return

def serve(store, auth, host='127.0.0.1', port=8080):
    Handler.api=API(store,auth); return ThreadingHTTPServer((host,port),Handler)
