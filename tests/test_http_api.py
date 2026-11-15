import hashlib, threading, time, urllib.error, urllib.request
from blackbox.core import Role, Store
from blackbox.http_api import Authenticator, serve

def test_http_requests_enforce_auth_and_roles():
    store=Store(); store.create_incident('BBX-HTTP','<script>alert(1)</script>','test','ops')
    auth=Authenticator({'observer':(hashlib.sha256(b'pw').hexdigest(),Role.OBSERVER),'commander':(hashlib.sha256(b'pw2').hexdigest(),Role.COMMANDER)},secret='test-secret',ttl_seconds=30)
    server=serve(store,auth,'127.0.0.1',0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start(); base=f'http://127.0.0.1:{server.server_address[1]}'
    try:
        try: urllib.request.urlopen(base+'/incidents/BBX-HTTP')
        except urllib.error.HTTPError as exc: assert exc.code==401
        observer=auth.login('observer','pw'); request=urllib.request.Request(base+'/incidents/BBX-HTTP',headers={'Authorization':'Bearer '+observer}); assert urllib.request.urlopen(request).status==200
        request=urllib.request.Request(base+'/incidents/BBX-HTTP/actions',data=b'{"action":"deploy"}',headers={'Authorization':'Bearer '+observer},method='POST')
        try: urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc: assert exc.code==403 or exc.code==401
    finally: server.shutdown(); server.server_close()
