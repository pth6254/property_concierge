"""실제 계산부터 자금 경고·후보 비교까지 저장 경로를 검증한다."""
from tests.test_purchase_cases import client, _register


def test_real_calculation_persists_funding_and_recalculation_clears_warnings(client):
    _register(client, "funding@example.com")
    case_id = client.post("/api/cases", json={"title": "자금 검토"}).json()["id"]
    path = f"/api/cases/{case_id}"
    candidate = client.post(f"{path}/properties", json={
        "name": "자금 후보", "asking_price": 600_000_000, "category": "아파트",
    }).json()
    payload = dict(case_id=case_id, candidate_id=candidate["id"], purchase_price=600_000_000,
                   loan_ratio=0.5, annual_interest_rate=4, annual_income=100_000_000,
                   cash_available=300_000_000, monthly_payment_limit=100_000)
    response = client.post("/api/simulation", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert not body.get("error"), body
    calculated = body["result"]
    detail = client.get(path).json()["properties"][0]
    summary = next(a["summary"] for a in detail["analyses"] if a["analysis_type"] == "simulation")
    assert summary["monthly_payment"] == calculated["loan"]["monthly_payment"] > 0
    assert summary["dsr_ratio"] == calculated["finance_check"]["dsr"] > 0
    assert summary["required_cash"] == 300_000_000 + calculated["acquisition_cost"]["total"]
    assert summary["cash_shortfall"] == calculated["acquisition_cost"]["total"] > 0
    assert {"funding_shortfall", "funding_payment"} <= {a["code"] for a in detail["next_actions"]}
    assert not client.get(f"{path}/comparison").json()["rows"][0]["decision_ready"]

    payload.update(cash_available=summary["required_cash"], monthly_payment_limit=summary["monthly_payment"])
    assert not client.post("/api/simulation", json=payload).json().get("error")
    detail = client.get(path).json()["properties"][0]
    assert not any(a["code"].startswith("funding_") for a in detail["next_actions"])
    assert next(c for c in detail["checklist"] if c["category"] == "funding")["status"] == "done"
    funding = client.get(f"{path}/comparison").json()["rows"][0]["funding"]
    assert funding["cash_shortfall"] == 0 and funding["monthly_payment_exceeded"] is False

    client.patch(f"{path}/properties/{candidate['id']}", json={"asking_price": 610_000_000})
    assert "simulation_price" in {a["code"] for a in client.get(path).json()["properties"][0]["next_actions"]}


def test_missing_funding_criteria_and_legacy_results_remain_unverified():
    from backend.services.candidate_funding import funding_issues
    assert funding_issues({})[0][0] == "funding_details"
    summary = dict(required_cash=100, monthly_payment=10, loan_amount=50)
    assert {i[0] for i in funding_issues(summary)} == {"funding_cash_input", "funding_payment_input", "funding_income"}
    summary.update(cash_available=100, cash_shortfall=0, monthly_payment_limit=10,
                   monthly_payment_exceeded=False, finance_check={"dsr": 0.5, "dsr_exceeded": True})
    assert {i[0] for i in funding_issues(summary)} == {"funding_finance"}
    summary.update(loan_amount=0, monthly_payment=0)
    assert not funding_issues(summary)


def test_candidate_disappearing_during_calculation_does_not_report_saved(client, monkeypatch):
    import pytest
    import requests
    from fastapi import HTTPException
    from backend.services.funding_execution_client import execute_simulation
    from schemas.funding_request import SimulationRequest
    user_id = _register(client, "funding-save@example.com")
    case_id = client.post("/api/cases", json={"title": "저장 검증"}).json()["id"]
    candidate = client.post(f"/api/cases/{case_id}/properties", json={"name": "후보"}).json()
    # 저장 중 삭제는 Spring 컨트롤러 테스트에서 재현한다. 클라이언트도 실패를 성공으로 바꾸지 않는다.
    response = requests.Response()
    response.status_code = 404
    monkeypatch.setattr('backend.services.funding_execution_client.request_core', lambda *args: response)
    with pytest.raises(HTTPException) as failure:
        execute_simulation(SimulationRequest(case_id=case_id, candidate_id=candidate['id'], purchase_price=600_000_000), {'id': user_id})
    assert failure.value.status_code == 404
    assert client.get(f'/api/cases/{case_id}').json()['properties'][0]['analyses'] == []
