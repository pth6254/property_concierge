"""다음 행동 안내가 누락·위험을 감추거나 검토 완료를 과장하지 않는지 확인한다."""
import pytest

from backend.services.candidate_next_actions import candidate_next_actions
from backend.services.case_comparison_service import compare_case_candidates


def reviewed_candidate():
    return {
        "id": 1, "name": "후보", "status": "reviewing", "asking_price": 900_000_000,
        "analyses": [
            {"analysis_type": "appraisal", "status": "completed", "summary": {"estimated_value": 900_000_000, "confidence": 0.8}},
            {"analysis_type": "simulation", "status": "completed", "summary": {
                "purchase_price": 900_000_000, "loan_amount": 0, "required_cash": 920_000_000,
                "monthly_payment": 0, "cash_available": 920_000_000, "cash_shortfall": 0,
            }},
            {"analysis_type": "rights", "status": "completed", "summary": {"risk_grade": "safe"}},
        ],
        "checklist": [{"id": 1, "category": "site", "title": "현장 상태 확인", "status": "done"}],
    }


def test_missing_information_and_analysis_are_actionable_without_duplicates():
    candidate = {"checklist": [{"id": 1, "category": "price", "title": "적정가격 확인", "status": "todo"}]}
    actions = candidate_next_actions({}, candidate)
    assert [a["target"] for a in actions] == ["price", "appraisal", "simulation", "rights"]


@pytest.mark.parametrize("status, expected", [("stale", "갱신"), ("failed", "재시도"), ("pending", "진행 확인")])
def test_incomplete_analysis_blocks_readiness_even_with_completed_checklist(status, expected):
    candidate = reviewed_candidate()
    candidate["analyses"][0]["status"] = status
    actions = candidate_next_actions({}, candidate)
    assert expected in actions[0]["title"]
    row = compare_case_candidates({"id": 1, "title": "케이스", "properties": [candidate]})["rows"][0]
    assert not row["decision_ready"]
    assert row["missing"]


def test_risks_precede_missing_inputs_and_remain_when_stale():
    candidate = reviewed_candidate()
    candidate["asking_price"] = None
    candidate["analyses"][2].update(status="stale", summary={"risk_grade": "danger"})
    actions = candidate_next_actions({}, candidate)
    assert actions[0]["code"] == "rights_risk"
    assert {a["code"] for a in actions} == {"rights_risk", "rights", "asking_price"}


def test_manual_review_is_required_and_rejected_candidates_are_quiet():
    candidate = reviewed_candidate()
    candidate["checklist"][0]["status"] = "todo"
    case = {"id": 1, "title": "케이스", "properties": [candidate]}
    assert not compare_case_candidates(case)["rows"][0]["decision_ready"]
    assert candidate_next_actions(case, candidate)[0]["checklist_id"] == 1
    candidate["status"] = "rejected"
    assert candidate_next_actions(case, candidate) == []
    assert not compare_case_candidates(case)["rows"][0]["decision_ready"]


def test_resolved_candidate_has_no_outstanding_action():
    candidate = reviewed_candidate()
    assert candidate_next_actions({}, candidate) == []
    assert compare_case_candidates({"id": 1, "title": "케이스", "properties": [candidate]})["rows"][0]["decision_ready"]


def test_changed_price_requires_funding_review_and_budget_warning():
    candidate = reviewed_candidate()
    candidate["asking_price"] = 1_000_000_000
    codes = {a["code"] for a in candidate_next_actions({"budget_max": 950_000_000}, candidate)}
    assert codes == {"budget", "price_gap", "simulation_price"}


def test_unknown_rights_grade_requires_confirmation():
    candidate = reviewed_candidate()
    candidate["analyses"][2]["summary"] = {}
    assert candidate_next_actions({}, candidate)[0]["code"] == "rights_risk"


def test_manual_candidate_needs_source_and_unknown_avm_confidence_blocks_price_gap():
    candidate = reviewed_candidate()
    candidate.update(source="manual", source_listing_id=None)
    candidate["analyses"][0]["summary"].pop("confidence")
    candidate["asking_price"] = 1_000_000_000
    case = {"id": 1, "title": "케이스", "properties": [candidate]}
    row = compare_case_candidates(case)["rows"][0]
    codes = {action["code"] for action in candidate_next_actions(case, candidate)}
    assert {"source_unverified", "appraisal_confidence", "simulation_price"} <= codes
    assert "price_gap" not in codes
    assert row["price_gap"] is None
    assert not row["decision_ready"]


def test_sample_recommendation_never_becomes_decision_ready():
    candidate = reviewed_candidate()
    candidate.update(source="recommendation", source_listing_id=None)
    row = compare_case_candidates({"id": 1, "title": "케이스", "properties": [candidate]})["rows"][0]
    assert "demo_listing" in {action["code"] for action in candidate_next_actions({}, candidate)}
    assert not row["decision_ready"]
