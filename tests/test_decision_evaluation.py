"""핵심 의사결정 평가가 위험 누락·미추정·미래 데이터 누출을 잡는지 확인한다."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from evaluation.cli import DATASETS, load_dataset, main
from evaluation.decision_schema import AvmCase, DecisionCase, IntentCase
from evaluation.decision_suites import avm, decision, intent


@pytest.mark.parametrize("suite", ["decision", "avm", "intent"])
def test_core_datasets_are_valid(suite):
    dataset, cases = load_dataset(DATASETS / f"{suite}.json")
    assert dataset.suite == suite and cases


def test_all_decision_scenarios_use_fixed_time_and_pass_their_expectations():
    _, cases = load_dataset(DATASETS / "decision.json")
    for case in cases:
        result = decision(case)
        assert result["status"] == "pass", (case.id, [c for c in result["checks"] if not c["passed"]])
        assert len(result["details"]["steps"]) == len(case.steps)


def test_decision_evaluator_detects_dangerous_ready_regression(monkeypatch):
    from backend.services import case_comparison_service
    original = case_comparison_service.compare_case_candidates
    def broken(*args, **kwargs):
        result = original(*args, **kwargs)
        for row in result["rows"]:
            row["decision_ready"] = True
        return result
    monkeypatch.setattr(case_comparison_service, "compare_case_candidates", broken)
    _, cases = load_dataset(DATASETS / "decision.json")
    assert decision(next(c for c in cases if c.id == "cheap-but-risky"))["status"] == "fail"


def test_decision_evaluator_detects_missing_risk_action(monkeypatch):
    from backend.services import candidate_next_actions
    monkeypatch.setattr(candidate_next_actions, "candidate_next_actions", lambda *_: [])
    _, cases = load_dataset(DATASETS / "decision.json")
    result = decision(next(c for c in cases if c.id == "cheap-but-risky"))
    assert result["status"] == "fail"
    assert any(not c["passed"] and "first_action" in c["name"] for c in result["checks"])


def test_snapshot_validation_rejects_wrong_candidate_and_duplicate_analysis():
    _, cases = load_dataset(DATASETS / "decision.json")
    payload = cases[0].model_dump(mode="json")
    payload["steps"][0]["expected"]["required_actions"] = {"999": ["rights"]}
    with pytest.raises(ValidationError):
        DecisionCase.model_validate(payload)
    payload = cases[0].model_dump(mode="json")
    candidate = payload["steps"][-1]["candidates"][0]
    candidate["analyses"].append(deepcopy(candidate["analyses"][0]))
    with pytest.raises(ValidationError):
        DecisionCase.model_validate(payload)


def test_backtest_does_not_learn_from_target_month_and_counts_unestimated():
    from backend.tools.backtest_avm import evaluate_months
    def deal(price, area=84):
        return {"price": price, "area_sqm": area, "per_sqm": price / area, "apt_name": "A", "dong": "D"}
    result = evaluate_months({"202601": [deal(10000)], "202602": [deal(10000)],
                             "202603": [deal(1000000), deal(10000, 200)]}, region_name="가상 지역",
                             target_months=1, window=6, time_factor=lambda *_: 1)
    assert result["eligible"] == 2 and result["unestimated"] == 1 and result["coverage"] == 0.5
    assert result["cases"][0]["predicted_manwon"] == 10000
    assert result["cases"][0]["ape"] == 0.99
    assert result["cases"][0]["prior_months"] == ["202601", "202602"]


def test_synthetic_avm_is_labeled_and_cannot_pass_without_comparables():
    _, cases = load_dataset(DATASETS / "avm.json")
    result = avm(cases[0], live=False)
    assert result["status"] == "pass"
    assert result["details"]["source"] == "synthetic_fixture"
    payload = cases[0].model_dump(mode="json")
    payload["months"]["202603"][0]["area_sqm"] = 200
    result = avm(AvmCase.model_validate(payload), live=False)
    assert result["status"] == "fail"
    assert result["metrics"]["mape"] is None
    assert result["metrics"]["coverage"] == 0


def test_cancelled_transactions_are_neither_comparables_nor_targets():
    from backend.tools.backtest_avm import evaluate_months
    deal = {"price": 10000, "per_sqm": 100, "area_sqm": 100, "apt_name": "A", "dong": "D"}
    cancelled = dict(deal, price=1000000, per_sqm=10000, is_cancelled=True)
    result = evaluate_months({"202601": [deal, cancelled], "202602": [deal, cancelled]},
                            region_name="가상", target_months=1, window=6, time_factor=lambda *_: 1)
    assert result["eligible"] == 1 and result["cancelled"] == 1 and result["coverage"] == 1
    assert result["cases"][0]["predicted_manwon"] == 10000


def test_live_avm_empty_store_fails_without_updating_calibration(monkeypatch):
    from backend.tools import backtest_avm
    monkeypatch.setattr(backtest_avm.transaction_store, "list_ingested_months", lambda *_: [])
    _, cases = load_dataset(DATASETS / "avm.json")
    result = avm(cases[0], live=True)
    assert result["status"] == "fail" and result["details"]["source"] == "stored_transactions"


def test_intent_uses_actual_previous_criteria_and_reports_unconnected_tools(monkeypatch):
    from backend.graphs import concierge_graph
    from schemas.concierge import ConciergeDecision
    inputs = []
    def decide(state):
        inputs.append(deepcopy(state))
        return {"decision": ConciergeDecision.model_validate({"intent": "appraise", "criteria": {"budget_max_won": 800000000}})}
    monkeypatch.setattr(concierge_graph, "decide_node", decide)
    case = IntentCase.model_validate({"id": "test", "turns": [
        {"message": "시세 추정", "expected_intent": "appraise", "expected_criteria": {"budget_max_won": 800000000}},
        {"message": "같은 조건", "expected_intent": "appraise", "expected_criteria": {"budget_max_won": 800000000}},
    ]})
    result = intent(case)
    assert result["status"] == "pass"
    assert inputs[1]["previous_criteria"]["budget_max_won"] == 800000000
    assert result["metrics"]["unconnected_tools"] == 0


def test_intent_model_failure_is_error_not_a_successful_fallback(monkeypatch):
    from backend import model_factory
    from backend.graphs.concierge_graph import decide_node
    def unavailable():
        raise RuntimeError("down")
    monkeypatch.setattr(model_factory, "get_chat_llm", lambda **_: unavailable())
    state = decide_node({"message": "지역 추천", "previous_criteria": {"budget_max_won": 1000000000}})
    assert state["routing_error"] == "RuntimeError"
    case = IntentCase.model_validate({"id": "down", "turns": [{"message": "지역 추천", "expected_intent": "find_region"}]})
    assert intent(case)["status"] == "error"


def test_intent_requires_live_mode():
    with pytest.raises(SystemExit) as exc:
        main(["run", "--suite", "intent"])
    assert exc.value.code == 2
