"""매수 조건의 재계산과 대화 기본값이 후보 분석을 오염시키지 않는지 검증한다."""
from schemas.purchase_case import BuyerProfile, PurchaseCaseCreate
from backend.services.case_funding_scenarios import compare_funding_scenarios
from backend.services.case_comparison_service import compare_case_candidates
from backend.concierge.decision_tools import simulate_investment
from backend.services.concierge_service import _save_explicit_case_conditions


def _case():
    return {"id": 12, "title": "매수 검토", "buyer_profile": BuyerProfile(
        cash_available=400_000_000, emergency_reserve=50_000_000,
        monthly_payment_limit=2_000_000, annual_income=100_000_000,
        loan_ratio=0.5, annual_interest_rate=4.0, loan_years=30,
        owned_homes=1, adjusted_area=False,
    ).model_dump(), "properties": [
        {"id": 31, "name": "후보 A", "category": "아파트", "asking_price": 700_000_000,
         "status": "reviewing", "analyses": []},
        {"id": 32, "name": "후보 B", "category": "apartment", "asking_price": 800_000_000,
         "status": "reviewing", "analyses": []},
    ]}


def test_profile_schema_resolves_and_validates_cash():
    assert PurchaseCaseCreate(title="새 케이스").buyer_profile.priority == "cash"
    assert BuyerProfile(cash_available=10, emergency_reserve=0).cash_available == 10


def test_scenario_calculates_all_candidates_without_changing_case():
    case = _case()
    result = compare_funding_scenarios(case, price_delta_won=20_000_000,
                                       interest_delta_pct=1.0, reserve_delta_won=10_000_000)
    assert len(result["rows"]) == 2
    assert result["persisted"] is False
    for row in result["rows"]:
        assert row["baseline"]["status"] == row["scenario"]["status"] == "calculated"
        assert row["scenario"]["summary"]["purchase_price"] == row["asking_price"] + 20_000_000
        assert row["scenario"]["summary"]["cash_available"] == 340_000_000
        assert row["scenario"]["summary"]["monthly_payment"] > row["baseline"]["summary"]["monthly_payment"]
    assert case["properties"][0]["analyses"] == []
    assert case["properties"][0]["asking_price"] == 700_000_000


def test_stage_advances_from_comparison_to_detailed():
    case = _case()
    rows = compare_case_candidates(case)["rows"]
    assert all(row["review_stage"] == "comparison" for row in rows)
    case["properties"][0]["analyses"] = [
        {"analysis_type": kind, "status": "completed", "summary": {}}
        for kind in ("appraisal", "simulation", "rights")
    ]
    assert compare_case_candidates(case)["rows"][0]["review_stage"] == "detailed"


def test_chat_funding_uses_saved_profile(monkeypatch):
    case = _case()
    monkeypatch.setattr("api.case_db.get_case", lambda case_id, user_id: case)
    captured = {}

    def fake_execute(request, user):
        captured["request"] = request
        return {"candidate_funding": {"required_cash": 360_000_000,
                                      "cash_shortfall": 10_000_000, "monthly_payment": 1_700_000}}

    monkeypatch.setattr("api.routes.simulation.execute_simulation", fake_execute)
    result = simulate_investment({}, 7, {"case_id": 12, "candidate_id": 31})
    assert result.status == "completed"
    assert captured["request"].cash_available == 350_000_000
    assert captured["request"].loan_ratio == 0.5


def test_chat_saves_only_explicit_validated_case_changes(monkeypatch):
    case = _case()
    writes = []
    monkeypatch.setattr("api.case_db.update_case", lambda case_id, user_id, data: writes.append(data) or case)
    result = _save_explicit_case_conditions(
        case, 7, "케이스 조건 보유 현금 5억원으로 변경", {},
        {"cash_available": 500_000_000}, {}, {},
    )
    assert result["status"] == "completed"
    assert writes[0]["buyer_profile"]["cash_available"] == 500_000_000
    assert writes[0]["buyer_profile"]["emergency_reserve"] == 50_000_000
    assert _save_explicit_case_conditions(
        case, 7, "현금이 3억원이면?", {}, {"cash_available": 300_000_000}, {}, {},
    ) is None
    assert len(writes) == 1


def test_chat_rejects_budget_below_minimum_and_reserve_above_cash(monkeypatch):
    case = _case()
    case["budget_min"] = 600_000_000
    monkeypatch.setattr("api.case_db.update_case", lambda *_: (_ for _ in ()).throw(AssertionError("must not save")))
    too_low = _save_explicit_case_conditions(
        case, 7, "케이스 조건 예산 5억원으로 변경", {}, {},
        {"budget_max_won": 700_000_000}, {"budget_max_won": 500_000_000},
    )
    assert too_low["status"] == "needs_input"
    no_cash = _save_explicit_case_conditions(
        case, 7, "케이스 조건 보유 현금 1만원으로 변경", {},
        {"cash_available": 10_000}, {}, {},
    )
    assert no_cash["status"] == "needs_input"
