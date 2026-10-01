"""실제 Spring OAuth의 state·PKCE·콜백·재사용 방지를 격리 공급자와 검증한다."""
from urllib.parse import urlsplit,parse_qs
import requests
from tests.test_market_explorer import client

def configure(**values):
    assert requests.post('http://127.0.0.1:8016/configure',json=values,timeout=5).status_code==200

def start(client):
    response=client.get('/api/auth/google',follow_redirects=False)
    assert response.status_code==302
    query=parse_qs(urlsplit(response.headers['location']).query)
    assert query['code_challenge_method']==['S256'] and len(query['code_challenge'][0])>=43
    assert 'httponly' in response.headers['set-cookie'].lower()
    return query['state'][0]

def test_oauth_success_then_replay_is_rejected(client):
    configure()
    state=start(client)
    response=client.get('/api/auth/google/callback',params={'code':'fixture-code','state':state},follow_redirects=False)
    assert response.status_code==302,response.text
    assert client.get('/api/auth/me').json()['provider']=='google'
    client.cookies.set('oauth_state',state)
    assert client.get('/api/auth/google/callback',params={'code':'fixture-code','state':state},follow_redirects=False).status_code==400

def test_oauth_mismatched_state_and_unverified_email_do_not_replace_session(client):
    owner=client.get('/api/auth/me').json()['id']
    configure()
    state=start(client)
    assert client.get('/api/auth/google/callback',params={'code':'fixture-code','state':'wrong'},follow_redirects=False).status_code==400
    configure(google_user={'id':'unverified','email':'unverified@example.com','verified_email':False})
    assert client.get('/api/auth/google/callback',params={'code':'fixture-code','state':state},follow_redirects=False).status_code==502
    assert client.get('/api/auth/me').json()['id']==owner

def test_oauth_expired_request_is_rejected(client):
    from db.redis_client import get_redis
    configure()
    state=start(client)
    get_redis().delete('oauth-state:'+state)
    assert client.get('/api/auth/google/callback',params={'code':'fixture-code','state':state},follow_redirects=False).status_code==400
