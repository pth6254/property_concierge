"""시점·소유권·종료 오판과 금액 단위 오류를 고정 입력으로 검증한다."""
import time
from datetime import datetime, timezone
import pytest
from tests.test_listing_import import regions, row, upload
from tests.test_market_explorer import client
from backend.services.naver_listing_collector import canonical_url, parse_money, parse_page, allow_browser_request


@pytest.mark.parametrize("text,expected", [("7억 5,000",750000000),("3억",300000000),("5,000",50000000),("80",800000),("800000원",800000),("1.5억",150000000),("협의",None),("7억~8억",None)])
def test_price_units(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize("url", ["http://fin.land.naver.com/articles/1", "https://fin.land.naver.com.evil.com/articles/1", "https://127.0.0.1/articles/1", "https://fin.land.naver.com@localhost/articles/1", "https://fin.land.naver.com:8000/articles/1", "https://fin.land.naver.com/"])
def test_url_restriction(url):
    with pytest.raises(ValueError):
        canonical_url(url)


def test_only_article_or_naver_missing_page_can_be_navigated():
    assert allow_browser_request("https://fin.land.naver.com/articles/123", navigation=True, article="123")
    assert allow_browser_request("https://fin.land.naver.com/404", navigation=True, article="123")
    assert allow_browser_request("https://financial.pstatic.net/404.html?text=home", navigation=True, article="123")
    assert not allow_browser_request("https://financial.pstatic.net/private", navigation=True, article="123")
    assert not allow_browser_request("https://fin.land.naver.com/articles/124", navigation=True, article="123")
    assert not allow_browser_request("http://127.0.0.1/admin", navigation=True, article="123")


def test_parser_does_not_confuse_area_or_availability():
    data = parse_page("매매 7억 5,000\n공급/전용면적\n112㎡/84.5㎡\n소재지\n서울특별시 강남구 역삼동 123\n확인매물 26.09.20.", "검증단지 - 네이버페이 부동산")
    assert data["outcome"] == "observed"
    assert data["fields"]["area_sqm"] == 84.5
    assert data["fields"]["asking_price"] == 750000000
    assert data["fields"]["status"] == "unknown"
    assert data["fields"]["source_confirmed_date"] == "26.09.20."
    assert data["fields"]["address"] == "서울특별시 강남구 역삼동 123"
    assert parse_page("월세 5,000/80\n전용면적 30㎡", "검증")["fields"]["monthly_rent"] == 800000
    assert parse_page("매매 7억\n공급면적 112㎡", "검증")["outcome"] == "parse_error"
    assert parse_page("페이지를 찾을 수 없습니다", "검증")["outcome"] == "unavailable"
    assert parse_page("매매 7억\n전용면적 84㎡", "검증", 403)["outcome"] == "blocked"


def test_parser_reads_live_page_label_layout_without_guessing_availability():
    # 실제 상세 화면은 값이 별도 줄에 있고 공급·전용을 따로 표기한다.
    text = ("e편한세상신곡시그니처뷰 102동 매매 6억 1,125\n확인매물 2025. 06. 04.\n"
            "기본 정보\n매매가\n6억 1,125만원\n공급면적\n99.1㎡\n전용면적\n74.92㎡ (전용률 76%)\n"
            "위치\n경기도 의정부시 신곡동 435-3")
    result = parse_page(text, "네이버페이 부동산")
    assert result["outcome"] == "observed"
    assert result["fields"]["name"] == "e편한세상신곡시그니처뷰 102동"
    assert result["fields"]["asking_price"] == 611250000
    assert result["fields"]["area_sqm"] == 74.92
    assert result["fields"]["address"] == "경기도 의정부시 신곡동 435-3"
    assert result["fields"]["status"] == "unknown"


def test_listing_address_is_not_replaced_by_broker_address():
    text = ("매매 10억\n전용면적 84.9㎡\n소재지\n서울특별시 서초구 반포동 1\n"
            "중개사 정보\n주소\n서울특별시 강남구 역삼동 2")
    assert parse_page(text, "검증 아파트")["fields"]["address"] == "서울특별시 서초구 반포동 1"
    ambiguous = "매매 10억\n전용면적 84.9㎡\n소재지 서울특별시 서초구 반포동 1\n소재지 서울특별시 서초구 서초동 2"
    assert "address" not in parse_page(ambiguous, "검증 아파트")["fields"]
    broker_only = "매매 10억\n전용면적 84.9㎡\n중개사 정보\n상호 강남중개\n대표 김검증\n소재지 서울특별시 강남구 역삼동 2"
    assert "address" not in parse_page(broker_only, "검증 아파트")["fields"]


def test_observation_failure_preserves_listing_and_blocks_fresh_recommendation(regions):
    from backend.services.listing_observations import record_observation, history
    from db.base import session_scope
    from db.models import User
    from sqlalchemy import select
    with session_scope() as session:
        owner = session.scalar(select(User.id).where(User.email == "market@example.com"))
    url="https://fin.land.naver.com/articles/123456"
    assert upload(regions,[row(external_id="custom-csv-id",source_url=url)]).json()["created"] == 1
    listing=regions.get("/api/listings").json()["items"][0]
    now=time.time()
    common={"source_url":url,"external_id":"123456","requested_at":now-1,"fetched_at":now,"fields":{},"message":"검증"}
    record_observation(owner,{**common,"outcome":"observed"})
    record_observation(owner,{**common,"outcome":"unavailable","fetched_at":now+0.001})
    updated=regions.get("/api/listings").json()["items"][0]
    assert updated["status"] == "active" and updated["asking_price"] == listing["asking_price"]
    assert updated["needs_confirmation"] and updated["last_seen_at"] == now
    assert updated["last_collection_outcome"] == "unavailable"
    assert regions.get("/api/listings?fresh_only=true").json()["total"] == 0
    assert len(history(owner,url)["items"]) == 2
    assert history(owner+999,url)["items"] == []
    # 사용자 재확인으로만 최신 추천으로 복귀한다. 원문의 확인일은 이 시간을 대체하지 않는다.
    time.sleep(0.01)
    assert upload(regions,[row(external_id="custom-csv-id",source_url=url,confirmed_at=datetime.now(timezone.utc).isoformat())]).json()["updated"] == 1
    assert regions.get("/api/listings?fresh_only=true").json()["total"] == 1


def test_listing_page_fetches_observations_in_batches(regions):
    from sqlalchemy import event
    from db.base import get_engine

    rows = [row(external_id=f"listing-{i}", source_url=f"https://fin.land.naver.com/articles/{123450+i}")
            for i in range(5)]
    assert upload(regions, rows).json()["created"] == 5
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if "listing_observations" in statement:
            statements.append(statement)

    event.listen(get_engine(), "before_cursor_execute", record)
    try:
        response = regions.get("/api/listings")
    finally:
        event.remove(get_engine(), "before_cursor_execute", record)
    assert response.status_code == 200 and response.json()["total"] == 5
    assert len(statements) == 2


def test_collection_job_and_owner_isolation(regions, monkeypatch):
    from backend.services import listing_observations
    from db.redis_client import get_redis
    get_redis().delete(*list(get_redis().scan_iter("listing-collection-cooldown:*"))) if list(get_redis().scan_iter("listing-collection-cooldown:*")) else None
    async def fake(url):
        now=time.time()
        return {"external_id":"123456","source_url":url,"requested_at":now,"fetched_at":now,"outcome":"blocked","fields":{},"message":"접근 제한"}
    monkeypatch.setattr(listing_observations,"collect_page",fake)
    assert regions.post("/api/listings/collection/jobs",json={"source_url":"https://localhost/"}).status_code == 422
    response=regions.post("/api/listings/collection/jobs",json={"source_url":"https://fin.land.naver.com/articles/123456"})
    assert response.status_code == 202
    job=response.json()["job_id"]
    for _ in range(100):
        data=regions.get(f"/api/listings/collection/jobs/{job}").json()
        if data["status"] in ("done","error"):break
        time.sleep(.02)
    assert data["status"] == "done" and data["result"]["outcome"] == "blocked"
    assert regions.post("/api/listings/collection/jobs",json={"source_url":"https://fin.land.naver.com/articles/123456"}).status_code == 429
    regions.cookies.clear()
    assert regions.get(f"/api/listings/collection/jobs/{job}").status_code == 401
    assert regions.post("/api/auth/register",json={"email":"collector-other@example.com","password":"password-12345","name":"검증"}).status_code == 201
    assert regions.get(f"/api/listings/collection/jobs/{job}").status_code == 404


def test_shared_wait_rejects_job_before_enqueue(regions, monkeypatch):
    from backend.services import listing_collection_gate as gate
    from db.redis_client import get_redis
    from api import jobs
    monkeypatch.setattr(gate, "KEY", "test:listing-collection:api-gate")
    def unexpected(*args, **kwargs):
        raise AssertionError("대기 중인 작업을 큐에 넣으면 안 됨")
    monkeypatch.setattr(jobs, "create_task", unexpected)
    try:
        gate.postpone(900)
        response = regions.post("/api/listings/collection/jobs", json={"source_url":"https://fin.land.naver.com/articles/123"})
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0
        assert "자동 재시도하지 않습니다" in response.json()["detail"]
    finally:
        get_redis().delete(gate.KEY)
