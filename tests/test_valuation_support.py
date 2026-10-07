"""유형별 시나리오의 실제 Spring 계산·작업 계약. 수식 검증 원본은 Kotlin 테스트다."""
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from pydantic import ValidationError
from schemas.income_valuation import IncomeValuationInput
from backend.router import run_appraisal
from backend.services.case_snapshot_presentation import _appraisal_won, _appraisal_evidence


def inputs():
    return dict(monthly_rent_won=10_000_000, monthly_operating_cost_min_won=1_000_000,
                monthly_operating_cost_max_won=2_000_000, cap_rate_min_pct=4, cap_rate_max_pct=6,
                asking_price_won=2_000_000_000, valuation_unit="whole_building",
                as_of_date=datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat())


@pytest.mark.parametrize("category", ["상업용", "업무용"])
def test_actual_spring_income_contract_and_report(category):
    result = run_appraisal("수익 검토", address="서울 강남구 역삼동 123", property_category=category, income_valuation=inputs())
    assert not result.get("error"), result.get("error")
    scenario = result["analysis_result"]["income_scenario"]
    assert scenario["calculator_engine"] == "kotlin-spring"
    assert scenario["low_price_won"] == 1_600_000_000
    assert scenario["high_price_won"] == 2_700_000_000
    assert scenario["net_yield_min_pct"] == 4.8
    assert _appraisal_won(result) is None
    assert _appraisal_evidence(result)["result_kind"] == "conditional_scenario"
    assert result["report_output"]["structured"]["estimated_price"] is None
    assert "1,600,000,000" in result["final_report"]


@pytest.mark.parametrize("category", ["상업용", "업무용"])
def test_missing_income_does_not_use_fixed_rent_or_llm(category, monkeypatch):
    import backend.services.valuation_support as support
    monkeypatch.setattr(support, "calculate", lambda *_: pytest.fail("미입력 계산 실행"))
    result = run_appraisal("임대료 없는 요청", address="서울 강남구 역삼동 123", property_category=category)
    assert result["analysis_result"]["result_kind"] == "withheld"
    assert _appraisal_won(result) is None


def test_job_input_keeps_income_and_checks_type_date():
    from api.routes.appraisal import AppraisalRequest
    data = dict(user_input="검토", property_category="상업용", income_valuation=inputs())
    req = AppraisalRequest.model_validate(data)
    assert req.model_dump(mode="json")["income_valuation"]["monthly_rent_won"] == 10_000_000
    with pytest.raises(ValidationError): AppraisalRequest.model_validate({**data, "property_category": "주거용"})
    with pytest.raises(ValidationError): AppraisalRequest.model_validate({**data, "appraisal_date": "20200101"})


@pytest.mark.parametrize("patch", [{"monthly_rent_won": None}, {"monthly_rent_won": 1.5}, {"monthly_rent_won": True},
                                    {"cap_rate_min_pct": 0}, {"cap_rate_min_pct": 7}, {"monthly_operating_cost_min_won": None},
                                    {"as_of_date": "2999-01-01"}, {"cap_rate_min_pct": "NaN"}])
def test_income_invalid_contract_is_rejected(patch):
    with pytest.raises(ValidationError): IncomeValuationInput.model_validate({**inputs(), **patch})


def test_mismatched_calculation_response_is_not_reported(monkeypatch):
    import backend.services.valuation_support as support
    monkeypatch.setattr(support, "calculate", lambda *_: {"calculator_engine": "kotlin-spring", "inputs": {**inputs(), "monthly_rent_won": 1}})
    result = run_appraisal("검토", address="서울", property_category="상업용", income_valuation=inputs())
    assert result["error"] and not result["analysis_result"]


def test_land_information_does_not_become_market_value(monkeypatch):
    import backend.services.valuation_support as support
    class Response:
        status_code = 200
        def json(self): return {"status": "found", "pnu": "1114010300100310000", "official_price_year": "2026", "official_reference_total_won": 10_000_000,
                               "limitations": ["공시자료 참고"], "sources": []}
    monkeypatch.setattr(support, "request_core", lambda path, body: Response())
    result = run_appraisal("토지 검토", address="서울 중구 세종대로 110", property_category="토지")
    assert result["analysis_result"]["result_kind"] == "public_reference"
    assert _appraisal_won(result) is None
    assert _appraisal_evidence(result)["land_information"]["official_reference_total_won"] == 10_000_000


def test_no_stale_price_reused_for_scenario():
    assert _appraisal_won({"estimated_value": 1_000_000, "analysis_result": {"result_kind": "conditional_scenario"}}) is None


@pytest.mark.parametrize("category", ["상업용", "업무용", "토지"])
def test_direct_recommendation_analysis_uses_same_withholding_policy(category, monkeypatch):
    from backend.services import price_analysis_service as service
    from schemas.property_query import PropertyQuery
    monkeypatch.setattr(service, "fetch_real_transaction_prices", lambda **_: pytest.fail("비주거 구 평균가 대체 금지"))
    result = service.analyze_price(PropertyQuery(intent="price_analysis", property_type=category, region="중구"))
    assert result.estimated_price is None and result.low_price is None and result.high_price is None
    assert result.raw["result_kind"] == "withheld" and result.warnings
