"""저장·권한 처리에서 분리한 내부 검증 계약과 서비스 인증 경계를 확인한다."""
import csv
import io

from tests.test_market_explorer import client
from tests.test_listing_import import row


def request_body():
    data = io.StringIO()
    writer = csv.DictWriter(data, fieldnames=list(row()))
    writer.writeheader()
    writer.writerow(row())
    return {"user_id": 1, "source_name": "내부 검증", "csv_text": data.getvalue(),
            "regions": [{"code": "1168010100", "full_name": "서울특별시 강남구 역삼동"}]}


def test_internal_import_requires_service_auth(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "test-internal-secret-" + "a" * 32)
    assert client.post("/internal/v1/listing-import/validate", json=request_body()).status_code == 401
    assert client.post("/internal/v1/listing-import/validate", json=request_body(),
                       headers={"X-Internal-Service-Key": "wrong"}).status_code == 401


def test_internal_import_never_queries_or_writes_database(client, monkeypatch):
    from db import base
    def forbidden():
        raise AssertionError("내부 입력 검증에서 DB 접근 금지")
    monkeypatch.setattr(base, "session_scope", forbidden)
    key = "test-internal-secret-" + "a" * 32
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", key)
    result = client.post("/internal/v1/listing-import/validate", json=request_body(),
                         headers={"X-Internal-Service-Key": key})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["validation"]["valid"] and not body["validation"]["committed"]
    assert body["rows"][0]["price"] == 800000000
    assert body["rows"][0]["payload"]["legal_region_code"] == "1168010100"
    assert "address_token" not in body["rows"][0]["payload"]


def test_private_service_mode_rejects_direct_business_request(client, monkeypatch):
    import os
    key = os.environ["INTERNAL_SERVICE_SECRET"]
    monkeypatch.setenv("REQUIRE_INTERNAL_SERVICE_AUTH", "1")
    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as private:
        private.cookies.update(client.cookies)
        assert private.get("/health").status_code == 200
        assert private.get("/api/activity").status_code == 401
        assert private.get("/api/activity", headers={"X-Internal-Service-Key": key}).status_code == 404
        assert private.get("/internal/v1/data/market/regions", headers={"X-Internal-Service-Key": key}).status_code == 200
        assert private.get("/api/listings", headers={"X-Internal-Service-Key": key}).status_code == 404
        # 서비스 키만 있어도 브라우저 쿠키를 AI 행위자로 해석하지 않는다.
        assert private.get("/internal/v1/ai/chat/conversations/00000000-0000-0000-0000-000000000001",
                           headers={"X-Internal-Service-Key": key}).status_code == 401


def test_stored_case_decoration_has_no_database_access(client, monkeypatch):
    from db import base
    def forbidden():
        raise AssertionError("전달된 스냅샷을 분석할 때 DB 접근 금지")
    monkeypatch.setattr(base, "session_scope", forbidden)
    key = "test-internal-secret-" + "a" * 32
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", key)
    timestamp = "2026-10-01 00:00:00"
    snapshot = {"case": {"id": 1, "user_id": 99, "title": "경계 검증", "status": "reviewing", "purpose": "purchase",
        "budget_min": None, "budget_max": None, "buyer_profile": {}, "target_regions": [], "notes": "",
        "selected_property_id": None, "decision_reason": "", "decided_at": None, "created": timestamp, "updated": timestamp},
        "histories": {"9": {"id": 9, "query": "고정 AVM", "created": timestamp,
                            "result": {"analysis_result": {"estimated_value": 78000, "value_unit": "만원"}}}},
        "regions": [], "properties": [{"property": {"id": 2, "case_id": 1, "name": "단지", "address": "서울특별시",
            "category": "apartment", "asking_price": 800000000, "area_sqm": 84.0, "legal_region_code": None,
            "source": "appraisal", "status": "reviewing", "notes": "", "history_id": 9, "source_listing_id": None,
            "source_snapshot": {}, "created": timestamp, "updated": timestamp},
            "source_status": None, "source_reviews": [], "analyses": [], "checklist": []}]}
    response = client.post("/internal/v1/decision/decorate", json={"snapshot": snapshot},
                           headers={"X-Internal-Service-Key": key})
    assert response.status_code == 200, response.text
    case = response.json()
    assert "user_id" not in case
    assert case["property_count"] == 1 and case["properties"][0]["appraisal"]["estimated_value"] == 780000000
    assert case["properties"][0]["next_actions"] and case["workspace"]["checklist_total"] == 0
    response = client.post("/internal/v1/appraisal/summary", json={"history_id": 9,
        "result": snapshot["histories"]["9"]["result"]}, headers={"X-Internal-Service-Key": key})
    assert response.status_code == 200 and response.json()["estimated_value"] == 780000000


def test_store_bridge_never_falls_back_to_sql_on_connection_failure(monkeypatch):
    import pytest
    import requests
    from fastapi import HTTPException
    from api.core_bridge import core_store
    def original(user_id, data):
        raise AssertionError("Spring 이전 영역을 Python이 대신 저장하면 안 됨")
    save = core_store("cases")(original)
    monkeypatch.setenv("CORE_STORAGE_URL", "http://core.test:8080")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "test-internal-secret-" + "a" * 32)
    def disconnected(*args, **kwargs):
        raise requests.ConnectionError("isolated")
    monkeypatch.setattr(requests, "post", disconnected)
    with pytest.raises(HTTPException) as caught:
        save(99, {"title": "경계 검증"})
    assert caught.value.status_code == 503


def test_pytest_refuses_a_service_storage_bridge():
    import os
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-c", "import tests.conftest"],
        env=os.environ | {"CORE_STORAGE_URL": "http://core:8080"}, text=True, capture_output=True)
    assert result.returncode != 0
    assert "pytest는 서비스 Spring 저장 주소를 사용할 수 없습니다" in result.stderr
