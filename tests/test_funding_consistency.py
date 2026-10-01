"""같은 매수 조건을 화면·대화·케이스 비교에 전달해 실제 계산과 저장 내용을 대조한다."""
import pytest

from api.routes.simulation import SimulationRequest
from backend.concierge.decision_tools import simulate_investment
from backend.services.candidate_funding import profile_funding_inputs
from schemas.simulation import SimulationInput
from tests.test_purchase_cases import client, _register


@pytest.mark.parametrize("owned_homes,tax", [(1, 6_600_000), (2, 48_000_000), (3, 72_000_000)])
def test_after_purchase_count_matches_real_api_chat_and_case_scenario(client, owned_homes, tax):
    user_id = _register(client, f"funding-{owned_homes}@example.com")
    profile = dict(cash_available=400_000_000, emergency_reserve=50_000_000,
                   monthly_payment_limit=2_000_000, annual_income=100_000_000,
                   existing_loan_annual_payment=1_200_000, loan_ratio=0.5,
                   annual_interest_rate=4.25, loan_years=27, owned_homes=owned_homes,
                   adjusted_area=False)
    created = client.post("/api/cases", json={"title": "입력 조건 일치", "buyer_profile": profile})
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    path = f"/api/cases/{case_id}"
    candidate = client.post(f"{path}/properties", json={
        "name": "입력 대조 후보", "asking_price": 600_000_000, "category": "apartment",
    }).json()
    payload = {"case_id": case_id, "candidate_id": candidate["id"], "purchase_price": 600_000_000,
               "property_type": "아파트", **profile_funding_inputs(profile)}
    direct = client.post("/api/simulation", json=payload)
    assert direct.status_code == 200, direct.text
    body = direct.json()
    assert not body.get("error"), body
    # 현재 간이 모델의 분기를 고정한다. 최신 법령의 모든 예외를 검증하는 테스트는 아니다.
    assert body["result"]["acquisition_cost"]["acquisition_tax"] == tax
    assert body["result"]["owned_homes"] == owned_homes
    assert body["result"]["home_count_basis"] == "after_purchase"
    expected = body["candidate_funding"]
    assert expected["inputs"]["owned_homes"] == owned_homes
    assert expected["home_count_basis"] == "after_purchase"
    assert expected["cash_available"] == 350_000_000
    assert f"{owned_homes}주택 (이번 취득 포함)" in body["report"]

    chat = simulate_investment({}, user_id, {"case_id": case_id, "candidate_id": candidate["id"]})
    assert chat.status == "completed"
    assert chat.data["candidate_funding"] == expected
    assert f"취득 후 {owned_homes}주택" in chat.data["answer"]
    scenario = client.post(f"{path}/funding-scenarios", json={})
    assert scenario.status_code == 200, scenario.text
    row = scenario.json()["rows"][0]
    assert row["baseline"]["summary"] == row["scenario"]["summary"] == expected
    stored = next(a for a in client.get(path).json()["properties"][0]["analyses"] if a["analysis_type"] == "simulation")
    assert stored["summary"] == expected


def test_cash_override_does_not_subtract_reserve_twice():
    profile = {"cash_available": 400_000_000, "emergency_reserve": 50_000_000, "owned_homes": 2}
    assert profile_funding_inputs(profile)["cash_available"] == 350_000_000
    assert profile_funding_inputs(profile, {"cash_available": 300_000_000})["cash_available"] == 300_000_000
    assert profile_funding_inputs(profile)["owned_homes"] == 2
    assert profile["cash_available"] == 400_000_000


@pytest.mark.parametrize("value", [0, -1, 1.5, 101])
def test_invalid_after_purchase_count_is_rejected_everywhere(value):
    from schemas.concierge import ConciergeFunding
    from schemas.purchase_case import BuyerProfile
    from pydantic import ValidationError
    for model in (SimulationRequest, SimulationInput, ConciergeFunding, BuyerProfile):
        payload = {"purchase_price": 600_000_000} if model in (SimulationRequest, SimulationInput) else {}
        assert model.model_validate({**payload, "owned_homes": 1}).owned_homes == 1
        with pytest.raises(ValidationError):
            model.model_validate({**payload, "owned_homes": value})


def test_zero_income_remains_unverified_in_chat_and_scenario(client):
    user_id = _register(client, "zero-income@example.com")
    profile = dict(cash_available=400_000_000, monthly_payment_limit=2_000_000,
                   annual_income=0, loan_ratio=0.5, annual_interest_rate=4.0,
                   loan_years=30, owned_homes=1, adjusted_area=False)
    case_id = client.post("/api/cases", json={"title": "소득 미검증", "buyer_profile": profile}).json()["id"]
    path = f"/api/cases/{case_id}"
    candidate = client.post(f"{path}/properties", json={
        "name": "소득 미검증 후보", "category": "apartment", "asking_price": 600_000_000,
    }).json()
    chat = simulate_investment({}, user_id, {"case_id": case_id, "candidate_id": candidate["id"]})
    assert chat.status == "completed"
    assert chat.data["candidate_funding"]["finance_check"]["dsr"] is None
    assert "연소득 확인" in chat.data["warnings"]
    scenario = client.post(f"{path}/funding-scenarios", json={}).json()["rows"][0]["baseline"]
    assert scenario["summary"] == chat.data["candidate_funding"]
    assert "연소득 확인" in scenario["warnings"]
