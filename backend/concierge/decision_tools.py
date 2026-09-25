"""소유한 후보의 계산과 저장된 분석 비교를 대화에서 재사용한다."""
from schemas.concierge import ConciergeFunding, ConciergeToolResult

FUNDING_LABELS = {
    "cash_available": "보유 현금(원)", "monthly_payment_limit": "월 상환 한도(원)",
    "loan_ratio": "대출 비율(%)", "annual_interest_rate": "연 금리(%)",
    "loan_years": "대출 기간(년)", "repayment_type": "상환 방식(원리금균등·원금균등·만기일시)",
    "owned_homes": "취득 후 주택 수", "adjusted_area": "조정대상지역 여부",
    "annual_income": "연소득(원)", "existing_loan_annual_payment": "기존 대출 연간 상환액(원)",
}


def merge_funding(changes: dict, previous: dict) -> tuple[dict, list[str]]:
    values, invalid = dict(previous), []
    for key, value in changes.items():
        if value is None:
            continue
        try:
            validated = ConciergeFunding.model_validate({key: value})
            values[key] = getattr(validated, key)
        except (ValueError, AttributeError):
            invalid.append(key)
    return values, invalid


def _case(user_id, context):
    from api import case_db
    if not context or not context.get("case_id"):
        return None
    case = case_db.get_case(context["case_id"], user_id)
    if not case:
        raise LookupError("case_not_found")
    return case


def simulate_investment(criteria, user_id, candidate_context=None, *, funding=None):
    from api.routes.simulation import SimulationRequest, execute_simulation
    from backend.services.candidate_funding import funding_issues
    tool = "simulate_investment"
    case = _case(user_id, candidate_context)
    candidate = next((p for p in (case or {}).get("properties", [])
                      if p["id"] == (candidate_context or {}).get("candidate_id")), None)
    if not candidate:
        return ConciergeToolResult(tool=tool, status="needs_input", missing_fields=["candidate"],
                                   data={"answer": "자금을 분석할 케이스와 후보를 선택해주세요."})
    # 케이스 공통 조건을 기본값으로 쓰되 대화에서 지정한 값이 우선한다.
    profile = (case or {}).get("buyer_profile") or {}
    profile_funding = {key: profile[key] for key in FUNDING_LABELS if profile.get(key) is not None}
    profile_funding.setdefault("repayment_type", "equal_payment")
    values = ConciergeFunding.model_validate({**profile_funding, **(funding or {})}).model_dump(exclude_none=True)
    if "cash_available" in profile_funding and "cash_available" not in (funding or {}):
        values["cash_available"] = profile_funding["cash_available"] - profile.get("emergency_reserve", 0)
    required = ["cash_available", "loan_ratio", "owned_homes", "adjusted_area"]
    if values.get("loan_ratio", 1) > 0:
        required += ["annual_interest_rate", "loan_years", "repayment_type", "existing_loan_annual_payment"]
    missing = [key for key in required if key not in values]
    data = {"case_id": case["id"], "candidate_id": candidate["id"], "candidate_name": candidate["name"],
            "funding_inputs": values, "result_url": f"/cases/{case['id']}"}
    if not candidate.get("asking_price"):
        missing.append("asking_price")
    from api.candidate_appraisal import PROPERTY_TYPES
    property_types = {key: value[1] for key, value in PROPERTY_TYPES.items()}
    property_types.update(non_residential="상업용", industrial="산업용")
    if candidate.get("category") not in property_types:
        missing.append("property_type")
    if missing:
        labels = {**FUNDING_LABELS, "asking_price": "후보 희망가", "property_type": "후보 물건 종류"}
        data["answer"] = f"{candidate['name']}의 자금 분석에 필요한 조건을 알려주세요: " + ", ".join(labels[k] for k in missing) + ". 입력한 조건은 이 후보에 한해 이어서 사용합니다."
        return ConciergeToolResult(tool=tool, status="needs_input", missing_fields=missing, data=data)
    req = SimulationRequest(case_id=case["id"], candidate_id=candidate["id"],
        purchase_price=candidate["asking_price"], property_type=property_types[candidate["category"]], **values)
    result = execute_simulation(req, {"id": user_id})
    summary = result.get("candidate_funding")
    if result.get("error") or not summary:
        return ConciergeToolResult(tool=tool, status="error", data={"answer": "자금 계산을 완료하지 못했습니다. 입력 조건을 확인하고 다시 요청해주세요."})
    warnings = [issue[1] for issue in funding_issues(summary)]
    def money(value):
        return f"{value:,}원" if value is not None else "미확인"
    data.update(candidate_funding=summary, warnings=warnings,
        answer=f"{candidate['name']}의 현재 희망가 {money(candidate['asking_price'])}을 기준으로 계산하고 후보에 저장했습니다.\n"
        f"필요 현금 {money(summary.get('required_cash'))}, 현금 부족액 {money(summary.get('cash_shortfall'))}, 월 상환액 {money(summary.get('monthly_payment'))}.\n"
        + ("확인할 항목: " + ", ".join(warnings) + ".\n" if warnings else "")
        + "참고용 시뮬레이션이며 대출 승인을 보장하지 않습니다. 부가 시나리오는 보유 3년·가격 상승률 0%·임대수입 없음으로 계산했습니다.")
    return ConciergeToolResult(tool=tool, status="completed", data=data)


def compare_properties(criteria, user_id, candidate_context=None):
    from backend.services.case_comparison_service import compare_case_candidates
    case = _case(user_id, candidate_context)
    if not case:
        return ConciergeToolResult(tool="compare_properties", status="needs_input", missing_fields=["case"],
                                   data={"answer": "비교할 후보가 담긴 케이스를 선택해주세요."})
    comparison = compare_case_candidates(case)
    rows = comparison["rows"]
    lines = [f"{case['title']}의 저장된 후보 {len(rows)}개를 비교했습니다."]
    for row in rows:
        price = f"{row['asking_price']:,}원" if row["asking_price"] is not None else "미입력"
        details = []
        if row["estimated_value"] is not None:
            details.append(f"AVM 추정가 {row['estimated_value']:,}원({row['analysis_status']['appraisal']})")
        for key, label in [("required_cash", "필요 현금"), ("monthly_payment", "월 상환액"), ("cash_shortfall", "현금 부족액")]:
            value = (row["funding"] or {}).get(key)
            if value is not None:
                details.append(f"{label} {value:,}원")
        lines.append(f"• {row['name']}: 희망가 {price}. " + (", ".join(details) + ". " if details else "")
                     + "확인할 항목: " + ", ".join(row["warnings"] + row["missing"] or ["현재 등록된 검토 항목 없음"]) + ".")
    lines.append("갱신이 필요한 분석은 다시 실행해주세요. 자료가 부족한 상태에서 우선순위나 매수 결론을 확정하지 않습니다.")
    if len(rows) < 2:
        lines.append("후보 비교를 위해 케이스에 후보를 2개 이상 등록해주세요.")
    return ConciergeToolResult(tool="compare_properties", status="completed" if len(rows) >= 2 else "needs_input",
        missing_fields=[] if len(rows) >= 2 else ["candidates"],
        data={"answer": "\n".join(lines), "comparison": comparison, "case_id": case["id"], "result_url": f"/cases/{case['id']}"})
