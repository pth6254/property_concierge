"""후속 대화의 금융 조건·소유권 경계와 실제 계산 저장을 검증한다."""
import json
from types import SimpleNamespace

import pytest

from tests.test_market_explorer import client
from backend.concierge.decision_tools import merge_funding


@pytest.mark.parametrize("field,value", [("cash_available", True), ("cash_available", -1),
    ("loan_ratio", 50), ("annual_interest_rate", float("inf")), ("loan_years", "30"),
    ("adjusted_area", "false"), ("purchase_price", 1), ("annual_income", -1)])
def test_invalid_funding_does_not_replace_previous(field, value):
    previous = {"cash_available": 300000000}
    values, invalid = merge_funding({field: value}, previous)
    assert values == previous and invalid == [field]


def test_model_financial_fields_in_criteria_are_validated(monkeypatch):
    from backend.graphs.concierge_graph import decide_node, execute_node
    router(monkeypatch, [{"intent": "simulate", "criteria": {"cash_available": 300000000, "loan_ratio": 50}}], [])
    state = decide_node({"user_id": 1, "message": "현금 3억, 대출 50%", "previous_criteria": {}})
    assert state["funding"] == {"cash_available": 300000000}
    assert execute_node(state)["tool_result"].tool == "funding_validation"


def test_conflicting_financial_locations_do_not_calculate(monkeypatch):
    from backend.graphs.concierge_graph import decide_node, execute_node
    router(monkeypatch, [{"intent": "simulate", "criteria": {"cash_available": 100},
                         "funding": {"cash_available": 200}}], [])
    state = decide_node({"user_id": 1, "message": "현금 100원", "previous_criteria": {}})
    assert execute_node(state)["tool_result"].status == "error"


@pytest.mark.parametrize("model_id,accepted", [(2, True), (999, False)])
def test_model_cannot_change_selected_candidate(monkeypatch, model_id, accepted):
    from backend.graphs.concierge_graph import decide_node
    router(monkeypatch, [{"intent": "simulate", "criteria": {"candidate_id": model_id}}], [])
    state = decide_node({"user_id": 1, "message": "자금 조건 확인", "candidate_context": {"case_id": 1, "candidate_id": 2}})
    assert (not state.get("routing_error")) is accepted


def test_foreign_case_and_conversation_are_not_reused(client):
    case_id, candidates = setup_candidates(client)
    first = client.post("/api/concierge/messages", json={"case_id": case_id,
        "candidate_id": candidates[0]["id"], "message": "자금 분석해줘"}).json()
    client.cookies.clear()
    assert client.post("/api/auth/register", json={"email": "other-concierge@example.com",
        "password": "another-test-password", "name": "다른 사용자"}).status_code == 201
    assert client.post("/api/concierge/messages", json={"case_id": case_id,
        "message": "후보 비교해줘"}).status_code == 404
    other = client.post("/api/concierge/messages", json={"conversation_id": first["conversation_id"],
        "message": "자금 분석해줘"}).json()
    assert other["missing_fields"] == ["candidate"]


def setup_candidates(client):
    case = client.post("/api/cases", json={"title": "대화 자금 검토"}).json()
    candidates = []
    for name, price in [("후보 A", 600000000), ("후보 B", 700000000)]:
        response = client.post(f"/api/cases/{case['id']}/properties", json={
            "name": name, "category": "apartment", "asking_price": price})
        assert response.status_code == 201
        candidates.append(response.json())
    return case["id"], candidates


def router(monkeypatch, outputs, prompts):
    from backend import model_factory
    answers = iter(outputs)
    def invoke(messages):
        prompts.append(messages)
        return SimpleNamespace(content=json.dumps(next(answers)))
    monkeypatch.setattr(model_factory, "get_chat_llm", lambda **_: SimpleNamespace(invoke=invoke))
    monkeypatch.setattr(model_factory, "get_llm", lambda: pytest.fail("계산 결과를 LLM으로 재작성하면 안 됨"))


def test_followup_real_calculation_persistence_compare_and_candidate_switch(client, monkeypatch):
    case_id, candidates = setup_candidates(client)
    prompts = []
    router(monkeypatch, [
        {"intent": "simulate", "funding": {"cash_available": 300000000, "loan_ratio": .5}},
        {"intent": "simulate", "funding": {"annual_interest_rate": 4., "loan_years": 30,
         "repayment_type": "equal_payment", "owned_homes": 1, "adjusted_area": False,
         "existing_loan_annual_payment": 0, "annual_income": 100000000, "monthly_payment_limit": 2000000}},
        {"intent": "simulate", "funding": {"annual_interest_rate": 5.}},
    ], prompts)
    first = client.post("/api/concierge/messages", json={"case_id": case_id, "candidate_id": candidates[0]["id"],
        "message": "현금 3억, 대출 50%로 자금 계산해줘"}).json()
    assert first["status"] == "needs_input" and "annual_interest_rate" in first["missing_fields"]
    assert "cash_available" not in first["missing_fields"]
    conversation = first["conversation_id"]
    # 두 번째 요청은 ID를 다시 보내지 않는다. 소유한 후보와 첫 번째 입력을 기억해야 한다.
    second = client.post("/api/concierge/messages", json={"conversation_id": conversation,
        "message": "금리 4%, 30년 원리금균등, 취득 후 1주택 비조정지역, 기존 대출 없음, 연소득 1억, 월 한도 200만원"}).json()
    assert second["status"] == "completed", second
    funding = second["data"]["candidate_funding"]
    assert funding["inputs"]["cash_available"] == 300000000
    assert funding["purchase_price"] == 600000000
    assert funding["cash_shortfall"] == funding["acquisition_cost"]
    monthly = funding["monthly_payment"]
    assert 1400000 < monthly < 1500000
    assert "현금 3억" in prompts[1][1][1] and "annual_interest_rate" in prompts[1][1][1]
    changed = client.post("/api/concierge/messages", json={"conversation_id": conversation, "message": "그럼 금리만 5%로"}).json()
    assert changed["data"]["candidate_funding"]["monthly_payment"] > monthly
    comparison = client.post("/api/concierge/messages", json={"conversation_id": conversation, "message": "그럼 후보 비교해줘"}).json()
    rows = comparison["data"]["comparison"]["rows"]
    assert len(rows) == 2 and rows[0]["funding"]["annual_interest_rate"] == 5
    assert rows[1]["funding"] is None and not rows[1]["decision_ready"]
    switched = client.post("/api/concierge/messages", json={"conversation_id": conversation,
        "case_id": case_id, "candidate_id": candidates[1]["id"], "message": "자금 분석해줘"}).json()
    assert "cash_available" in switched["missing_fields"]
    cleared = client.post("/api/concierge/messages", json={"conversation_id": conversation,
        "clear_context": True, "message": "자금 분석해줘"}).json()
    assert cleared["missing_fields"] == ["candidate"]


def test_case_only_compare_and_deselection(client):
    case_id, candidates = setup_candidates(client)
    first = client.post("/api/concierge/messages", json={"case_id": case_id,
        "candidate_id": candidates[0]["id"], "message": "자금 분석해줘"}).json()
    deselected = client.post("/api/concierge/messages", json={"case_id": case_id,
        "conversation_id": first["conversation_id"], "message": "자금 분석해줘"}).json()
    assert deselected["missing_fields"] == ["candidate"]
    compared = client.post("/api/concierge/messages", json={"case_id": case_id, "message": "후보 비교해줘"}).json()
    assert len(compared["data"]["comparison"]["rows"]) == 2


def test_retained_context_rechecks_deleted_candidate(client):
    case_id, candidates = setup_candidates(client)
    first = client.post("/api/concierge/messages", json={"case_id": case_id,
        "candidate_id": candidates[0]["id"], "message": "자금 분석해줘"}).json()
    assert client.delete(f"/api/cases/{case_id}/properties/{candidates[0]['id']}").status_code in {200, 204}
    assert client.post("/api/concierge/messages", json={"conversation_id": first["conversation_id"],
        "message": "자금 분석해줘"}).status_code == 404
    assert client.post("/api/concierge/messages", json={"case_id": case_id + 9999,
        "message": "후보 비교해줘"}).status_code == 404
