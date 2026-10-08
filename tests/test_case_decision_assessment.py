"""의사결정 근거 부족·만료·변경·위험 신호를 매수 확신으로 표시하지 않는 회귀 검증."""
from copy import deepcopy
from datetime import datetime

import pytest

from backend.services.case_decision_assessment import assess_case_decision
from backend.services.case_comparison_service import compare_case_candidates

NOW = datetime(2026, 10, 1, 12)


@pytest.fixture()
def case():
    def analysis(kind, summary):
        return {"analysis_type": kind, "status": "completed", "summary": summary,
                "analyzed_at": "2026-10-01 10:00:00", "expires_at": "2026-10-03 10:00:00",
                "reference_id": 123 if kind == "appraisal" else None}

    return {"id": 1, "budget_max": 650_000_000, "target_regions": [], "regions": [],
        "buyer_profile": {"property_types": ["apartment"], "min_area_sqm": 70, "max_area_sqm": 90},
        "selected_property_id": None, "updated": "2026-10-01 09:00:00", "properties": [{
            "id": 2, "name": "검증 후보", "category": "아파트", "address": "검증용 주소",
            "asking_price": 600_000_000, "area_sqm": 84, "legal_region_code": "1165010700",
            "source": "manual", "source_listing_id": 3, "status": "reviewing", "review_progress": 100,
            "source_status": {"status": "current", "current": {"confirmed_at": "2026-10-01 08:00:00"}},
            "checklist": [{"id": 4, "category": "site", "title": "현장 확인", "status": "done"}],
            "analyses": [analysis("appraisal", {"estimated_value": 600_000_000,
                "confidence": 0.8, "comparable_count": 6, "match_level": "동일단지"}),
                analysis("simulation", {"purchase_price": 600_000_000, "home_count_basis": "after_purchase",
                    "required_cash": 610_000_000, "monthly_payment": 0, "cash_available": 650_000_000,
                    "cash_shortfall": 0, "loan_amount": 0, "finance_check": {},
                    "inputs": {"owned_homes": 1, "loan_ratio": 0, "annual_interest_rate": 4, "loan_years": 30}}),
                analysis("rights", {"risk_grade": "safe", "risk_label": "위험 신호 미검출",
                    "registry_supplied": True, "building_supplied": True,
                    "registry_parsed": True, "building_parsed": True})],
            "updated": "2026-10-01 11:00:00",
        }]}


def result(case):
    return assess_case_decision(case, now=NOW).candidates[0]


def axis(case, key):
    return next(item for item in result(case).axes if item.key == key)


def summary(case, kind):
    return next(item["summary"] for item in case["properties"][0]["analyses"] if item["analysis_type"] == kind)


def test_five_axes_confirmed_are_not_an_automatic_purchase_decision(case):
    before = deepcopy(case)
    assessment = result(case)
    assert [item.key for item in assessment.axes] == ["fit", "price", "funding", "risk", "execution"]
    assert all(item.status == "confirmed" for item in assessment.axes)
    assert assessment.review_ready and assessment.next_actions == []
    assert assessment.metrics.required_cash == 610_000_000
    assert assessment.metrics.monthly_payment == 0
    assert assessment.metrics.price_gap == 0
    assert case == before and case["selected_property_id"] is None
    price_evidence = axis(case, "price").evidence
    assert next(item for item in price_evidence if item.key == "estimated_value").reference_url == "/report/123"
    assert "미검출" in axis(case, "risk").headline
    assert "보장하지" in assess_case_decision(case, now=NOW).boundary
    comparison = compare_case_candidates({**case, "title": "검증 케이스"}, now=NOW)["rows"][0]
    assert comparison["decision_ready"] == assessment.review_ready
    assert comparison["price_gap"] == assessment.metrics.price_gap
    assert comparison["funding"]["required_cash"] == assessment.metrics.required_cash


def test_missing_analyses_do_not_become_zero_or_safe(case):
    case["properties"][0]["analyses"] = []
    assessment = result(case)
    assert not assessment.review_ready
    assert all(item.status == "unknown" for item in assessment.axes[1:4])
    assert assessment.metrics.required_cash is None
    assert assessment.metrics.monthly_payment is None
    assert assessment.metrics.price_gap is None
    assert {"appraisal", "simulation", "rights"}.issubset({item.target for item in assessment.next_actions})


@pytest.mark.parametrize("kind,key", [("appraisal", "price"), ("simulation", "funding"), ("rights", "risk")])
@pytest.mark.parametrize("status,expected", [("stale", "stale"), ("failed", "error"), ("pending", "pending")])
def test_incomplete_analysis_statuses_are_visible(case, kind, key, status, expected):
    next(item for item in case["properties"][0]["analyses"] if item["analysis_type"] == kind)["status"] = status
    assert axis(case, key).status == expected
    assert not result(case).review_ready
    if kind == "appraisal":
        assert result(case).metrics.price_gap is None
    if kind == "simulation":
        assert result(case).metrics.required_cash is None


@pytest.mark.parametrize("timestamp", [None, "", "invalid", "2026-09-01 10:00:00", "2026-10-02 10:00:00", "2026-10-01T10:00:00Z"])
def test_old_or_undated_price_analysis_is_not_current(case, timestamp):
    analysis = case["properties"][0]["analyses"][0]
    analysis.update(analyzed_at=timestamp, expires_at=None)
    assert axis(case, "price").status == "stale"
    assert result(case).metrics.price_gap is None
    assert any(item.code == "appraisal" for item in result(case).next_actions)


@pytest.mark.parametrize("field,value", [("confidence", None), ("confidence", 0.49), ("confidence", 1.1),
    ("confidence", True), ("comparable_count", 0), ("comparable_count", None), ("estimated_value", 0),
    ("estimated_value", True), ("estimated_value", float("nan"))])
def test_price_evidence_requirements(case, field, value):
    summary(case, "appraisal")[field] = value
    assert axis(case, "price").status == "unknown"
    assert result(case).metrics.price_gap is None
    assert not result(case).review_ready
    assert not any(item.code == "price_gap" for item in result(case).next_actions)


@pytest.mark.parametrize("status", ["changed", "needs_confirmation", "missing"])
def test_source_change_disables_previous_comparisons(case, status):
    case["properties"][0]["source_status"]["status"] = status
    assessment = result(case)
    assert all(item.status == "stale" for item in assessment.axes[:4])
    assert assessment.metrics.price_gap is None and assessment.metrics.required_cash is None
    assert not assessment.review_ready
    assert any(item.code == "source_listing" for item in assessment.next_actions)


def test_price_difference_is_a_review_signal(case):
    summary(case, "appraisal")["estimated_value"] = 500_000_000
    assert axis(case, "price").status == "warning"
    assert result(case).metrics.price_gap_ratio == 20
    assert not result(case).review_ready


def test_legacy_home_count_and_changed_price_need_recalculation(case):
    del summary(case, "simulation")["home_count_basis"]
    assert axis(case, "funding").status == "unknown"
    assert result(case).metrics.required_cash is None
    summary(case, "simulation")["home_count_basis"] = "after_purchase"
    summary(case, "simulation")["purchase_price"] = 610_000_000
    assert axis(case, "funding").status == "stale"
    assert result(case).metrics.monthly_payment is None
    row = compare_case_candidates({**case, "title": "검증 케이스"}, now=NOW)["rows"][0]
    assert row["funding"] is None and not row["decision_ready"]


def test_funding_shortfall_is_warning_with_actual_calculation(case):
    summary(case, "simulation").update(cash_available=600_000_000, cash_shortfall=10_000_000)
    assert axis(case, "funding").status == "warning"
    assert result(case).metrics.cash_shortfall == 10_000_000
    assert any(item.code == "funding_shortfall" for item in result(case).next_actions)


@pytest.mark.parametrize("field", ["required_cash", "monthly_payment", "loan_amount", "cash_available", "cash_shortfall"])
def test_incomplete_funding_outputs_are_not_confirmed(case, field):
    summary(case, "simulation").pop(field)
    assert axis(case, "funding").status == "unknown"
    assert result(case).metrics.required_cash is None


def test_funding_input_home_count_must_be_recorded(case):
    summary(case, "simulation")["inputs"].pop("owned_homes")
    assert axis(case, "funding").status == "unknown"


def test_borrowing_without_income_and_monthly_limit_is_unknown(case):
    summary(case, "simulation").update(loan_amount=300_000_000, monthly_payment=1_500_000)
    assert axis(case, "funding").status == "unknown"
    assert {"funding_income", "funding_payment_input"}.issubset({action.code for action in result(case).next_actions})


@pytest.mark.parametrize("key", ["registry_parsed", "building_parsed"])
def test_pdf_upload_without_parsing_is_not_clear_risk(case, key):
    summary(case, "rights")[key] = False
    assert axis(case, "risk").status == "unknown"
    assert "미검출" not in axis(case, "risk").headline
    assert not result(case).review_ready


def test_expired_risk_warning_is_preserved(case):
    rights = case["properties"][0]["analyses"][2]
    rights["status"] = "stale"
    rights["summary"].update(risk_grade="danger", reasons=["가압류 확인 필요"])
    risk = axis(case, "risk")
    assert risk.status == "warning"
    assert any(item.value == "가압류 확인 필요" and not item.usable for item in risk.evidence)


def test_unverified_listing_is_not_clear_risk(case):
    case["properties"][0].update(source_listing_id=None, source_status=None)
    assert axis(case, "risk").status == "unknown"
    assert not result(case).review_ready


def test_listing_confirmation_without_timestamp_is_unknown(case):
    case["properties"][0]["source_status"]["current"] = {}
    assert axis(case, "risk").status == "unknown"


def test_fit_uses_only_existing_evidence(case):
    case["buyer_profile"]["min_build_year"] = 2010
    assert axis(case, "fit").status == "unknown"
    assert "후보 준공연도" in axis(case, "fit").missing
    assert any(item.target == "profile" for item in result(case).next_actions)
    assert "통근" in axis(case, "fit").limitations[0]
    case["properties"][0]["area_sqm"] = 50
    assert axis(case, "fit").status == "warning"


def test_generic_category_cannot_establish_preferred_subtype(case):
    case["properties"][0]["category"] = "주거용"
    assert axis(case, "fit").status == "unknown"
    assert "후보의 세부 물건 유형" in axis(case, "fit").missing


@pytest.mark.parametrize("code,expected", [("1100000000", "confirmed"), ("1165000000", "confirmed"),
    ("1165010700", "confirmed"), ("1165010800", "warning")])
def test_region_scope_uses_legal_codes(case, code, expected):
    case["regions"] = [{"region_code": code, "region_name": "검증 지역"}]
    assert axis(case, "fit").status == expected


def test_region_names_without_codes_cannot_be_guessed(case):
    case["target_regions"] = ["서울"]
    assert axis(case, "fit").status == "unknown"


def test_rejected_candidate_has_no_next_actions(case):
    case["properties"][0]["status"] = "rejected"
    assessment = result(case)
    assert not assessment.review_ready and not assessment.next_actions
    assert assessment.axes[-1].status == "unknown"


def jeonse(ratio, sufficient=True):
    return {"policy_version": "PC-AVM-1.0-runtime-1", "result_kind": "market_reference", "comparison_eligible": True,
            "subject": {}, "jeonse_context": {"ratio_pct": ratio, "sufficient": sufficient, "lease_count": 5 if sufficient else 1,
                                              "sale_count": 6, "window_months": 6, "leases": []}}


def test_high_jeonse_ratio_warns_but_low_or_thin_ratio_never_clears_risk(case):
    summary(case, "appraisal")["valuation"] = jeonse(82.4)
    risk = axis(case, "risk")
    assert risk.status == "warning" and "보증금" in risk.headline
    assert any("82.4%" in text for text in risk.missing)
    assert not result(case).review_ready
    assert any(item.key == "jeonse_ratio" and item.usable for item in risk.evidence)

    summary(case, "appraisal")["valuation"] = jeonse(45.0)
    low = axis(case, "risk")
    assert low.status == "confirmed" and "미검출" in low.headline  # 낮은 값은 문서 판단을 바꾸지 않는다
    assert any(item.key == "jeonse_ratio" and item.usable for item in low.evidence)

    summary(case, "appraisal")["valuation"] = jeonse(90.0, sufficient=False)
    thin = axis(case, "risk")
    assert thin.status == "confirmed"  # 표본 부족 비율은 경고에도 쓰지 않는다
    assert not next(item for item in thin.evidence if item.key == "jeonse_ratio").usable


def test_stale_or_changed_source_does_not_trigger_jeonse_warning(case):
    summary(case, "appraisal")["valuation"] = jeonse(95.0)
    case["properties"][0]["source_status"] = {"status": "changed"}
    risk = axis(case, "risk")
    assert not next(item for item in risk.evidence if item.key == "jeonse_ratio").usable
    assert not any("전세가율" in text for text in risk.missing)


def test_assumed_deposit_share_warns_and_is_shown_on_funding(case):
    sim = summary(case, "simulation")
    sim.update(assumed_deposit=500_000_000, deposit_return_obligation=500_000_000)
    risk = axis(case, "risk")
    assert risk.status == "warning" and any("83.3%" in text for text in risk.missing)
    funding = axis(case, "funding")
    assert next(item for item in funding.evidence if item.key == "assumed_deposit").value == 500_000_000
    assert any("반환" in text for text in funding.limitations)
    sim["assumed_deposit"] = 200_000_000
    assert axis(case, "risk").status == "confirmed"
