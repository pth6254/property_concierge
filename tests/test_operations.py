"""운영자 격리·장애 감지·단지 주소 영속화·요약 스냅샷 검증."""
import time
from tests.test_market_explorer import client


def operator(client, monkeypatch):
    user = client.get('/api/auth/me').json()
    monkeypatch.setenv('OPERATOR_USER_IDS', str(user['id']))
    return user


def test_operations_requires_explicit_existing_account(client, monkeypatch):
    monkeypatch.setenv('OPERATOR_USER_IDS', '')
    assert client.get('/api/operations/status').status_code == 403
    operator(client, monkeypatch)
    assert client.get('/api/auth/me').json()['is_operator'] is True
    assert client.get('/api/operations/status').status_code == 200
    client.post('/api/auth/logout')
    assert client.get('/api/operations/status').status_code == 401


def test_readiness_detects_dead_worker_and_alert_transitions(client):
    from api.operational_health import WORKERS, ALERTS, snapshot, record_transition
    from api.job_worker import ensure_group
    from db.redis_client import get_redis
    redis = get_redis()
    ensure_group()
    redis.delete(WORKERS, ALERTS, f'{ALERTS}:state')
    assert client.get('/health').status_code == 200
    assert client.get('/ready').status_code == 503
    state = snapshot()
    assert state['checks']['worker'] == 'down'
    record_transition(state);record_transition(state)
    assert redis.xlen(ALERTS) == 1
    redis.zadd(WORKERS, {'test-worker':time.time()})
    assert client.get('/ready').status_code == 200
    record_transition(snapshot())
    assert redis.xlen(ALERTS) == 2
    redis.zadd(WORKERS, {'test-worker':time.time()-35})
    assert client.get('/ready').status_code == 503
    redis.delete(WORKERS)


def test_catalog_retains_identity_and_marks_failed_recheck(client,monkeypatch):
    from backend.services.complex_catalog import lookup
    from services import complex_address_service as addresses
    from db.models import ComplexCatalog
    from tests.conftest import truncate_tables
    truncate_tables(ComplexCatalog)
    calls=[]
    def result(*args,**kwargs):
        calls.append(1)
        return {'road_address':'검증로 1','jibun_address':'검증동 1','address_status':'matched','matched_name':'현대1차아파트'}
    monkeypatch.setattr(addresses,'resolve_complex_address',result)
    first=lookup('서울특별시 강남구','11680','역삼동','현대1차')
    second=lookup('서울특별시 강남구','11680','역삼동','1차현대아파트')
    assert first['complex_id']==second['complex_id'] and len(calls)==1
    monkeypatch.setattr(addresses,'resolve_complex_address',lambda *a,**kw:{'address_status':'unavailable'})
    failed=lookup('서울특별시 강남구','11680','역삼동','현대1차',force=True)
    assert failed['road_address']=='검증로 1' and failed['address_status']=='unavailable'
    operator(client,monkeypatch)
    row=client.get('/api/operations/complexes?lawd_code=11680').json()['items'][0]
    assert '1차현대아파트' in row['aliases']


def test_ingestion_missing_months_and_retry_guard(client,monkeypatch):
    from api import jobs
    from db.models import IngestLog
    from tests.conftest import truncate_tables
    truncate_tables(IngestLog)
    operator(client,monkeypatch)
    data=client.get('/api/operations/ingestion?lawd_code=11680&months=1').json()
    assert data['counts']['missing'] == len(data['items']) > 0
    assert client.post('/api/operations/ingestion/retry',json={'lawd_code':'11680','endpoint':'https://internal','month':'202609'}).status_code==422
    monkeypatch.setattr(jobs,'create_task',lambda *a:'test-job')
    row=data['items'][0]
    payload={'lawd_code':'11680','endpoint':row['endpoint'],'month':row['month']}
    from db.redis_client import get_redis
    import json
    get_redis().delete(f'ops-request:ingestion_retry:{json.dumps(payload,sort_keys=True)}')
    assert client.post('/api/operations/ingestion/retry',json=payload).json()['job_id']=='test-job'
    assert client.post('/api/operations/ingestion/retry',json=payload).status_code==409


def test_summary_owner_and_current_price_snapshot(client):
    created=client.post('/api/cases',json={'title':'요약 검증'}).json()
    candidate=client.post(f"/api/cases/{created['id']}/properties",json={'name':'후보','asking_price':600000000}).json()
    response=client.get(f"/api/cases/{created['id']}/summary")
    assert response.status_code==200
    assert response.json()['comparison']['rows'][0]['asking_price']==600000000
    assert response.json()['case']['properties'][0]['id']==candidate['id']
    client.post('/api/auth/logout')
    client.post('/api/auth/register',json={'email':'other-summary@example.com','password':'test-password-1234','name':'other'})
    assert client.get(f"/api/cases/{created['id']}/summary").status_code==404


def test_recommendation_limits_prevent_unbounded_fetch(client):
    for field,value in [('months',1000),('limit',1000),('budget_min',-1)]:
        assert client.post('/api/recommendation/complexes',json={'region':'강남구',field:value}).status_code==422
