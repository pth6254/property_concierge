"""계산 결과와 사용자의 자금 기준을 비교한다. 금융기관 승인 여부는 판단하지 않는다."""
from __future__ import annotations


def profile_funding_inputs(profile: dict, overrides: dict | None = None) -> dict:
    from schemas.concierge import ConciergeFunding

    values = {key: profile[key] for key in ConciergeFunding.model_fields if profile.get(key) is not None}
    values.setdefault("repayment_type", "equal_payment")
    # 개별 지정한 현금은 매수 가용액이다. 공통 조건의 보유 현금에서만 비상자금을 한 번 뺀다.
    if "cash_available" in values:
        values["cash_available"] -= profile.get("emergency_reserve", 0)
    values.update({key: value for key, value in (overrides or {}).items() if value is not None})
    return ConciergeFunding.model_validate(values).model_dump(exclude_none=True)


def funding_summary(request, calculated: dict) -> dict:
    loan = calculated.get("loan") or {}
    finance = calculated.get("finance_check") or {}
    required = calculated.get("required_cash")
    monthly = loan.get("monthly_payment")
    cash = request.cash_available
    limit = request.monthly_payment_limit
    return {
        "funding_version": 1,
        "home_count_basis": "after_purchase",
        "purchase_price": request.purchase_price,
        "loan_amount": calculated.get("loan_amount"),
        "annual_interest_rate": request.annual_interest_rate,
        "monthly_payment": monthly,
        "required_cash": required,
        "acquisition_cost": (calculated.get("acquisition_cost") or {}).get("total"),
        "cash_available": cash,
        # 임대보증금은 수령 시점과 반환 의무가 있으므로 잔금 자금으로 자동 차감하지 않는다.
        "cash_shortfall": max(required - cash, 0) if required is not None and cash is not None else None,
        "monthly_payment_limit": limit,
        "monthly_payment_exceeded": monthly > limit if monthly is not None and limit is not None else None,
        "dsr_ratio": finance.get("dsr"),
        "finance_check": finance,
        "annual_equity_roi": (calculated.get("scenario_base") or {}).get("annual_equity_roi"),
        "inputs": request.model_dump(mode="json", exclude={"case_id", "candidate_id"}),
    }


def funding_issues(summary: dict) -> list[tuple[str, str, str, str]]:
    issues = []
    def add(code, title, reason, priority="warning"):
        issues.append((code, title, reason, priority))

    if summary.get("required_cash") is None or summary.get("monthly_payment") is None:
        add("funding_details", "자금 분석 갱신", "필요 현금·월 상환액이 없는 이전 결과입니다. 다시 계산하세요.", "normal")
        return issues
    if summary.get("cash_available") is None:
        add("funding_cash_input", "보유 현금 입력", "취득비용을 포함한 필요 현금과 비교할 보유 현금이 없습니다.", "input")
    elif (summary.get("cash_shortfall") or 0) > 0:
        add("funding_shortfall", "부족한 자금 조달 확인", f"취득비용 포함 필요 현금 대비 {summary['cash_shortfall']:,}원이 부족합니다.")
    if (summary.get("loan_amount") or 0) > 0:
        if summary.get("monthly_payment_limit") is None:
            add("funding_payment_input", "월 상환 한도 입력", "감당 가능한 월 대출 상환액을 입력해 계산 결과와 비교하세요.", "input")
        elif summary.get("monthly_payment_exceeded"):
            add("funding_payment", "월 상환 부담 확인", "계산된 첫 달 대출 상환액이 입력한 월 상환 한도를 초과합니다.")
        finance = summary.get("finance_check") or {}
        if finance.get("dsr") is None:
            add("funding_income", "연소득 확인", "DSR을 계산할 연소득이 없습니다. 기존 대출 상환액도 함께 확인하세요.", "input")
        if finance.get("ltv_exceeded") or finance.get("dsr_exceeded"):
            add("funding_finance", "대출 조건 재검토", "계산기에 적용된 LTV 또는 DSR 기준을 초과합니다. 금융기관에서 가능 금액을 확인하세요.")
    return issues
