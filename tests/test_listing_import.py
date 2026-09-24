"""수입 원자성·갱신 순서·소유권·금액 단위·검색과 후보 연결을 검증한다."""
import csv
import io
import time
from datetime import datetime, timedelta, timezone
import pytest
from tests.test_market_explorer import client


def row(**changes):
    return {"external_id":"a-1", "name":"수입 검증 매물", "property_type":"apartment", "transaction_type":"purchase",
        "address":"서울특별시 강남구 역삼동 123", "legal_region_code":"1168010100", "area_sqm":"84.5", "floor":"7",
        "asking_price":"800000000", "deposit":"", "monthly_rent":"", "source_url":"https://example.com/listing/a-1",
        "confirmed_at":(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(), "status":"active", **changes}


def upload(client, rows, commit=True, source="검증 출처"):
    text=io.StringIO(); writer=csv.DictWriter(text, fieldnames=list(row()));writer.writeheader();writer.writerows(rows)
    return client.post('/api/listings/import',json={"source_name":source,"csv_text":text.getvalue(),"commit":commit})


@pytest.fixture
def regions(client):
    from db.base import session_scope
    from db.models import LegalRegion
    with session_scope() as session:
        session.add(LegalRegion(code="1168010100",parent_code="1168000000",sido_code="11",sigungu_code="680",
            eup_myeon_dong_code="101",ri_code="00",name="역삼동",full_name="서울특별시 강남구 역삼동",
            level="eup_myeon_dong",depth=3,lawd_code="11680",resident_code="",cadastral_code="",sort_order=1,remarks="",is_active=True,synced_at=time.time()))
    return client


def test_preview_commit_history_and_older_input(regions):
    client=regions; first=row()
    assert upload(client,[first],False).json()['valid']
    assert client.get('/api/listings').json()['total']==0
    assert upload(client,[first]).json()['created']==1
    assert upload(client,[first]).json()['unchanged']==1
    second={**first,"asking_price":"700000000","status":"withdrawn","confirmed_at":datetime.now(timezone.utc).isoformat()}
    assert upload(client,[second]).json()['updated']==1
    assert upload(client,[first]).json()['skipped_older']==1
    data=client.get('/api/listings').json();item=data['items'][0]
    assert item['asking_price']==700000000 and item['status']=='withdrawn'
    history=client.get(f"/api/listings/{item['id']}/history").json()['items']
    assert [h['asking_price'] for h in history]==[700000000,800000000]
    assert upload(client,[{**second,"asking_price":"1"}]).status_code==409
    assert len(client.get(f"/api/listings/{item['id']}/history").json()['items'])==2


@pytest.mark.parametrize('changes',[{"asking_price":"8억"},{"area_sqm":"NaN"},{"asking_price":"-1"},
    {"transaction_type":"rent"},{"source_url":"javascript:alert(1)"},{"legal_region_code":"1165010100"},
    {"address":"서울특별시 서초구 서초동"},{"confirmed_at":"2026-01-01T00:00:00"}])
def test_invalid_batch_never_partially_saves(regions, changes):
    client=regions; result=upload(client,[row(),row(external_id="bad",**changes)]).json()
    assert not result['valid'] and result['errors'][0]['row']==3
    assert client.get('/api/listings').json()['total']==0


def test_duplicate_unlinked_and_empty_csv(regions):
    client=regions
    assert not upload(client,[row(),row()]).json()['valid']
    result=upload(client,[row(legal_region_code="", address="알 수 없는 주소")]).json()
    assert result['committed'] and len(result['warnings'])==1
    assert client.get('/api/listings?region_code=1168000000').json()['total']==0
    assert upload(client,[]).status_code==422


def test_missing_status_is_unknown_and_conflict_rolls_back_batch(regions):
    client=regions; original=row(status="")
    assert upload(client,[original]).json()['created']==1
    assert client.get('/api/listings').json()['items'][0]['status']=='unknown'
    assert client.get('/api/listings?fresh_only=true').json()['total']==0
    assert upload(client,[row(external_id='new'),{**original,'asking_price':'750000000'}]).status_code==409
    assert client.get('/api/listings').json()['total']==1


def test_search_candidates_and_ownership(regions,monkeypatch):
    client=regions
    from tests.test_concierge_validation import route
    recent=row(); stale=row(external_id="stale",confirmed_at=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat())
    lease=row(external_id="lease",transaction_type="lease",asking_price="",deposit="500000000")
    assert upload(client,[recent,stale,lease]).json()['created']==3
    assert client.get('/api/listings?fresh_only=true').json()['total']==2
    data=client.get('/api/listings?region_code=1168010100&transaction_type=purchase&budget_max=800000000&fresh_only=true').json()
    assert data['total']==1
    assert client.get('/api/listings?budget_max=700000000').json()['total']==1
    assert client.get('/api/listings?area_min=85').json()['total']==0
    assert len(client.get('/api/listings?page_size=1&page=2').json()['items'])==1
    item=data['items'][0];case=client.post('/api/cases',json={'title':'매물 검토'}).json()
    saved=client.post(f"/api/listings/{item['id']}/candidate",json={'case_id':case['id']})
    assert saved.status_code==201
    assert saved.json()['asking_price']==800000000
    rows=client.get('/api/listings').json()['items'];old=next(r for r in rows if r['external_id']=='stale')
    assert client.post(f"/api/listings/{old['id']}/candidate",json={'case_id':case['id']}).status_code==409
    rent=next(r for r in rows if r['external_id']=='lease')
    assert client.post(f"/api/listings/{rent['id']}/candidate",json={'case_id':case['id']}).status_code==422
    route(monkeypatch,{'intent':'search_listing','criteria':{'region_name':'강남구','transaction_type':'purchase'}})
    answer=client.post('/api/concierge/messages',json={'message':'등록한 매매 매물 찾아줘'}).json()
    assert answer['tool_used']=='search_listings' and '800,000,000원' in answer['answer']
    client.cookies.clear()
    assert client.get('/api/listings').status_code==401
    assert client.post('/api/auth/register',json={'email':'listing-other@example.com','password':'listing-other-12345','name':'다른 사용자'}).status_code==201
    assert client.get('/api/listings').json()['total']==0
    assert client.get(f"/api/listings/{item['id']}/history").status_code==404
    assert client.post(f"/api/listings/{item['id']}/candidate",json={'case_id':case['id']}).status_code==404
    assert upload(client,[recent]).json()['created']==1
    own=client.get('/api/listings').json()['items'][0]
    assert client.post(f"/api/listings/{own['id']}/candidate",json={'case_id':case['id']}).status_code==404
