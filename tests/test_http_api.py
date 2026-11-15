import hashlib
from blackbox.core import Role, Store
from blackbox.http_api import Authenticator, API

def test_authenticated_api_rejects_bad_token_and_observer_cannot_propose():
    store=Store(); store.create_incident('BBX-HTTP','http','test','ops')
    auth=Authenticator({'observer':(hashlib.sha256(b'pw').hexdigest(),Role.OBSERVER)},secret='test-secret',ttl_seconds=30)
    observer=auth.verify(auth.login('observer','pw'))
    assert API(store,auth).get_incident('BBX-HTTP',observer)['incident_id']=='BBX-HTTP'
    try: API(store,auth).propose_action('BBX-HTTP','deploy',observer)
    except Exception as exc: assert exc.__class__.__name__=='AuthorizationError'
    else: raise AssertionError('observer proposed sensitive action')
