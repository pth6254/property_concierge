"""수집된 실거래 기반 자치구 탐색 API 테스트."""
from __future__ import annotations

import os
import time
import pytest

os.environ.setdefault("DISABLE_RATE_LIMIT", "1")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-market-explorer")


@pytest.fixture()
def client():
    from tests.service_client import ServiceTestClient as TestClient
    from db.base import session_scope
    from db.models import CaseRegion, PurchaseCase, LegalRegion, Transaction, User
    from tests.conftest import truncate_tables

    truncate_tables(CaseRegion, PurchaseCase, Transaction, LegalRegion, User)
    with session_scope() as session:
        session.add_all([
            LegalRegion(code="1100000000", parent_code=None, sido_code="11", sigungu_code="000",
                        eup_myeon_dong_code="000", ri_code="00", name="서울특별시", full_name="서울특별시",
                        level="sido", depth=1, lawd_code=None, resident_code="", cadastral_code="",
                        sort_order=1, remarks="", is_active=True, synced_at=time.time()),
            LegalRegion(code="1168000000", parent_code="1100000000", sido_code="11", sigungu_code="680",
                        eup_myeon_dong_code="000", ri_code="00", name="강남구", full_name="서울특별시 강남구",
                        level="sigungu", depth=2, lawd_code="11680", resident_code="", cadastral_code="",
                        sort_order=1, remarks="", is_active=True, synced_at=time.time()),
            LegalRegion(code="1165000000", parent_code="1100000000", sido_code="11", sigungu_code="650",
                        eup_myeon_dong_code="000", ri_code="00", name="서초구", full_name="서울특별시 서초구",
                        level="sigungu", depth=2, lawd_code="11650", resident_code="", cadastral_code="",
                        sort_order=2, remarks="", is_active=True, synced_at=time.time()),
        ])
        session.add_all([
            Transaction(endpoint="RTMSDataSvcAptTrade", category="주거용", lawd_cd="11680", deal_ym="202608",
                        price=120000, area_sqm=84, per_sqm=1429, apt_name="강남단지", is_cancelled=False),
            Transaction(endpoint="RTMSDataSvcAptTrade", category="주거용", lawd_cd="11680", deal_ym="202608",
                        price=90000, area_sqm=59, per_sqm=1525, apt_name="강남단지2", is_cancelled=True),
            Transaction(endpoint="RTMSDataSvcLandTrade", category="토지", lawd_cd="11650", deal_ym="202607",
                        price=50000, area_sqm=100, per_sqm=500, apt_name="서초 토지", is_cancelled=False),
        ])

    from api.main import app
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/register", json={
            "email": "market@example.com", "password": "test-password-1234", "name": "market",
        })
        assert response.status_code == 201
        yield test_client


def test_apartment_summary_uses_collected_transactions(client):
    response = client.get("/api/market/districts?property_type=apartment&months=12&budget_max=100000")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "국토교통부 실거래가"
    assert body["period"] == {"from": "202509", "to": "202608"}
    assert len(body["items"]) == 1
    assert body["items"][0]["region_name"] == "서울특별시 강남구"
    assert body["items"][0]["deal_count"] == 1  # 해제 거래 제외
    assert body["items"][0]["budget_fit_count"] == 0
    assert body["items"][0]["median_price"] == 120000
    assert body["items"][0]["price_q1"] == 120000
    assert body["items"][0]["price_q3"] == 120000
    assert body["items"][0]["budget_fit_ratio"] == 0
    assert body["items"][0]["confidence"] == "low"


def test_market_summary_requires_login(client):
    client.cookies.clear()
    assert client.get("/api/market/districts").status_code == 401
    assert client.get("/api/market/regions").status_code == 401


def test_region_hierarchy_and_code_based_summary(client):
    regions = client.get("/api/market/regions").json()["items"]
    assert regions == [{
        "code": "1100000000", "parent_code": None, "name": "서울특별시",
        "full_name": "서울특별시", "level": "sido", "lawd_code": None,
    }]

    response = client.get(
        "/api/market/regions/summary"
        "?region_code=1100000000&property_type=apartment&months=12"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scope"]["code"] == "1100000000"
    assert body["items"][0]["region_code"] == "1168000000"


def test_concierge_routes_to_real_market_tool(client, monkeypatch):
    from backend import model_factory

    class FakeResponse:
        def __init__(self, content):
            self.content = content

    class FakeRouter:
        def invoke(self, messages):
            del messages
            return FakeResponse(
                '{"intent":"find_region","criteria":{"property_type":"apartment",'
                '"transaction_type":"purchase","budget_max_won":1000000000,'
                '"region_name":"서울","region_code":null}}'
            )

    class FakeWriter:
        def invoke(self, messages):
            del messages
            return FakeResponse("국토교통부 실거래 자료를 기준으로 비교했습니다.")

    monkeypatch.setattr(model_factory, "get_chat_llm", lambda **kwargs: FakeRouter() if kwargs.get("json_mode") else FakeWriter())

    response = client.post("/api/concierge/messages", json={
        "message": "서울에서 10억 이하 아파트 동네를 추천해줘",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "find_region"
    assert body["status"] == "completed"
    assert body["tool_used"] == "find_regions"
    assert body["criteria"]["region_code"] == "1100000000"
    assert body["data"]["items"][0]["region_name"] == "서울특별시 강남구"


def test_case_region_saves_server_calculated_snapshot(client):
    case_id = client.post("/api/cases", json={"title": "강남권 검토"}).json()["id"]
    response = client.post(f"/api/cases/{case_id}/regions", json={
        "region_code": "1168000000", "property_type": "apartment",
        "budget_max_won": 1_000_000_000, "source": "market_explorer",
    })
    assert response.status_code == 201
    saved = response.json()
    assert saved["region_name"] == "서울특별시 강남구"
    assert saved["stats_snapshot"]["median_price"] == 120000
    assert saved["stats_snapshot"]["confidence"] == "low"

    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["target_regions"] == ["서울특별시 강남구"]
    assert detail["regions"][0]["region_code"] == "1168000000"

    assert client.post(f"/api/cases/{case_id}/regions", json={
        "region_code": "1168000000", "property_type": "apartment",
    }).status_code == 201
    assert len(client.get(f"/api/cases/{case_id}").json()["regions"]) == 1


def test_other_user_cannot_access_case_regions(client):
    case_id = client.post("/api/cases", json={"title": "소유자 케이스"}).json()["id"]
    region = client.post(f"/api/cases/{case_id}/regions", json={
        "region_code": "1168000000", "property_type": "apartment",
    }).json()

    client.cookies.clear()
    response = client.post("/api/auth/register", json={
        "email": "market-attacker@example.com", "password": "test-password-1234", "name": "attacker",
    })
    assert response.status_code == 201
    assert client.post(f"/api/cases/{case_id}/regions", json={
        "region_code": "1168000000", "property_type": "apartment",
    }).status_code == 404
    assert client.delete(f"/api/cases/{case_id}/regions/{region['id']}").status_code == 404
