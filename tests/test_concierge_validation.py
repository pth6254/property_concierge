"""실제 실패한 모델 출력과 다중 턴 조건의 실행 경계를 검증한다."""
import json
from types import SimpleNamespace

import pytest

from backend.graphs.concierge_graph import decide_node, execute_node, explain_node
from tests.test_market_explorer import client


def route(monkeypatch, output, *, previous=None, message="조건을 변경해줘"):
    from backend import model_factory
    raw = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    monkeypatch.setattr(model_factory, "get_chat_llm", lambda **_: SimpleNamespace(
        invoke=lambda _: SimpleNamespace(content=raw)))
    return decide_node({"user_id": 1, "message": message, "previous_criteria": previous or {}})


def test_actual_null_transaction_response_produces_help_without_writer(monkeypatch):
    from backend import model_factory
    state = route(monkeypatch, {"intent": "general", "criteria": {
        "property_type": None, "transaction_type": None, "budget_max_won": None,
        "region_name": None, "region_code": None, "area_min_sqm": None, "purpose": None}})
    monkeypatch.setattr(model_factory, "get_llm", lambda: pytest.fail("사용 안내에 모델 재호출"))
    state = explain_node(execute_node(state))
    assert state["tool_result"].status == "completed"
    assert "AVM" in state["answer"]
    assert state["decision"].criteria.transaction_type is None


@pytest.mark.parametrize("output", ["not json", "[]", "null", {"intent": "unknown"},
    {"intent": "general", "criteria": []}, {"intent": "general", "unexpected": 1}])
def test_invalid_envelope_never_executes_a_guessed_intent(monkeypatch, output):
    state = route(monkeypatch, output, previous={"budget_max_won": 800000000})
    assert state["routing_error"]
    assert state["decision"].intent.value == "general"
    assert state["decision"].criteria.budget_max_won == 800000000
    assert execute_node(state)["tool_result"].status == "error"


@pytest.mark.parametrize("field,value", [("budget_max_won", -1), ("budget_max_won", True),
    ("budget_max_won", 2.5), ("area_min_sqm", -84), ("area_min_sqm", float("inf")),
    ("transaction_type", "invalid"), ("region_code", "abcdefghij"), ("purpose", ""), ("extra", 5)])
def test_bad_field_asks_for_input_without_executing(monkeypatch, field, value):
    state = route(monkeypatch, {"intent": "find_region", "criteria": {field: value}})
    result = execute_node(state)["tool_result"]
    assert result.status == "needs_input"
    assert result.tool == "criteria_validation"
    assert result.missing_fields == ([field] if field != "extra" else ["criteria"])


def test_partial_update_preserves_null_and_normalizes_alias(monkeypatch):
    state = route(monkeypatch, {"intent": "find_region", "criteria": {
        "transaction_type": None, "budget_max_won": 900000000, "purpose": "투자"}},
        previous={"transaction_type": "purchase", "budget_max_won": 800000000, "property_type": "apartment"})
    criteria = state["decision"].criteria
    assert criteria.transaction_type == "purchase" and criteria.property_type == "apartment"
    assert criteria.budget_max_won == 900000000 and criteria.purpose == "investment"


@pytest.mark.parametrize("message,cleared", [("예산 제한 없애줘", True), ("예산 제한 없애지 마", False),
    ("예산 제한 없애줘라고 하면 되나요?", False), ("같은 조건으로", False)])
def test_clear_requires_explicit_user_command(monkeypatch, message, cleared):
    state = route(monkeypatch, {"intent": "find_region", "criteria": {}, "clear_fields": ["budget_max_won"]},
        previous={"budget_max_won": 800000000}, message=message)
    assert state["decision"].criteria.budget_max_won == (None if cleared else 800000000)
    assert bool(state["validation_fields"]) is not cleared


def test_region_name_change_discards_old_code(client, monkeypatch):
    state = route(monkeypatch, {"intent": "find_region", "criteria": {"region_name": "서초구"}},
        previous={"region_name": "강남구", "region_code": "1168000000"})
    assert state["decision"].criteria.region_code == "1165000000"


def test_unknown_and_mismatched_codes_do_not_run_market(client, monkeypatch):
    for criteria in [{"region_code": "9999999999"}, {"region_name": "서초구", "region_code": "1168000000"}]:
        state = route(monkeypatch, {"intent": "find_region", "criteria": criteria})
        assert execute_node(state)["tool_result"].tool == "criteria_validation"


def test_api_followup_merges_saved_criteria_and_clear(client, monkeypatch):
    from backend import model_factory
    outputs = iter([
        {"intent": "find_region", "criteria": {"region_name": "서울", "property_type": "아파트", "budget_max_won": 800000000}},
        {"intent": "find_region", "criteria": {"transaction_type": "매매", "budget_max_won": None}},
        {"intent": "find_region", "criteria": {}, "clear_fields": ["budget_max_won"]},
    ])
    monkeypatch.setattr(model_factory, "get_chat_llm", lambda **kwargs: SimpleNamespace(invoke=lambda _: SimpleNamespace(content=json.dumps(next(outputs)) if kwargs.get("json_mode") else "실거래 자료입니다.")))
    first = client.post('/api/concierge/messages', json={"message": "서울 아파트 8억 이하 추천"}).json()
    assert first["status"] == "needs_input" and first["missing_fields"] == ["transaction_type"]
    second = client.post('/api/concierge/messages', json={"message": "매매로", "conversation_id": first["conversation_id"]}).json()
    assert second["status"] == "completed" and second["criteria"]["budget_max_won"] == 800000000
    third = client.post('/api/concierge/messages', json={"message": "예산 제한 없애줘", "conversation_id": first["conversation_id"]}).json()
    assert third["status"] == "completed" and third["criteria"]["budget_max_won"] is None


def test_lease_does_not_silently_query_purchase_data(client, monkeypatch):
    state = route(monkeypatch, {"intent": "find_region", "criteria": {
        "region_name": "서울", "property_type": "apartment", "transaction_type": "전세"}})
    assert execute_node(state)["tool_result"].status == "not_available"
