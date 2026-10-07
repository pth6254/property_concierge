"""비주거 검토 결과를 기존 AVM 작업·이력 계약에 연결한다. 가격 수식은 Spring에만 둔다."""
from datetime import datetime
from zoneinfo import ZoneInfo
from api.core_bridge import request_core
from backend.services.core_calculations import calculate
from schemas.income_valuation import IncomeValuationInput


def analyze_support(state: dict, category: str) -> dict:
    raw = state.get("raw_inputs") or {}
    intent = state.get("intent")
    address = raw.get("address") or getattr(intent, "location_normalized", "")
    date_text = raw.get("appraisal_date") or getattr(intent, "appraisal_date", "")
    as_of = datetime.strptime(date_text, "%Y%m%d").date().isoformat() if date_text else datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    result = {"agent_name": category, "estimated_value": None, "value_min": None, "value_max": None,
              "value_unit": "원", "result_kind": "withheld", "support_version": "valuation-support-1.0",
              "address": address, "as_of_date": as_of, "limitations": []}
    if category in {"상업용", "업무용"}:
        result["valuation_method"] = "현재 임대료 기반 수익 시나리오"
        data = raw.get("income_valuation")
        if data is None:
            result["limitations"] = ["현재 수령 월세·소유자 운영비·환원율 범위를 시세추정 화면에서 입력해주세요. 고정 임대료로 대체하지 않습니다."]
        else:
            inputs = IncomeValuationInput.model_validate(data)
            if inputs.as_of_date.isoformat() != as_of:
                raise ValueError("임대료 확인일과 분석 기준일을 맞춰주세요")
            scenario = calculate("income_valuation", inputs.model_dump(mode="json"))
            if (not isinstance(scenario, dict) or scenario.get("calculator_engine") != "kotlin-spring"
                    or IncomeValuationInput.model_validate(scenario.get("inputs")) != inputs
                    or scenario.get("result_kind") not in {"conditional_scenario", "withheld"}):
                raise ValueError("계산 결과의 입력 조건과 실행 원본을 확인하지 못했습니다")
            result.update(income_scenario=scenario, result_kind=scenario["result_kind"], limitations=scenario["limitations"])
    else:
        result["valuation_method"] = "필지 공개정보 자동 조회"
        response = request_core("/internal/v1/land/lookup", {"address": address, "as_of_date": as_of})
        if response.status_code == 200:
            info = response.json()
            result.update(land_information=info, result_kind="public_reference", limitations=info["limitations"])
            result["limitations"].append("토지 시장가격은 비교 근거 검증 전까지 산출하지 않습니다.")
        else:
            result["limitations"] = ["필지 공개정보를 확인하지 못했습니다. 정확한 지번 주소와 API 설정을 확인해주세요. 미확인 값을 0으로 대체하지 않습니다."]
    return {**state, "analysis_result": result, "error": ""}


def support_report(state: dict) -> dict:
    result = state["analysis_result"]
    lines = ["# 부동산 검토 참고자료", "", f"- 주소: {result['address']}", f"- 기준일: {result['as_of_date']}",
             f"- 검토 방식: {result['valuation_method']}", ""]
    scenario = result.get("income_scenario")
    if scenario:
        lines += [f"- 현재 월세 연 환산: {scenario['annual_rent_won']:,}원", "", "| 가정 환원율 | 가격 하한 | 가격 상한 |", "|---|---|---|"]
        for row in scenario["scenarios"]:
            lines.append(f"| {row['cap_rate_pct']}% | {row['low_price_won']:,}원 | {row['high_price_won']:,}원 |")
    land = result.get("land_information")
    if land:
        lines += [f"- 필지: {land['pnu']}", f"- 공시지가 기준연도: {land.get('official_price_year') or '미확인'}"]
        lines += [f"- {s['title']}: {s['status']} ({s['url']})" for s in land["sources"]]
    lines += ["", *[f"- {text}" for text in result["limitations"]], "", "AVM 기반 참고용 분석이며 법정 감정평가가 아닙니다."]
    return {**state, "final_report": "\n".join(lines), "report_output": {"structured": {
        "estimated_price": None, "low_price": None, "high_price": None, "confidence": None,
        "warnings": result["limitations"], "appraisal_date": result["as_of_date"], "raw": result,
        "valuation": result.get("valuation"),
    }}}
