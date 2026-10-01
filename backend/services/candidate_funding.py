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
    from backend.services.core_calculations import calculate
    return calculate("funding_summary", {"request": request.model_dump(mode="json"), "calculated": calculated})


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
