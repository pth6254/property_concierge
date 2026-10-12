"""아파트 혼합 AVM(R-APT): 근거 단계 판정, 저장 산출물로 하는 운영 추정, 정책 결과 종류.

가격 정확도는 시간 분할 평가(evaluation avm-segment --segment apartment)로 따로 확인한다. 여기서는 규칙·계약을 검사한다.
"""
from datetime import date, timedelta

import pytest

from backend.valuation import apartment_avm
from backend.valuation import models as price_models
from backend.valuation.segments import apartment as apt
from backend.valuation.segments.row_house import MarketIndex
from tests.test_valuation_policy import prices, state


def _rows(complex_trades, as_of=date(2026, 10, 1), other=()):
    rows, next_id = [], 1
    def add(name, day, area, price, dong="반포동", floor=10, year=2009):
        nonlocal next_id
        rows.append(dict(id=next_id, lawd_cd="11650", deal_year=day.year, deal_month=day.month, deal_day=day.day, price=price,
                         area_sqm=area, floor=str(floor), year_built=year, dong=dong, apt_name=name, transaction_type="중개거래",
                         is_cancelled=False))
        next_id += 1
    for days_ago, area, price in complex_trades:
        add("반포자이", as_of - timedelta(days=days_ago), area, price)
    for name, days_ago, area, price in other:
        add(name, as_of - timedelta(days=days_ago), area, price)
    return rows


def _evidence(rows, area=84.9, as_of=date(2026, 10, 1)):
    trades = apt.normalize(rows)
    comps = apt.ComparableIndex(trades, MarketIndex(trades))
    subject = apt.Subject("11650", "반포동", apt.complex_key("11650", "반포동", "반포자이아파트"), area, 10, None, as_of)
    return comps.evidence(subject)


def test_levels_follow_public_rule_then_weaker_evidence():
    five = [(d, 84.9, 480_000) for d in (10, 30, 60, 90, 120)]
    assert _evidence(_rows(five)).level == "A1"
    assert _evidence(_rows(five[:4])).level == "A2"                            # 6개월 4건: 공개 기준 미달
    assert _evidence(_rows([(300, 84.9, 470_000)])).level == "A2"               # 12개월 안 1건
    assert _evidence(_rows([(30, 59.9, 380_000)])).level == "A3"                # 같은 단지 다른 면적(±35%)
    similar = [("반포리체", d, 84.0, 400_000) for d in (20, 40, 60)]
    assert _evidence(_rows([], other=similar)).level == "A3"                    # 같은 동 유사 단지 3건
    assert _evidence(_rows([(400, 84.9, 470_000)], other=similar[:2])).level == "A4"


def test_evidence_never_uses_trades_on_or_after_cutoff():
    rows = _rows([(d, 84.9, 480_000) for d in (10, 30, 60, 90)] + [(0, 84.9, 999_000), (-5, 84.9, 999_000)])
    evidence = _evidence(rows)
    assert evidence.level == "A2" and evidence.a1_count == 4


def _artifact(tmp_path, deployment="service"):
    import pandas as pd
    spec = price_models.FeatureSpec(apt.CATEGORICAL, apt.BASE_NUMERIC + apt.COMP_NUMERIC)
    rows = []
    for i in range(120):
        values = {name: 1.0 for name in spec.numeric} | {"lawd": "11650", "dong": "반포동", "complex": f"단지{i % 7}"}
        values.update(comp_estimate=17.6 + (i % 5) * .01, area=60 + i % 30, target=17.6 + (i % 5) * .01)
        rows.append(values)
    frame = pd.DataFrame(rows)
    model = price_models.create("ridge", spec).fit(frame, frame)
    calibration = {"weights": {"A1": .5, "A2": 0.0, "A3": 0.0}, "interval": .85,
                   "interval_log_quantiles": {"A1": [-.08, .07], "A2": [-.12, .1], "A3": [-.3, .25]},
                   "confidence_by_level": {"A1": .89, "A2": .75, "A3": .42}}
    price_models.save(model, tmp_path, {"segment": "R-APT", "deployment": deployment, "calibration": calibration,
                                        "feature_origin_month": 2023 * 12 + 9, "history_months": 12, "trained_through": "2026-09-30",
                                        "withheld_levels": ["A4"]})
    return tmp_path


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AVM_APARTMENT_MODEL_DIR", str(_artifact(tmp_path)))
    apartment_avm._loaded.cache_clear()
    yield monkeypatch
    apartment_avm._loaded.cache_clear()


def test_runtime_estimate_returns_calibrated_band_and_level(runtime):
    runtime.setattr(apartment_avm, "_rows", lambda *args: _rows([(d, 84.9, 480_000) for d in (0, 30, 60, 90, 120)]))
    result = apartment_avm.estimate("11650", "반포동", ["반포자이", "반포자이아파트"], 84.97, 10, date(2026, 10, 1))
    assert result["level"] == "A1" and result["complex"] == "반포자이"
    assert result["counts"]["a1"] == 5  # 기준일 당일 신고도 운영에서는 근거에 포함
    assert result["value_min"] < result["estimated_value"] < result["value_max"]
    assert result["confidence"] == .89 and result["interval"] == .85 and result["comparable_weight"] == .5


def test_runtime_gives_no_price_without_evidence_or_unknown_complex(runtime):
    runtime.setattr(apartment_avm, "_rows", lambda *args: _rows([(400, 84.9, 470_000)]))
    assert "estimated_value" not in apartment_avm.estimate("11650", "반포동", ["반포자이"], 84.9, None, date(2026, 10, 1))
    runtime.setattr(apartment_avm, "_rows", lambda *args: _rows([(10, 84.9, 470_000)]))
    unknown = apartment_avm.estimate("11650", "반포동", ["없는단지"], 84.9, None, date(2026, 10, 1))
    assert unknown["level"] == "A4" and "estimated_value" not in unknown


def test_runtime_refuses_evaluation_only_or_missing_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("AVM_APARTMENT_MODEL_DIR", str(_artifact(tmp_path, deployment="evaluation_only")))
    apartment_avm._loaded.cache_clear()
    assert apartment_avm.estimate("11650", "반포동", ["반포자이"], 84.9, None, date(2026, 10, 1)) is None
    monkeypatch.setenv("AVM_APARTMENT_MODEL_DIR", str(tmp_path / "none"))
    apartment_avm._loaded.cache_clear()
    assert apartment_avm.estimate("11650", "반포동", ["반포자이"], 84.9, None, date(2026, 10, 1)) is None
    apartment_avm._loaded.cache_clear()


CONTEXT = {"level": "A2", "basis": "같은 단지·전용 ±10% 최근 12개월 2건", "complex": "마포래미안푸르지오", "counts": {"a1": 2},
           "model": "catboost", "model_version": "1", "trained_through": "2026-09-30", "interval": .85,
           "estimated_value": 1_500_000_000, "value_min": 1_350_000_000, "value_max": 1_650_000_000, "confidence": .75,
           "comparable_weight": 0.0, "comparable_per_sqm": None}


def test_below_public_rule_becomes_model_estimate_not_market_price(monkeypatch):
    from backend.valuation import policy
    value, data = state(), prices()
    data["samples"] = data["samples"][:2]
    assert policy.eligible_comparables(value, data) is None
    monkeypatch.setattr(apartment_avm, "estimate", lambda *args: dict(CONTEXT))
    context = policy.model_estimate(value, data)
    result = policy.model_result(value, context)["analysis_result"]
    assessment = result["valuation"]
    assert result["result_kind"] == assessment["result_kind"] == "model_estimate"
    assert result["estimated_value"] == 1_500_000_000 and not assessment["comparison_eligible"]
    assert assessment["model_status"] == "used" and assessment["model_context"]["level"] == "A2"
    assert [m["status"] for m in assessment["methods"]] == ["blocked", "selected"]
    assert not any("ML로 대체하지 않습니다" in text for text in assessment["next_actions"])
    from backend.services.case_snapshot_presentation import _appraisal_won
    assert _appraisal_won({"analysis_result": result}) is None  # 케이스 시장가격 비교에 쓰지 않는다


def test_public_rule_hybrid_replaces_rule_estimate_and_records_model(monkeypatch):
    from backend.valuation import policy
    value, data = state(), prices()
    monkeypatch.setattr(apartment_avm, "estimate", lambda *args: dict(CONTEXT, level="A1", comparable_weight=.25, hybrid_approved=True))
    assert policy.eligible_comparables(value, data)["count"] == 5
    policy.model_estimate(value, data)
    val = policy.apply_hybrid({"estimated_value": 80_000, "value_min": 72_000, "value_max": 88_000, "price_per_sqm": 952}, value["valuation_plan"], 84)
    assert (val["estimated_value"], val["value_min"], val["value_max"]) == (150_000, 135_000, 165_000)  # 만원
    assessment = policy.finalize({**value, "analysis_result": val})["analysis_result"]["valuation"]
    assert assessment["result_kind"] == "market_reference" and assessment["comparison_eligible"]
    assert assessment["model_status"] == "used" and assessment["interval_basis"] == "calibrated_holdout_quantiles"
    assert assessment["methods"][1]["status"] == "selected"


def test_without_model_artifact_existing_rules_are_unchanged(monkeypatch):
    from backend.valuation import policy
    value, data = state(), prices()
    monkeypatch.setattr(apartment_avm, "estimate", lambda *args: None)
    policy.eligible_comparables(value, data)
    assert policy.model_estimate(value, data) is None
    val = {"estimated_value": 80_000, "value_min": 72_000, "value_max": 88_000}
    assert policy.apply_hybrid(val, value["valuation_plan"], 84) == val
    assessment = policy.finalize({**value, "analysis_result": val})["analysis_result"]["valuation"]
    assert assessment["model_status"] == "not_used" and assessment["interval_basis"] == "heuristic_range_not_prediction_interval"


def test_unapproved_a1_hybrid_keeps_rule_price_and_says_why(monkeypatch):
    """A1 혼합은 두 기간 평가에서 일관되게 낫지 않아 미승인이다. 미승인 산출물은 기존 비교 규칙 가격을 바꾸지 않는다."""
    from backend.valuation import policy
    value, data = state(), prices()
    monkeypatch.setattr(apartment_avm, "estimate", lambda *args: dict(CONTEXT, level="A1", hybrid_approved=False))
    policy.eligible_comparables(value, data)
    policy.model_estimate(value, data)
    val = {"estimated_value": 80_000, "value_min": 72_000, "value_max": 88_000}
    assert policy.apply_hybrid(val, value["valuation_plan"], 84) == val
    assessment = policy.finalize({**value, "analysis_result": val})["analysis_result"]["valuation"]
    assert assessment["model_status"] == "not_used" and assessment["methods"][1]["status"] == "not_applicable"
    assert assessment["model_context"]["level"] == "A1" and not assessment["model_context"]["applied"]
