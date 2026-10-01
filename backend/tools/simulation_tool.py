"""
simulation_tool.py — 부동산 투자 시뮬레이션 계산 엔진 (Phase 4-1)

순수 계산 함수 모음. 외부 API 호출 없음.

단위 규칙:
  금액  — 원 (int), 소수점 이하 반올림
  비율  — % (float, 예: 4.0 = 4%)
  기간  — 년 (int) 또는 개월 수 (int)

간이 계산 고지:
  취득세·중개보수는 2024년 기준 간이 세율을 적용한다.
  실제 세율은 취득 시점·보유 주택 수·지역 등에 따라 달라질 수 있으므로
  이 결과를 실제 투자 의사결정에 직접 사용하지 마라.
"""

from __future__ import annotations

import math
import os
import sys

_TOOLS_DIR    = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_TOOLS_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schemas.simulation import (
    AcquisitionCost,
    CashFlowSummary,
    FinanceCheck,
    LoanSummary,
    RateSensitivityCell,
    ScenarioResult,
    SimulationInput,
    SimulationResult,
)
from tax_rules import (
    TAX_RULES_AS_OF,
    calc_annual_holding_tax,
    calc_capital_gains_tax,
    check_dsr,
    check_ltv,
    estimate_official_price,
)


# ─────────────────────────────────────────
#  취득세 (간이)
# ─────────────────────────────────────────

# 매물 유형 → 세율 버킷
_COMMERCIAL_TYPES = {"상가", "오피스", "사무실", "업무용", "상업용", "공장", "창고", "산업용", "토지"}


def calc_acquisition_tax(
    purchase_price: int,
    property_type: str | None,
    owned_homes: int = 1,
) -> int:
    """
    취득세 간이 계산 (취득세 + 지방교육세 포함).

    주거용 1주택: 가격 구간별 1.1 / 2.2 / 3.3%
    주거용 2주택: 8% (조정지역 기준 간이 — 비조정은 기본세율 적용)
    주거용 3주택 이상: 12% (조정지역 기준 간이)
    상업용·업무용·산업용·토지: 4.4% (owned_homes 무관)
    """
    ptype = (property_type or "").strip()
    is_commercial = any(kw in ptype for kw in _COMMERCIAL_TYPES)

    if is_commercial:
        rate = 0.044
    elif owned_homes >= 3:
        rate = 0.12   # 3주택 이상 중과 (조정지역 기준 간이)
    elif owned_homes == 2:
        rate = 0.08   # 2주택 중과 (조정지역 기준 간이)
    elif purchase_price <= 600_000_000:
        rate = 0.011
    elif purchase_price <= 900_000_000:
        rate = 0.022
    else:
        rate = 0.033

    return round(purchase_price * rate)


# ─────────────────────────────────────────
#  중개보수 (간이)
# ─────────────────────────────────────────

_BROKERAGE_BRACKETS = [
    (50_000_000,    0.006, 250_000),
    (200_000_000,   0.005, 800_000),
    (900_000_000,   0.004, None),
    (1_200_000_000, 0.005, None),
    (1_500_000_000, 0.006, None),
    (float("inf"),  0.007, None),
]


def calc_brokerage_fee(purchase_price: int) -> int:
    """
    공인중개사 중개보수 간이 계산 (매매 기준, VAT 별도).

    매매가 구간별 상한 요율 적용.
    괄호 안의 한도액이 있는 구간은 min(요율 계산값, 한도액)을 적용한다.
    """
    for threshold, rate, cap in _BROKERAGE_BRACKETS:
        if purchase_price <= threshold:
            fee = round(purchase_price * rate)
            if cap is not None:
                fee = min(fee, cap)
            return fee
    # fallback (shouldn't reach)
    return round(purchase_price * 0.007)


# ─────────────────────────────────────────
#  기타 취득 비용
# ─────────────────────────────────────────

def calc_other_acquisition_cost(purchase_price: int) -> int:
    """
    등기 비용·인지세 등 기타 취득 비용 간이 계산.
    매수가의 0.1%, 최소 300,000원, 최대 2,000,000원.
    """
    raw = round(purchase_price * 0.001)
    return max(300_000, min(raw, 2_000_000))


# ─────────────────────────────────────────
#  총 취득 비용
# ─────────────────────────────────────────

def calc_total_acquisition_cost(
    purchase_price: int,
    property_type: str | None,
    owned_homes: int = 1,
) -> AcquisitionCost:
    acq_tax  = calc_acquisition_tax(purchase_price, property_type, owned_homes)
    brok_fee = calc_brokerage_fee(purchase_price)
    other    = calc_other_acquisition_cost(purchase_price)
    return AcquisitionCost(
        acquisition_tax = acq_tax,
        brokerage_fee   = brok_fee,
        other_cost      = other,
        total           = acq_tax + brok_fee + other,
    )


# ─────────────────────────────────────────
#  대출 월 상환액
# ─────────────────────────────────────────

def calc_monthly_payment(
    loan_amount: int,
    annual_interest_rate: float,
    loan_years: int,
    repayment_type: str = "equal_payment",
) -> int:
    """
    대출 첫 달 월 상환액 계산.

    equal_payment  (원리금균등): 매달 동일 금액
    equal_principal (원금균등) : 첫 달 상환액 (이후 줄어듦)
    interest_only  (만기일시)  : 이자만 납부
    """
    if loan_amount <= 0:
        return 0

    r = annual_interest_rate / 100 / 12
    n = loan_years * 12

    if repayment_type == "equal_payment":
        if r == 0:
            return round(loan_amount / n)
        m = loan_amount * r * (1 + r) ** n / ((1 + r) ** n - 1)
        return round(m)

    if repayment_type == "equal_principal":
        principal_part = loan_amount / n
        interest_part  = loan_amount * r
        return round(principal_part + interest_part)

    if repayment_type == "interest_only":
        return round(loan_amount * r)

    raise ValueError(f"알 수 없는 상환 방식: {repayment_type}")


def calc_interest_during_holding(
    loan_amount: int,
    annual_interest_rate: float,
    loan_years: int,
    holding_years: int,
    repayment_type: str = "equal_payment",
) -> int:
    """
    보유 기간 동안 실제 납부한 이자 합계.

    30년 대출 / 5년 보유 시 5년치 이자만 계산.
    (매도 시 잔여 원금은 매도 대금에서 상환되므로 수익 계산에 미포함)
    """
    if loan_amount <= 0:
        return 0

    r = annual_interest_rate / 100 / 12
    n = loan_years * 12
    k = min(holding_years * 12, n)

    if repayment_type == "equal_payment":
        if r == 0:
            return 0
        M = loan_amount * r * (1 + r) ** n / ((1 + r) ** n - 1)
        remaining = loan_amount * (1 + r) ** k - M * ((1 + r) ** k - 1) / r
        principal_repaid = loan_amount - remaining
        return round(M * k - principal_repaid)

    if repayment_type == "equal_principal":
        principal_per_month = loan_amount / n
        return round(sum(
            (loan_amount - principal_per_month * i) * r
            for i in range(k)
        ))

    if repayment_type == "interest_only":
        return round(loan_amount * r * k)

    raise ValueError(f"알 수 없는 상환 방식: {repayment_type}")


def calc_loan_summary(
    loan_amount: int,
    annual_interest_rate: float,
    loan_years: int,
    repayment_type: str = "equal_payment",
) -> LoanSummary:
    """대출 요약 (월 상환액·총 상환액·총 이자)."""
    if loan_amount <= 0:
        return LoanSummary(monthly_payment=0, total_repayment=0, total_interest=0)

    r = annual_interest_rate / 100 / 12
    n = loan_years * 12
    monthly = calc_monthly_payment(loan_amount, annual_interest_rate, loan_years, repayment_type)

    if repayment_type == "equal_payment":
        total_repayment = monthly * n
        total_interest  = total_repayment - loan_amount

    elif repayment_type == "equal_principal":
        principal_per_month = loan_amount / n
        total_interest = sum(
            (loan_amount - principal_per_month * i) * r
            for i in range(n)
        )
        total_repayment = loan_amount + round(total_interest)
        total_interest  = round(total_interest)

    elif repayment_type == "interest_only":
        total_interest  = round(loan_amount * r * n)
        total_repayment = loan_amount + total_interest

    else:
        raise ValueError(f"알 수 없는 상환 방식: {repayment_type}")

    return LoanSummary(
        monthly_payment = monthly,
        total_repayment = round(total_repayment),
        total_interest  = round(total_interest),
    )


# ─────────────────────────────────────────
#  현금흐름
# ─────────────────────────────────────────

def calc_cash_flow(
    rent_fee: int | None,
    monthly_payment: int,
    monthly_management_fee: int | None,
) -> CashFlowSummary:
    """
    월 현금흐름 계산.

    전세의 경우 rent_fee=None → 임대 수입 0으로 계산.
    """
    income   = rent_fee or 0
    mgmt_fee = monthly_management_fee or 0
    net      = income - monthly_payment - mgmt_fee

    return CashFlowSummary(
        monthly_rental_income  = income,
        monthly_loan_payment   = monthly_payment,
        monthly_management_fee = mgmt_fee,
        monthly_net            = net,
    )


# ─────────────────────────────────────────
#  미래 예상 매도가
# ─────────────────────────────────────────

def calc_expected_sale_price(
    purchase_price: int,
    annual_growth_rate: float,
    holding_years: int,
) -> int:
    """복리 적용 예상 매도가."""
    return round(purchase_price * (1 + annual_growth_rate / 100) ** holding_years)


# ─────────────────────────────────────────
#  시나리오 수익성 계산
# ─────────────────────────────────────────

def calc_scenario(
    purchase_price: int,
    equity: int,
    annual_growth_rate: float,
    holding_years: int,
    total_acquisition_cost: int,
    total_interest: int,
    rent_fee: int | None,
    rent_deposit: int | None,
    jeonse_opportunity_rate: float = 3.5,
    owned_homes: int = 1,
    official_price: int = 0,
    vacancy_rate: float = 0.0,
    residence_years: int | None = None,
) -> ScenarioResult:
    """
    단일 성장률 시나리오 수익성 계산 (세후).

    세전 순손익 = 시세차익 + 총 임대 수입 − 총 이자 − 취득 비용
    세후 순손익 = 세전 − 양도소득세 − 보유세(재산세+종부세) − 매도 중개보수
    자기자본 수익률 = 세후 순손익 / equity × 100

    - 월세는 공실률(vacancy_rate %)을 차감한다.
    - 전세는 보증금 기회수익률로 등가 임대 소득을 산정한다.
    - official_price=0 이면 보유세를 계산하지 않는다 (호출측에서 추정치 주입).
    - residence_years=None: 임대 중이면 0, 아니면 실거주로 간주(보유=거주).
    - equity ≤ 0 (무자본 갭투자): ROI 정의 불가 → infinite_leverage 플래그.
    """
    expected_price = calc_expected_sale_price(purchase_price, annual_growth_rate, holding_years)
    capital_gain   = expected_price - purchase_price

    # 총 임대 수입
    is_rental = bool(rent_fee or rent_deposit)
    if rent_fee:
        annual_rent  = round(rent_fee * 12 * (1 - vacancy_rate / 100))
        total_rental = annual_rent * holding_years
    elif rent_deposit:
        # 전세: 보증금을 시중 금리로 운용했을 때의 등가 임대 소득 (공실 무관)
        annual_rent  = round(rent_deposit * jeonse_opportunity_rate / 100)
        total_rental = annual_rent * holding_years
    else:
        annual_rent  = 0
        total_rental = 0

    rental_yield = round(annual_rent / purchase_price * 100, 2) if purchase_price > 0 else 0.0

    # ── 세금·매도비용 (tax_rules) ──
    sale_brokerage = calc_brokerage_fee(expected_price)

    # 보유세: 공시가격도 시나리오 성장률로 상승한다고 가정, 연도별 합산
    holding_tax_total = 0
    if official_price > 0:
        g = annual_growth_rate / 100
        for y in range(1, holding_years + 1):
            yearly_official = round(official_price * (1 + g) ** y)
            holding_tax_total += calc_annual_holding_tax(yearly_official, owned_homes)["total"]

    # 양도세: 필요경비 = 취득비용 + 매도 중개보수
    if residence_years is None:
        residence_years = 0 if is_rental else holding_years
    cgt = calc_capital_gains_tax(
        purchase_price, expected_price, holding_years,
        owned_homes=owned_homes,
        expenses=total_acquisition_cost + sale_brokerage,
        residence_years=residence_years,
    )

    pre_tax_profit = capital_gain + total_rental - total_interest - total_acquisition_cost
    net_profit     = pre_tax_profit - cgt["tax"] - holding_tax_total - sale_brokerage

    # ── 수익률 (무자본 갭투자 왜곡 방지) ──
    if equity <= 0:
        equity_roi, annual_roi, infinite = 0.0, 0.0, True
    else:
        infinite   = False
        equity_roi = round(net_profit / equity * 100, 2)
        total_value = equity + net_profit
        if holding_years > 0 and total_value > 0:
            annual_roi = round((math.pow(total_value / equity, 1 / holding_years) - 1) * 100, 2)
        elif total_value <= 0:
            annual_roi = -100.0  # 원금 전액 손실 (CAGR 정의 불가)
        else:
            annual_roi = 0.0

    return ScenarioResult(
        annual_growth_rate  = round(annual_growth_rate, 2),
        expected_sale_price = expected_price,
        capital_gain        = capital_gain,
        total_rental_income = total_rental,
        net_profit          = net_profit,
        equity_roi          = equity_roi,
        annual_equity_roi   = annual_roi,
        rental_yield        = rental_yield,
        pre_tax_profit      = pre_tax_profit,
        capital_gains_tax   = cgt["tax"],
        holding_tax_total   = holding_tax_total,
        sale_brokerage_fee  = sale_brokerage,
        cgt_note            = cgt["note"],
        infinite_leverage   = infinite,
    )


# ─────────────────────────────────────────
#  공개 인터페이스
# ─────────────────────────────────────────

def run_simulation(inp: SimulationInput) -> SimulationResult:
    """
    SimulationInput → SimulationResult 변환.

    모든 계산은 순수 함수이며 외부 API를 호출하지 않는다.
    """
    # 취득 비용
    acq = calc_total_acquisition_cost(inp.purchase_price, inp.property_type, inp.owned_homes)

    # 필요 현금 / 실투자금
    required_cash = inp.purchase_price - inp.loan_amount + acq.total
    jeonse        = inp.rent_deposit or 0
    equity        = required_cash - jeonse
    # equity < 0: 전세 레버리지가 취득비용을 초과 → 무자본 투자 케이스, 계산은 유지

    # 대출 요약
    loan = calc_loan_summary(
        inp.loan_amount,
        inp.annual_interest_rate,
        inp.loan_years,
        inp.repayment_type,
    )

    # 현금흐름
    cash_flow = calc_cash_flow(
        inp.rent_fee,
        loan.monthly_payment,
        inp.monthly_management_fee,
    )

    # 보유 기간 동안의 실제 이자 (전체 대출 기간 이자가 아님)
    interest_during_holding = calc_interest_during_holding(
        inp.loan_amount,
        inp.annual_interest_rate,
        inp.loan_years,
        inp.holding_years,
        inp.repayment_type,
    )

    # ── 보유세용 공시가격 (미입력 시 시세 × 현실화율 추정) ──
    is_housing = not any(kw in (inp.property_type or "") for kw in _COMMERCIAL_TYPES)
    if inp.official_price:
        official_price, official_estimated = inp.official_price, False
    elif is_housing:
        official_price, official_estimated = estimate_official_price(inp.purchase_price), True
    else:
        official_price, official_estimated = 0, False   # 비주거: 보유세 간이 계산 제외

    # 시나리오 공통 인자
    _scenario_kwargs = dict(
        purchase_price         = inp.purchase_price,
        equity                 = equity,
        holding_years          = inp.holding_years,
        total_acquisition_cost = acq.total,
        total_interest         = interest_during_holding,
        rent_fee               = inp.rent_fee,
        rent_deposit           = inp.rent_deposit,
        jeonse_opportunity_rate = inp.jeonse_opportunity_rate,
        owned_homes            = inp.owned_homes if is_housing else 99,   # 비주거: 양도세 일반과세 경로
        official_price         = official_price,
        vacancy_rate           = inp.vacancy_rate,
        residence_years        = inp.residence_years,
    )

    base_rate = inp.expected_annual_growth_rate
    spread    = inp.scenario_spread
    scenario_base = calc_scenario(annual_growth_rate=base_rate,          **_scenario_kwargs)
    scenario_bull = calc_scenario(annual_growth_rate=base_rate + spread, **_scenario_kwargs)
    scenario_bear = calc_scenario(annual_growth_rate=base_rate - spread, **_scenario_kwargs)

    # ── 손익분기 상승률 (세후 순손익 = 0인 연 상승률, 이분탐색) ──
    def _profit_at(growth: float) -> int:
        return calc_scenario(annual_growth_rate=growth, **_scenario_kwargs).net_profit

    breakeven: float | None = None
    lo, hi = -20.0, 50.0
    if _profit_at(lo) < 0 <= _profit_at(hi):
        for _ in range(40):
            mid = (lo + hi) / 2
            if _profit_at(mid) < 0:
                lo = mid
            else:
                hi = mid
        breakeven = round(hi, 2)

    # ── 금리 × 성장률 민감도 (3×3, 세후 연환산 ROI) ──
    sensitivity: list[RateSensitivityCell] = []
    for g in (base_rate - spread, base_rate, base_rate + spread):
        for r_delta in (-1.0, 0.0, 1.0):
            rate = max(0.0, inp.annual_interest_rate + r_delta)
            interest_r = calc_interest_during_holding(
                inp.loan_amount, rate, inp.loan_years,
                inp.holding_years, inp.repayment_type,
            )
            cell = calc_scenario(annual_growth_rate=g,
                                 **{**_scenario_kwargs, "total_interest": interest_r})
            sensitivity.append(RateSensitivityCell(
                growth_rate       = round(g, 2),
                interest_rate     = round(rate, 2),
                annual_equity_roi = cell.annual_equity_roi,
                net_profit        = cell.net_profit,
            ))

    # ── LTV·DSR 검증 ──
    ltv = check_ltv(inp.purchase_price, inp.loan_amount,
                    owned_homes=inp.owned_homes, adjusted_area=inp.adjusted_area)
    fc = FinanceCheck(
        ltv          = ltv["ltv"],
        ltv_limit    = ltv["limit"],
        ltv_exceeded = ltv["exceeded"],
        ltv_max_loan = ltv["max_loan_amount"],
    )
    if inp.annual_income and inp.loan_amount > 0:
        dsr = check_dsr(inp.loan_amount, inp.annual_interest_rate, inp.loan_years,
                        inp.annual_income, inp.existing_loan_annual_payment)
        fc.dsr                = dsr["dsr"]
        fc.dsr_limit          = dsr["limit"]
        fc.dsr_exceeded       = dsr["exceeded"]
        fc.stress_rate        = dsr["stress_rate"]
        fc.dsr_annual_payment = dsr["annual_payment"]
        fc.dsr_max_loan       = dsr["max_loan_amount"]

    return SimulationResult(
        purchase_price   = inp.purchase_price,
        loan_amount      = inp.loan_amount,
        owned_homes      = inp.owned_homes,
        home_count_basis = "after_purchase",
        required_cash    = required_cash,
        equity           = equity,
        acquisition_cost = acq,
        loan             = loan,
        cash_flow        = cash_flow,
        scenario_base    = scenario_base,
        scenario_bull    = scenario_bull,
        scenario_bear    = scenario_bear,
        tax_rules_as_of          = TAX_RULES_AS_OF,
        official_price_used      = official_price,
        official_price_estimated = official_estimated,
        finance_check            = fc,
        breakeven_growth_rate    = breakeven,
        rate_sensitivity         = sensitivity,
    )
