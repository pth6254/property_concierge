"""후보 한 번에 검토: 실제 Spring 저장·Kotlin 계산과 작업 실행기를 거쳐 기존 분석 경계를 지키는지 검증한다.

AVM 추정 엔진은 모의한다. 가격 정확도가 아니라 실행 조건·저장·재실행 방지·개별 조건 보존을 확인한다.
"""
import pytest

from backend.services.candidate_funding import profile_funding_inputs
from tests.test_candidate_avm import wait_job
from tests.test_purchase_cases import client, _register

PROFILE = dict(cash_available=400_000_000, emergency_reserve=50_000_000, monthly_payment_limit=2_000_000,
               annual_income=100_000_000, existing_loan_annual_payment=0, loan_ratio=0.5,
               annual_interest_rate=4.25, loan_years=30, owned_homes=1, adjusted_area=False)


def fake_appraisal(monkeypatch, calls):
    from backend import router

    def run(query, building_name, **kwargs):
        calls.append(kwargs)
        return {"analysis_result": {"estimated_value": 61_000, "value_unit": "만원", "comparable_count": 6,
                                    "comparables": [], "used_months": 6}, "final_report": "검증용 결과"}
    monkeypatch.setattr(router, "run_appraisal", run)


def setup(client, email, profile=PROFILE, area_basis="exclusive"):
    _register(client, email)
    case = client.post("/api/cases", json={"title": "한 번에 검토", **({"buyer_profile": profile} if profile else {})})
    assert case.status_code == 201, case.text
    candidate = client.post(f"/api/cases/{case.json()['id']}/properties", json={
        "name": "래미안퍼스티지", "address": "서울특별시 서초구 반포동 18-1", "area_sqm": 84.9, "category": "아파트",
        "asking_price": 600_000_000, "identity": {"area_basis": area_basis}})
    assert candidate.status_code == 201, candidate.text
    return case.json()["id"], candidate.json()["id"]


def review(client, case_id, candidate_id, expected=200):
    response = client.post(f"/api/cases/{case_id}/properties/{candidate_id}/quick-review")
    assert response.status_code == expected, response.text
    return response.json()


def analyses(client, case_id, candidate_id):
    item = next(p for p in client.get(f"/api/cases/{case_id}").json()["properties"] if p["id"] == candidate_id)
    return {a["analysis_type"]: a for a in item["analyses"]}


def test_runs_funding_from_common_profile_and_queues_candidate_appraisal(client, monkeypatch):
    calls = []
    fake_appraisal(monkeypatch, calls)
    case_id, candidate_id = setup(client, "quick-review@example.com")
    result = review(client, case_id, candidate_id)

    funding = result["funding"]
    assert funding["status"] == "calculated" and funding["input_source"] == "profile"
    assert funding["summary"]["purchase_price"] == 600_000_000
    assert funding["summary"]["required_cash"] > 0
    saved = analyses(client, case_id, candidate_id)["simulation"]["summary"]
    # 공통 조건의 비상자금은 한 번만 뺀다(AGENTS 2-12).
    assert saved["inputs"]["cash_available"] == 350_000_000
    assert saved["home_count_basis"] == "after_purchase"

    assert result["appraisal"]["status"] == "queued"
    job = wait_job(client, result["appraisal"]["job_id"])
    assert job["status"] == "done" and job["history_id"]
    assert calls[0]["area_sqm"] == 84.9 and calls[0]["valuation_context"]["area_basis"] == "exclusive"
    assert "appraisal" in analyses(client, case_id, candidate_id)
    assert result["rights"]["status"] == "needs_document"


def test_current_analyses_are_kept_and_stale_funding_uses_saved_individual_conditions(client, monkeypatch):
    calls = []
    fake_appraisal(monkeypatch, calls)
    case_id, candidate_id = setup(client, "quick-review-keep@example.com")
    # 후보별로 공통 조건과 다른 현금을 저장해 둔다.
    individual = {**profile_funding_inputs(PROFILE), "cash_available": 123_000_000}
    saved = client.post("/api/simulation", json={"case_id": case_id, "candidate_id": candidate_id,
        "purchase_price": 600_000_000, "property_type": "아파트", **individual})
    assert saved.status_code == 200, saved.text
    first = review(client, case_id, candidate_id)
    assert first["funding"]["status"] == "current"  # 유효한 개별 조건을 공통 조건으로 덮어쓰지 않는다
    wait_job(client, first["appraisal"]["job_id"])

    again = review(client, case_id, candidate_id)
    assert again["funding"]["status"] == "current" and again["appraisal"]["status"] == "current"
    assert len(calls) == 1  # 유효한 시세 분석이 있으면 작업을 새로 만들지 않는다

    changed = client.patch(f"/api/cases/{case_id}/properties/{candidate_id}", json={"asking_price": 650_000_000})
    assert changed.status_code == 200, changed.text
    # 희망가만 바뀌면 저장 상태는 completed로 남고, 다음 행동이 가격 차이로 재검토를 안내한다. 같은 기준으로 다시 계산한다.
    assert analyses(client, case_id, candidate_id)["simulation"]["summary"]["purchase_price"] == 600_000_000
    after = review(client, case_id, candidate_id)
    assert after["funding"]["status"] == "calculated" and after["funding"]["input_source"] == "saved"
    summary = analyses(client, case_id, candidate_id)["simulation"]["summary"]
    assert summary["purchase_price"] == 650_000_000
    assert summary["inputs"]["cash_available"] == 123_000_000  # 이미 비상자금을 뺀 개별 현금을 다시 빼지 않는다
    # 시세 추정은 희망가와 무관하므로 유효한 결과를 다시 만들지 않는다.
    assert after["appraisal"]["status"] == "current" and len(calls) == 1


def test_missing_conditions_do_not_calculate_or_start_appraisal(client, monkeypatch):
    calls = []
    fake_appraisal(monkeypatch, calls)
    case_id, candidate_id = setup(client, "quick-review-missing@example.com", profile=None, area_basis="unknown")
    result = review(client, case_id, candidate_id)
    assert result["funding"]["status"] == "needs_input"
    assert "cash_available" in result["funding"]["missing"]
    # 아파트 면적 기준이 미확인이면 정책상 항상 보류되므로 작업을 만들지 않고 입력을 요청한다.
    assert result["appraisal"] == {**result["appraisal"], "status": "needs_input", "missing": ["area_basis"]}
    assert result["appraisal"]["input_url"] == f"/appraisal?caseId={case_id}&candidateId={candidate_id}"
    assert calls == [] and analyses(client, case_id, candidate_id) == {}


@pytest.mark.parametrize("area_basis,missing", [("supply", "exclusive_area_sqm")])
def test_supply_area_is_not_used_as_exclusive(client, monkeypatch, area_basis, missing):
    calls = []
    fake_appraisal(monkeypatch, calls)
    case_id, candidate_id = setup(client, "quick-review-supply@example.com", area_basis=area_basis)
    result = review(client, case_id, candidate_id)
    assert result["appraisal"]["status"] == "needs_input" and missing in result["appraisal"]["missing"]
    assert calls == []


def test_other_users_and_rejected_candidates_are_refused(client, monkeypatch):
    fake_appraisal(monkeypatch, [])
    case_id, candidate_id = setup(client, "quick-review-owner@example.com", profile=None, area_basis="unknown")
    rejected = client.patch(f"/api/cases/{case_id}/properties/{candidate_id}", json={"status": "rejected"})
    assert rejected.status_code == 200, rejected.text
    review(client, case_id, candidate_id, expected=422)
    client.cookies.clear()
    _register(client, "quick-review-attacker@example.com")
    review(client, case_id, candidate_id, expected=404)


def test_invalid_common_profile_does_not_block_saved_individual_conditions(monkeypatch):
    from backend.services import candidate_quick_review as review_module
    from backend.services import funding_execution_client
    captured = {}

    def execute(request, user):
        captured["request"] = request
        return {"candidate_funding": {"purchase_price": request.purchase_price, "required_cash": 1, "cash_shortfall": 0,
                                      "monthly_payment": 1, "cash_available": request.cash_available}}
    monkeypatch.setattr(funding_execution_client, "execute_simulation", execute)
    saved = {"status": "completed", "summary": {"purchase_price": 600_000_000, "inputs": {
        **profile_funding_inputs(PROFILE), "cash_available": 123_000_000, "purchase_price": 600_000_000, "case_id": 9}}}
    case = {"id": 1, "buyer_profile": {"loan_ratio": "형식 오류"}}
    candidate = {"id": 2, "asking_price": 650_000_000, "category": "아파트"}
    result = review_module._funding(case, candidate, saved, user_id=3)
    assert result["status"] == "calculated" and result["input_source"] == "saved"
    assert captured["request"].cash_available == 123_000_000 and captured["request"].purchase_price == 650_000_000
    # 저장 조건도 없으면 공통 조건을 고치라고 알린다.
    assert review_module._funding(case, candidate, None, user_id=3) == {
        "status": "needs_input", "missing": ["buyer_profile"], "input_source": "profile"}
