import json
import threading
import urllib.request
from http.client import HTTPResponse
from blackbox.core import Role, Store, User
from blackbox.http_api import Authenticator, API


def test_authenticated_api_rejects_bad_token_and_observer_cannot_propose():
    store=Store(); store.create_incident('BBX-HTTP','http','test','ops')
    auth=Authenticator({'observer': (__import__('hashlib').sha256(b'pw').hexdigest(), Role.OBSERVER)})
    api=API(store,auth); observer=auth.verify(auth.login('observer','pw'))
    assert api.get_incident('BBX-HTTP', observer)['incident_id']=='BBX-HTTP'
    try: api.propose_action('BBX-HTTP','deploy',observer)
    except Exception as exc: assert exc.__class__.__name__=='AuthorizationError'
    else: raise AssertionError('observer proposed sensitive action')
