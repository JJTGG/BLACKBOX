import hashlib, threading, urllib.error, urllib.request
from blackbox.application import serve_application
from blackbox.core import Role, Store
from blackbox.http_api import Authenticator

def test_running_application_serves_frontend_and_protected_api():
    store=Store(); store.create_incident('BBX-WEB','<script>alert(1)</script>','body','ops')
    users={'observer':(hashlib.sha256(b'pw').hexdigest(),Role.OBSERVER),'commander':(hashlib.sha256(b'pw2').hexdigest(),Role.COMMANDER)}
    auth=Authenticator(users,secret='integration-secret',ttl_seconds=30)
    server=serve_application(store,auth,'127.0.0.1',0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start(); base=f'http://127.0.0.1:{server.server_address[1]}'
    try:
        page=urllib.request.urlopen(base+'/').read().decode(); assert 'BLACKBOX Operations' in page
        try: urllib.request.urlopen(base+'/incidents/BBX-WEB')
        except urllib.error.HTTPError as exc: assert exc.code==401
        token=auth.login('observer','pw'); req=urllib.request.Request(base+'/incidents/BBX-WEB',headers={'Authorization':'Bearer '+token}); response=urllib.request.urlopen(req); body=response.read().decode(); assert response.status==200 and '<script>' in body
        req=urllib.request.Request(base+'/incidents/BBX-WEB/actions',data=b'{}',headers={'Authorization':'Bearer '+token},method='POST')
        try: urllib.request.urlopen(req)
        except urllib.error.HTTPError as exc: assert exc.code==403
    finally: server.shutdown(); server.server_close()
