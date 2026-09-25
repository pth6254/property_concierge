"""실제 API·DB·Redis·계산기를 지나는 매수 판단 회귀 시나리오."""
import time
from datetime import datetime, timezone

from tests.test_listing_import import regions, row, upload
from tests.test_market_explorer import client


def _wait(client, job_id):
    until = time.monotonic() + 10
    while time.monotonic() < until:
        result = client.get(f"/api/appraisal/jobs/{job_id}").json()
        if result["status"] in {"done", "error"}:
            return result
        time.sleep(0.02)
    raise AssertionError("AVM 작업 완료를 기다리는 동안 시간 초과")


def test_listing_to_avm_funding_decision_and_re_review(regions, monkeypatch):
    from backend import router

    client = regions
    monkeypatch.setattr(router, "run_appraisal", lambda *args, **kwargs: {
        "analysis_result": {"estimated_value": 78000, "value_unit": "만원",
                            "comparable_count": 0, "comparables": [], "used_months": 0},
        "final_report": "고정 입력 연결 검증",
    })
    assert upload(client, [row()]).json()["created"] == 1
    listing = client.get("/api/listings").json()["items"][0]
    case_id = client.post("/api/cases", json={"title": "전체 판단 검증"}).json()["id"]
    candidate_id = client.post(f"/api/listings/{listing['id']}/candidate",
                               json={"case_id": case_id}).json()["id"]

    def analyze(price):
        started = client.post("/api/appraisal/jobs", json={
            "user_input": "서울특별시 강남구 역삼동 123 아파트 84.5㎡ 매매",
            "building_name": "수입 검증 매물", "address": "서울특별시 강남구 역삼동 123",
            "property_category": "주거용", "property_detail": "아파트", "area_sqm": 84.5,
            "case_id": case_id, "candidate_id": candidate_id,
        })
        assert started.status_code == 200, started.text
        completed = _wait(client, started.json()["job_id"])
        assert completed["status"] == "done" and completed["history_id"]
        funded = client.post("/api/simulation", json={
            "case_id": case_id, "candidate_id": candidate_id, "purchase_price": price,
            "loan_ratio": 0.5, "annual_interest_rate": 4, "annual_income": 100000000,
            "cash_available": 700000000, "monthly_payment_limit": 10000000,
        })
        assert funded.status_code == 200 and not funded.json().get("error"), funded.text
        return completed["history_id"]

    first_history = analyze(800000000)
    comparison = client.get(f"/api/cases/{case_id}/comparison").json()["rows"][0]
    assert comparison["estimated_value"] == 780000000
    assert comparison["appraisal_confidence"] < 0.5 and comparison["price_gap"] is None
    assert comparison["funding"]["purchase_price"] == 800000000
    assert client.post(f"/api/cases/{case_id}/decision", json={
        "property_id": candidate_id, "reason": "8억 자금 계획을 확인함"}).status_code == 200

    assert upload(client, [row(asking_price="900000000",
                               confirmed_at=datetime.now(timezone.utc).isoformat())]).json()["updated"] == 1
    source = client.get(f"/api/cases/{case_id}").json()["properties"][0]["source_status"]
    current = source["current"]
    applied = client.post(f"/api/cases/{case_id}/properties/{candidate_id}/source-update", json={
        "expected_revision_id": current["revision_id"], "expected_confirmed_at": current["confirmed_at"],
    })
    assert applied.status_code == 200 and applied.json()["decision_reopened"]
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["selected_property_id"] is None
    assert {a["analysis_type"]: a["status"] for a in detail["properties"][0]["analyses"]} == {
        "appraisal": "stale", "simulation": "stale"}
    assert client.post(f"/api/cases/{case_id}/decision", json={
        "property_id": candidate_id, "reason": "오래된 분석으로 선택"}).status_code == 422

    second_history = analyze(900000000)
    assert second_history != first_history
    comparison = client.get(f"/api/cases/{case_id}/comparison").json()["rows"][0]
    assert comparison["asking_price"] == comparison["funding"]["purchase_price"] == 900000000
    assert comparison["analysis_status"]["appraisal"] == "completed"
    assert comparison["analysis_status"]["simulation"] == "completed"
    assert client.post(f"/api/cases/{case_id}/decision", json={
        "property_id": candidate_id, "reason": "9억 가격과 자금을 다시 확인함"}).status_code == 200
    restored = client.get(f"/api/cases/{case_id}").json()
    assert restored["selected_property_id"] == candidate_id
    assert restored["properties"][0]["source_reviews"][0]["previous_decision"]["reason"] == "8억 자금 계획을 확인함"
