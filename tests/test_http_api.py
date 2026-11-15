import hashlib
import pytest
from blackbox.core import AuthorizationError, Role, Store, User
from blackbox.http_api import Authenticator, API

def test_authenticated_api_rejects_bad_token_and_observer_cannot_propose():
    store=Store(); store.create_incident('BBX-HTTP','http','test','ops')
    auth=Authenticator({'observer':(hashlib.sha256(b'pw').hexdigest(),Role.OBSERVER)},secret='test-secret',ttl_seconds=30)
    observer=auth.verify(auth.login('observer','pw'))
    assert API(store,auth).get_incident('BBX-HTTP',observer)['incident_id']=='BBX-HTTP'
    try: API(store,auth).propose_action('BBX-HTTP','deploy',observer)
    except Exception as exc: assert exc.__class__.__name__=='AuthorizationError'
    else: raise AssertionError('observer proposed sensitive action')

def test_get_incident_select_runs_inside_active_read_transaction():
    store=Store(); store.create_incident('BBX-READ','read','test','ops')
    api=API(store,Authenticator({'observer':(hashlib.sha256(b'pw').hexdigest(),Role.OBSERVER)},secret='test-secret'))
    observed=[]
    def trace(statement):
        normalized=statement.lstrip().upper()
        if normalized.startswith('SELECT INCIDENT_ID'):
            observed.append((store._tx_depth,len(store._savepoints),store.db.in_transaction))
    store.db.set_trace_callback(trace)
    try:
        assert api.get_incident('BBX-READ',User('observer',Role.OBSERVER))['incident_id']=='BBX-READ'
    finally:
        store.db.set_trace_callback(None)
    assert observed==[(1,0,True)]

def test_get_incident_preserves_key_error_and_denies_unauthorized_user():
    store=Store(); store.create_incident('BBX-AUTH','auth','test','ops')
    requested=[]
    def deny(user,action):
        requested.append(action)
        raise AuthorizationError('denied')
    store.authorize=deny
    api=API(store,None)
    observed=[]
    def trace(statement):
        if statement.lstrip().upper().startswith('SELECT INCIDENT_ID'):
            observed.append(statement)
    store.db.set_trace_callback(trace)
    try:
        with pytest.raises(AuthorizationError): api.get_incident('BBX-AUTH',User('denied',Role.OBSERVER))
    finally:
        store.db.set_trace_callback(None)
    assert requested==['observe']
    assert observed==[]

    store.authorize=lambda user,action: None
    with pytest.raises(KeyError): api.get_incident('BBX-MISSING',User('observer',Role.OBSERVER))
