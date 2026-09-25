"""채팅·후보 입력에서 작업 저장까지의 연결을 검증한다. 추정 엔진 정확도와 구분한다."""
import time
from types import SimpleNamespace

import pytest

from tests.test_purchase_cases import client, _register


def test_job_result_serializes_real_pipeline_models(monkeypatch):
    import json
    from api import jobs
    from backend.intent_agent import PropertyIntent
    captured = {}
    monkeypatch.setattr(jobs, "get_redis", lambda: SimpleNamespace(set=lambda key, value, ex: captured.update(value=value)))
    jobs._save("serialization", {"result": {"intent": PropertyIntent(area_min=84.9)}}, 30)
    assert json.loads(captured["value"])["result"]["intent"]["area_min"] == 84.9


def test_confirmed_area_overrides_model_interpretation(monkeypatch):
    from backend import geocoding
    from backend.intent_agent import PropertyIntent
    value = PropertyIntent(area_min=40, area_max=40, location_raw="서울")
    monkeypatch.setattr(geocoding, "geocode", lambda *a, **k: None)
    geocoding.geocoding_node({"intent": value, "raw_inputs": {"area_sqm": 84.9}})
    assert value.area_min == value.area_max == 84.9


def test_explicit_appraisal_command_does_not_wait_for_model(monkeypatch):
    from backend import model_factory
    from backend.graphs.concierge_graph import decide_node
    def unavailable():
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(model_factory, "get_llm_json", unavailable)
    assert decide_node({"message": "선택한 후보의 AVM 시세를 추정해줘"})["decision"].intent.value == "appraise"
    assert decide_node({"message": "선택한 후보의 AVM 시세를 추정하지 마"}).get("routing_error")


def test_candidate_appraisal_cannot_disable_history(client):
    _, case_id, candidate_id = setup_candidate(client)
    assert client.post("/api/appraisal/jobs", json={"user_input": "시세 추정", "case_id": case_id,
        "candidate_id": candidate_id, "save_history": False}).status_code == 422


def setup_candidate(client):
    owner = _register(client, "candidate-avm@example.com")
    case = client.post("/api/cases", json={"title": "AVM 연결"}).json()
    candidate = client.post(f"/api/cases/{case['id']}/properties", json={
        "name": "래미안퍼스티지", "address": "서울특별시 서초구 반포동 18-1", "area_sqm": 84.9,
        "category": "아파트", "asking_price": 900_000_000,
    }).json()
    return owner, case["id"], candidate["id"]


def wait_job(client, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client.get(f"/api/appraisal/jobs/{job_id}").json()
        if result["status"] in {"done", "error"}:
            return result
        time.sleep(0.02)
    pytest.fail("작업 완료 시간 초과")


def route_appraisal(monkeypatch):
    from backend import model_factory
    monkeypatch.setattr(model_factory, "get_llm_json", lambda: SimpleNamespace(invoke=lambda _: SimpleNamespace(content='{"intent":"appraise","criteria":{}}')))


def test_chat_runs_owned_candidate_and_persists_result(client, monkeypatch):
    from backend import router
    _, case_id, candidate_id = setup_candidate(client)
    route_appraisal(monkeypatch)
    captured = {}
    def fake_appraisal(query, building_name, **kwargs):
        captured.update(kwargs)
        captured["query"] = query
        return {"analysis_result": {"estimated_value": 87_000, "value_unit": "만원",
                "comparable_count": 1, "comparables": [], "used_months": 13}, "final_report": "평가용 결과"}
    monkeypatch.setattr(router, "run_appraisal", fake_appraisal)
    response = client.post("/api/concierge/messages", json={"message": "이 후보 시세를 추정해줘", "case_id": case_id, "candidate_id": candidate_id})
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    job = wait_job(client, response.json()["data"]["job_id"])
    assert job["status"] == "done" and job["history_id"]
    assert captured["area_sqm"] == 84.9
    assert captured["address"] == "서울특별시 서초구 반포동 18-1"
    value = client.get(f"/api/cases/{case_id}").json()["properties"][0]
    assert value["appraisal"]["estimated_value"] == 870_000_000
    assert value["history_id"] == job["history_id"]
    comparison = client.get(f"/api/cases/{case_id}/comparison").json()["rows"][0]
    assert comparison["appraisal_confidence"] < 0.5
    assert comparison["appraisal_comparable_count"] == 1
    assert comparison["price_gap_ratio"] is None


def test_chat_requires_explicit_candidate_and_checks_owner_before_llm(client, monkeypatch):
    _, case_id, candidate_id = setup_candidate(client)
    route_appraisal(monkeypatch)
    result = client.post("/api/concierge/messages", json={"message": "시세 추정"}).json()
    assert result["status"] == "needs_input" and "candidate" in result["missing_fields"]
    client.cookies.clear()
    _register(client, "candidate-avm-attacker@example.com")
    assert client.post("/api/concierge/messages", json={"message": "시세 추정", "case_id": case_id, "candidate_id": candidate_id}).status_code == 404


def test_missing_candidate_details_do_not_start_job(client, monkeypatch):
    _, case_id, _ = setup_candidate(client)
    route_appraisal(monkeypatch)
    candidate = client.post(f"/api/cases/{case_id}/properties", json={"name": "자료 부족"}).json()
    result = client.post("/api/concierge/messages", json={"message": "시세 추정", "case_id": case_id, "candidate_id": candidate["id"]}).json()
    assert result["status"] == "needs_input"
    assert set(result["missing_fields"]) == {"address", "area_sqm", "property_type"}
    assert "job_id" not in result["data"]


def test_required_candidate_save_failure_is_not_success(client, monkeypatch):
    from api import case_db
    from backend import router
    _, case_id, candidate_id = setup_candidate(client)
    route_appraisal(monkeypatch)
    monkeypatch.setattr(router, "run_appraisal", lambda *a, **k: {"analysis_result": {"estimated_value": 10}})
    monkeypatch.setattr(case_db, "link_appraisal", lambda *a, **k: False)
    result = client.post("/api/concierge/messages", json={"message": "시세 추정", "case_id": case_id, "candidate_id": candidate_id}).json()
    assert wait_job(client, result["data"]["job_id"])["status"] == "error"
