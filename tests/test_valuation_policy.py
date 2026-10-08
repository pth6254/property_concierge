"""가격 정확도가 아닌 적용 범위·자료 배제·결과 분류의 회귀 검사."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from backend.valuation.policy import plan, allowed, eligible_comparables, finalize
from backend.router import run_appraisal
from backend.services.case_snapshot_presentation import _appraisal_won


def state(**changes):
    raw = dict(property_category="주거용", property_detail="아파트", address="서울 마포구 아현동 777",
               area_sqm=84, appraisal_date="20260115",
               valuation_context=dict(scope="single_unit", area_basis="exclusive", transaction_type="sale"))
    raw.update(changes)
    value = dict(building_name="마포래미안푸르지오", appraisal_purpose="매매", raw_inputs=raw)
    value["valuation_plan"] = plan(value)
    return value


def prices():
    return dict(apt_name_matched="마포래미안푸르지오", target_dong="아현동", target_sigungu_code="11440",
                samples=[dict(apt_name="마포래미안푸르지오", dong="아현동", bjdong_code="1144010100",
                    price=80_000, area_sqm=84, deal_year=2026, deal_month=1, deal_day=i,
                    transaction_ref=f"valid-{i}", per_sqm=80_000 / 84) for i in range(1, 6)])


@pytest.mark.parametrize("change,kind", [
    ({"property_category": "알수없음"}, "unsupported"), ({"property_detail": ""}, "unsupported"),
    ({"property_detail": "오피스텔"}, "withheld"), ({"property_detail": "단독"}, "withheld"),
    ({"property_category": "산업용", "property_detail": "공장"}, "unsupported"),
    ({"area_sqm": None}, "withheld"), ({"address": ""}, "withheld"),
    ({"appraisal_date": "29990101"}, "withheld"), ({"appraisal_date": "20260230"}, "withheld"),
    ({"valuation_context": dict(scope="whole_building", area_basis="exclusive")}, "withheld"),
    ({"valuation_context": dict(scope="single_unit", area_basis="supply")}, "withheld"),
    ({"valuation_context": dict(scope="single_unit", area_basis="unknown")}, "withheld"),
    ({"valuation_context": dict(scope="single_unit", area_basis="exclusive", transaction_type="rent")}, "unsupported"),
])
def test_blocked_inputs_never_invoke_price_graph(change, kind, monkeypatch):
    import backend.router as router
    monkeypatch.setattr(router, "_get_graph", lambda: pytest.fail("차단 입력으로 모델 실행"))
    raw = state(**change)["raw_inputs"]
    result = run_appraisal("자료 검토", building_name="마포래미안푸르지오", **raw)
    assert not result.get("error"), result.get("error")
    assessment = result["analysis_result"]["valuation"]
    assert assessment["result_kind"] == kind
    assert not assessment["comparison_eligible"] and assessment["next_actions"]
    assert _appraisal_won(result) is None


def test_excludes_future_old_other_complex_area_cancelled_and_duplicates():
    value, data = state(), prices()
    base = data["samples"][0]
    bad = [dict(deal_day=16), dict(deal_year=2024), dict(apt_name="다른단지"),
           dict(area_sqm=120), dict(price=0), dict(cancelled=True), dict(cancel_date="20260110"),
           dict(deal_day=None), dict(bjdong_code="1168010100"), dict(dong="다른동")]
    data["samples"] += [{**base, **row, "transaction_ref": f"bad-{i}"} for i, row in enumerate(bad)]
    data["samples"] += [dict(base)]
    result = eligible_comparables(value, data)
    assert result["count"] == 5 and result["avg"] == 80_000
    assert [r["transaction_ref"] for r in result["samples"]] == [f"valid-{i}" for i in range(1, 6)]
    complete = finalize({**value, "analysis_result": {"estimated_value": 80_000}})
    assessment = complete["analysis_result"]["valuation"]
    assert assessment["result_kind"] == "market_reference" and assessment["comparison_eligible"]
    assert assessment["model_status"] == "not_used"
    assert assessment["interval_basis"] == "heuristic_range_not_prediction_interval"


def test_four_unique_transactions_withhold_without_ml_substitution():
    value, data = state(), prices()
    data["samples"] = data["samples"][:4] * 3
    assert eligible_comparables(value, data) is None
    result = finalize({**value, "analysis_result": {"estimated_value": 999_999}})["analysis_result"]
    assert result["estimated_value"] is None
    assert all(m["status"] == "blocked" for m in result["valuation"]["methods"])


def test_price_without_evidence_is_never_comparison_eligible():
    result = finalize({**state(), "analysis_result": {"estimated_value": 80_000}})["analysis_result"]
    assert result["result_kind"] == "withheld" and result["estimated_value"] is None


def test_subject_fingerprint_changes_with_area_basis_unit_and_date():
    first = state()["valuation_plan"]["input_fingerprint"]
    for patch in [dict(area_sqm=59), dict(appraisal_date="20260114"),
                  dict(valuation_context=dict(scope="single_unit", area_basis="supply", ho="101"))]:
        assert state(**patch)["valuation_plan"]["input_fingerprint"] != first


def test_natural_language_unknown_type_cannot_route_to_residential():
    from backend.graphs.appraisal_graph import router_node, route_by_category
    value = {"intent": SimpleNamespace(category="기타", category_detail="", location_normalized="서울", appraisal_date="")}
    assert route_by_category(value) == "error_handler"
    result = router_node(value)
    assert route_by_category(result) == "policy_result"
    assert result["analysis_result"]["valuation"]["result_kind"] == "unsupported"


@pytest.mark.parametrize("kind", ["conditional_scenario", "public_reference", "partial_reference", "withheld", "unsupported"])
def test_nonmarket_envelope_cannot_reuse_top_level_old_price(kind):
    value = deepcopy(state()["valuation_plan"])
    value["result_kind"] = kind
    assert _appraisal_won({"estimated_value": 888_888, "analysis_result": {"valuation": value, "estimated_value": 999_999}}) is None


def test_partial_land_remains_public_reference_with_missing_actions():
    value = state(property_category="토지", property_detail="토지", valuation_context={"scope": "single_parcel", "area_basis": "land"})
    result = finalize({**value, "analysis_result": {"result_kind": "public_reference", "land_information": {
        "status": "partial", "sources": [{"id": "land_price", "status": "unavailable", "title": "공시지가"}]}}})
    assessment = result["analysis_result"]["valuation"]
    assert assessment["next_actions"] and not assessment["comparison_eligible"]
    assert assessment["checks"][-1]["status"] == "missing"


def test_residential_engine_report_keeps_policy_and_won_units(monkeypatch):
    from backend import agents
    from backend.appraisal_report import report_node
    value = state()
    value["intent"] = SimpleNamespace(category="주거용", category_detail="아파트", location_normalized="서울 마포구 아현동 777",
        appraisal_date="20260115", area_min=84, area_max=84)
    value["geocoding_result"] = dict(region_2depth="마포구", region_3depth="아현동", sigungu_cd="11440")
    data = prices()
    data.update(avg=80_000, min=80_000, max=80_000, count=5, per_sqm_avg=952, source="국토부 실거래가")
    monkeypatch.setattr(agents, "fetch_real_transaction_prices", lambda *a, **kw: data)
    monkeypatch.setattr(agents, "_fetch_build_year", lambda _: (2005, "철근콘크리트"))
    monkeypatch.setattr(agents, "search_nearby_facilities", lambda *a, **kw: {})
    monkeypatch.setattr(agents, "search_web_tavily", lambda *_: "")
    monkeypatch.setattr(agents, "generate_appraisal_opinion", lambda *a, **kw: {})
    result = report_node(agents.residential_agent(value))
    analysis = result["analysis_result"]
    assert analysis["valuation"]["comparison_eligible"]
    assert analysis["comparable_count"] == 5
    assert _appraisal_won(result) == analysis["estimated_value"] * 10_000
    serialized = result["report_output"].model_dump(mode="json")
    assert serialized["structured"]["valuation"]["subject"]["area_sqm"] == 84
    assert serialized["structured"]["estimated_price"] == _appraisal_won(result)


def test_nearby_facility_result_never_changes_price(monkeypatch):
    """역 거리 보정 제거 회귀: 시설 조회 실패({})·역세권·원거리가 모두 같은 추정가여야 한다."""
    from backend import agents
    data = prices()
    data.update(avg=80_000, min=80_000, max=80_000, count=5, per_sqm_avg=952, source="국토부 실거래가")
    monkeypatch.setattr(agents, "fetch_real_transaction_prices", lambda *a, **kw: data)
    monkeypatch.setattr(agents, "_fetch_build_year", lambda _: (2005, "철근콘크리트"))
    monkeypatch.setattr(agents, "search_web_tavily", lambda *_: "")
    monkeypatch.setattr(agents, "generate_appraisal_opinion", lambda *a, **kw: {})
    seen = []
    for nearby in ({}, {"지하철역": {"nearest_m": 100}}, {"지하철역": {"nearest_m": 2000}}):
        value = state()
        value["intent"] = SimpleNamespace(category="주거용", category_detail="아파트", location_normalized="서울 마포구 아현동 777",
            appraisal_date="20260115", area_min=84, area_max=84)
        value["geocoding_result"] = dict(region_2depth="마포구", region_3depth="아현동", sigungu_cd="11440")
        monkeypatch.setattr(agents, "search_nearby_facilities", lambda *a, _n=nearby, **kw: _n)
        analysis = agents.residential_agent(value)["analysis_result"]
        seen.append((analysis["estimated_value"], analysis["value_min"], analysis["value_max"]))
    assert len(set(seen)) == 1


def test_withheld_apartment_exposes_reference_trades_without_price():
    """5건 미만 보류에서도 참고 거래를 보여주되 가격·비교 자격은 만들지 않는다."""
    value = state()
    data = prices()
    data["samples"] = data["samples"][:3] + [
        dict(data["samples"][0], deal_year=2025, deal_month=6, deal_day=3, transaction_ref="old-in-window", price=78_000),
        dict(data["samples"][0], deal_year=2024, transaction_ref="too-old"),
        dict(data["samples"][0], area_sqm=110, transaction_ref="area-out"),
        dict(data["samples"][0], is_cancelled=True, transaction_ref="cancelled")]
    assert eligible_comparables(value, data) is None
    context = value["valuation_plan"]["reference_context"]
    assert context["time_adjusted"] is False and context["trade_count"] == 4
    assert [t["deal_date"] for t in context["trades"]][0] == "2026-01-03"
    assert context["trades"][-1]["deal_date"] == "2025-06-03" and context["trades"][-1]["price_won"] == 780_000_000
    assert context["per_sqm_min_won"] <= context["per_sqm_median_won"] <= context["per_sqm_max_won"]
    assert not value["valuation_plan"]["comparison_eligible"]
    result = finalize({**value, "analysis_result": {}})["analysis_result"]
    assert result["estimated_value"] is None and result["valuation"]["reference_context"]["trade_count"] == 4


def test_jeonse_context_uses_same_complex_jeonse_only_and_flags_thin_samples():
    from datetime import date
    from backend.valuation import jeonse_context
    value = state()
    data = prices()
    target = value["valuation_plan"]["subject"]
    lease = lambda **kw: dict(apt_name="마포래미안푸르지오", dong="아현동", area_sqm=84, deposit_won=480_000_000,
        deal_year="2026", deal_month="01", deal_day="05", contract_type="신규", **kw)
    rows = [lease(), lease(), dict(lease(), apt_name="다른단지"), dict(lease(), area_sqm=120), dict(lease(), deal_year="2025", deal_month="01")]
    context = jeonse_context.build(data, target, date(2026, 1, 15), fetch=lambda lawd, ym: rows if ym == "202601" else [])
    assert context["lease_count"] == 2 and context["sale_count"] == 5
    assert context["sufficient"] is False  # 전세 2건은 기준(3건) 미만
    assert context["ratio_pct"] == round(480_000_000 / 84 / (80_000 * 10_000 / 84) * 100, 1)
    assert jeonse_context.build(data, target, date(2026, 1, 15), fetch=lambda lawd, ym: None) is None
    assert jeonse_context.build({**data, "apt_name_matched": ""}, target, date(2026, 1, 15), fetch=lambda *a: []) is None
