"""
simulation_service.py — 부동산 투자 시뮬레이션 서비스 (Phase 4-2)

계산 엔진(simulation_tool)을 감싸는 서비스 레이어.

공개 함수:
  run_property_simulation(data)          dict | SimulationInput → SimulationResult
  listing_to_simulation_input(listing)   PropertyListing | dict → SimulationInput
  generate_simulation_report(result, inp) SimulationResult → 마크다운 str
"""

from __future__ import annotations

import logging
import os
import sys
from decimal import Decimal
from typing import Any, Optional

_SVC_DIR      = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_SVC_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schemas.simulation import SimulationInput, SimulationResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
#  포맷 헬퍼
# ─────────────────────────────────────────

def _fmt_won(won: int | None) -> str:
    if won is None:
        return "—"
    sign = "-" if won < 0 else ""
    return f"{sign}{abs(won):,}원"


def _fmt_pct(pct: float | None, decimals: int = 2) -> str:
    """float → '3.50%' 형태"""
    if pct is None:
        return "—"
    return f"{pct:+.{decimals}f}%" if pct != 0 else f"0.{'0'*decimals}%"


def _fmt_pct_plain(pct: float | None, decimals: int = 2) -> str:
    """부호 없는 퍼센트 표기"""
    if pct is None:
        return "—"
    return f"{pct:.{decimals}f}%"


def _sign_label(value: int | float) -> str:
    """양수 → ▲, 음수 → ▼, 0 → ─"""
    if value > 0:
        return "▲"
    if value < 0:
        return "▼"
    return "─"


# ─────────────────────────────────────────
#  PropertyListing → SimulationInput 변환
# ─────────────────────────────────────────

_PROP_TYPE_MAP = {
    "주거용": "아파트",
    "상업용": "상가",
    "업무용": "오피스",
    "산업용": "공장",
    "토지":   "토지",
}


def build_simulation_input_from_listing(
    listing: Any,
    overrides: dict | None = None,
) -> SimulationInput:
    """
    PropertyListing 또는 dict + overrides dict → SimulationInput.

    overrides는 listing_to_simulation_input의 키워드 인자와 동일한 이름으로 전달한다.
    예: {"loan_ratio": 0.6, "annual_interest_rate": 3.5, "holding_years": 5}
    """
    return listing_to_simulation_input(listing, **(overrides or {}))


def listing_to_simulation_input(
    listing: Any,
    loan_ratio: float = 0.5,
    annual_interest_rate: float = 4.0,
    loan_years: int = 30,
    repayment_type: str = "equal_payment",
    holding_years: int = 3,
    expected_annual_growth_rate: float = 0.0,
    rent_fee: Optional[int] = None,
    monthly_management_fee: Optional[int] = None,
) -> SimulationInput:
    """
    PropertyListing 객체 또는 dict → SimulationInput 변환 편의 함수.

    loan_ratio: 매수가 대비 대출 비율 (기본 50%).
    PropertyListing.deposit_price가 있으면 임대 보증금으로 사용.
    rent_fee 인자가 주어지면 deposit_price 대신 월 임대료 모드로 설정.
    """
    if isinstance(listing, dict):
        purchase_price  = listing.get("asking_price", 0)
        rent_deposit    = listing.get("deposit_price")
        mgmt_fee        = listing.get("maintenance_fee") or monthly_management_fee
        ptype_raw       = listing.get("property_type", "주거용")
    else:
        purchase_price  = getattr(listing, "asking_price", 0)
        rent_deposit    = getattr(listing, "deposit_price", None)
        mgmt_fee        = getattr(listing, "maintenance_fee", None) or monthly_management_fee
        ptype_raw       = getattr(listing, "property_type", "주거용")

    property_type = _PROP_TYPE_MAP.get(ptype_raw, ptype_raw)
    loan_amount   = int(Decimal(purchase_price) * Decimal(str(loan_ratio)))

    # 월세 모드이면 jeonse 무시
    if rent_fee is not None:
        rent_deposit = None

    return SimulationInput(
        purchase_price              = purchase_price,
        loan_amount                 = loan_amount,
        annual_interest_rate        = annual_interest_rate,
        loan_years                  = loan_years,
        repayment_type              = repayment_type,
        holding_years               = holding_years,
        expected_annual_growth_rate = expected_annual_growth_rate,
        rent_deposit              = rent_deposit if not rent_fee else None,
        rent_fee                = rent_fee,
        monthly_management_fee      = mgmt_fee,
        property_type               = property_type,
    )


# ─────────────────────────────────────────
#  공개 실행 인터페이스
# ─────────────────────────────────────────

def run_property_simulation(
    data: dict | SimulationInput,
) -> SimulationResult:
    """
    dict 또는 SimulationInput → SimulationResult.

    dict가 전달되면 SimulationInput으로 변환한 뒤 계산 엔진으로 전달한다.
    Pydantic 유효성 검사 실패 시 ValidationError가 전파된다.
    """
    from tools.simulation_tool import run_simulation

    if isinstance(data, dict):
        inp = SimulationInput(**data)
    else:
        inp = data

    logger.debug(
        "[simulation_service] 시뮬레이션 실행 — 매수가 %s, 대출 %s",
        _fmt_won(inp.purchase_price),
        _fmt_won(inp.loan_amount),
    )
    return run_simulation(inp)


# ─────────────────────────────────────────
#  마크다운 리포트 생성
# ─────────────────────────────────────────

def generate_simulation_report(
    result: SimulationResult,
    inp: Optional[SimulationInput] = None,
) -> str:
    """
    SimulationResult → 마크다운 리포트 문자열.

    inp가 있으면 헤더에 입력 조건도 표시한다.
    """
    lines: list[str] = []

    # ── 헤더 ──────────────────────────────────────────────────────────────
    lines.append("# 부동산 투자 시뮬레이션 리포트")
    lines.append("")
    lines.append("> ⚠️ 이 리포트는 간이 계산 결과입니다. 실제 세율·대출 조건은 달라질 수 있습니다.")
    lines.append("")

    # ── 입력 조건 요약 ────────────────────────────────────────────────────
    if inp:
        lines.append("## 입력 조건")
        lines.append("")
        _REPAYMENT_LABEL = {
            "equal_payment":   "원리금균등상환",
            "equal_principal": "원금균등상환",
            "interest_only":   "만기일시상환",
        }
        rows = [
            ("매수가",         _fmt_won(inp.purchase_price)),
            ("대출금",         _fmt_won(inp.loan_amount)),
            ("연이율",         _fmt_pct_plain(inp.annual_interest_rate)),
            ("대출 기간",      f"{inp.loan_years}년"),
            ("상환 방식",      _REPAYMENT_LABEL.get(inp.repayment_type, inp.repayment_type)),
            ("보유 기간",      f"{inp.holding_years}년"),
            ("예상 연 상승률", _fmt_pct_plain(inp.expected_annual_growth_rate)),
            ("매물 유형",      inp.property_type or "—"),
            ("취득 후 주택 수", f"{inp.owned_homes}주택 (이번 취득 포함)"),
        ]
        if inp.rent_deposit:
            rows.append(("전세 보증금", _fmt_won(inp.rent_deposit)))
        if inp.assumed_deposit:
            rows.append(("승계 임차 보증금", _fmt_won(inp.assumed_deposit)))
        if inp.rent_fee:
            rows.append(("월세", _fmt_won(inp.rent_fee)))
        if inp.monthly_management_fee:
            rows.append(("월 관리비", _fmt_won(inp.monthly_management_fee)))

        lines.append("| 항목 | 값 |")
        lines.append("|------|-----|")
        for k, v in rows:
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # ── 취득 비용 ─────────────────────────────────────────────────────────
    lines.append("## 취득 비용")
    lines.append("")
    acq = result.acquisition_cost
    lines.append("| 항목 | 금액 |")
    lines.append("|------|------|")
    lines.append(f"| 취득세 (간이) | {_fmt_won(acq.acquisition_tax)} |")
    lines.append(f"| 중개보수 (간이) | {_fmt_won(acq.brokerage_fee)} |")
    lines.append(f"| 기타 (등기·인지세) | {_fmt_won(acq.other_cost)} |")
    lines.append(f"| **합계** | **{_fmt_won(acq.total)}** |")
    lines.append("")

    # ── 자기자본 ──────────────────────────────────────────────────────────
    lines.append("## 필요 자금")
    lines.append("")
    lines.append("| 항목 | 금액 |")
    lines.append("|------|------|")
    lines.append(f"| 매수가 | {_fmt_won(result.purchase_price)} |")
    lines.append(f"| 대출금 | −{_fmt_won(result.loan_amount)} |")
    lines.append(f"| 취득 비용 | +{_fmt_won(acq.total)} |")
    if inp and inp.assumed_deposit:
        lines.append(f"| 임차 보증금 승계 (차감) | −{_fmt_won(inp.assumed_deposit)} |")
    lines.append(f"| **필요 현금 합계** | **{_fmt_won(result.required_cash)}** |")
    if inp and inp.rent_deposit:
        lines.append(f"| 전세 보증금 (차감) | −{_fmt_won(inp.rent_deposit)} |")
        lines.append(f"| **실투자금** | **{_fmt_won(result.equity)}** |")
    lines.append("")

    # ── 대출 ──────────────────────────────────────────────────────────────
    if result.loan_amount > 0:
        lines.append("## 대출 정보")
        lines.append("")
        loan = result.loan
        lines.append("| 항목 | 금액 |")
        lines.append("|------|------|")
        lines.append(f"| 월 상환액 | {_fmt_won(loan.monthly_payment)} |")
        lines.append(f"| 총 상환액 | {_fmt_won(loan.total_repayment)} |")
        lines.append(f"| 총 이자 | {_fmt_won(loan.total_interest)} |")
        lines.append("")

    # ── 월 현금흐름 ───────────────────────────────────────────────────────
    lines.append("## 월 현금흐름")
    lines.append("")
    cf = result.cash_flow
    net_sign = _sign_label(cf.monthly_net)
    lines.append("| 항목 | 금액 |")
    lines.append("|------|------|")
    if cf.monthly_rental_income:
        lines.append(f"| 월 임대 수입 | +{_fmt_won(cf.monthly_rental_income)} |")
    lines.append(f"| 월 대출 상환 | −{_fmt_won(cf.monthly_loan_payment)} |")
    if cf.monthly_management_fee:
        lines.append(f"| 월 관리비 | −{_fmt_won(cf.monthly_management_fee)} |")
    lines.append(f"| **순 월 현금흐름** | **{net_sign} {_fmt_won(abs(cf.monthly_net))}** |")
    lines.append("")

    # ── 시나리오 비교 ─────────────────────────────────────────────────────
    lines.append("## 시나리오 비교")
    lines.append("")
    lines.append("| 지표 | 비관 시나리오 | 기본 시나리오 | 낙관 시나리오 |")
    lines.append("|------|-------------|-------------|-------------|")

    sb = result.scenario_bear
    sm = result.scenario_base
    su = result.scenario_bull

    def _row(label: str, getter):
        return (
            f"| {label} "
            f"| {getter(sb)} "
            f"| {getter(sm)} "
            f"| {getter(su)} |"
        )

    lines.append(_row("연 상승률",      lambda s: _fmt_pct_plain(s.annual_growth_rate)))
    lines.append(_row("예상 매도가",    lambda s: _fmt_won(s.expected_sale_price)))
    lines.append(_row("시세 차익",      lambda s: f"{_sign_label(s.capital_gain)} {_fmt_won(abs(s.capital_gain))}"))
    if sm.total_rental_income:
        lines.append(_row("총 임대 수입",  lambda s: _fmt_won(s.total_rental_income)))
    lines.append(_row("세전 순손익",    lambda s: f"{_sign_label(s.pre_tax_profit)} {_fmt_won(abs(s.pre_tax_profit))}"))
    lines.append(_row("양도소득세",     lambda s: f"−{_fmt_won(s.capital_gains_tax)}"))
    lines.append(_row("보유세 합계",    lambda s: f"−{_fmt_won(s.holding_tax_total)}"))
    lines.append(_row("매도 중개보수",  lambda s: f"−{_fmt_won(s.sale_brokerage_fee)}"))
    lines.append(_row("**세후 순손익**", lambda s: f"**{_sign_label(s.net_profit)} {_fmt_won(abs(s.net_profit))}**"))
    lines.append(_row("자기자본 수익률", lambda s: "무한 레버리지" if s.infinite_leverage else _fmt_pct(s.equity_roi)))
    lines.append(_row("연환산 수익률",  lambda s: "—" if s.infinite_leverage else _fmt_pct(s.annual_equity_roi)))
    if sm.rental_yield:
        lines.append(_row("임대 수익률",   lambda s: _fmt_pct_plain(s.rental_yield)))
    lines.append("")

    # ── 세금 상세 ─────────────────────────────────────────────────────────
    lines.append("## 세금 상세 (기본 시나리오)")
    lines.append("")
    lines.append(f"> 세법 기준일: {result.tax_rules_as_of} · {sm.cgt_note}")
    if result.official_price_used:
        est = " (시세×현실화율 추정)" if result.official_price_estimated else ""
        lines.append(f"> 보유세 산정 공시가격: {_fmt_won(result.official_price_used)}{est}")
    lines.append("")

    # ── 대출 규제 검증 ────────────────────────────────────────────────────
    fc = result.finance_check
    if fc and result.loan_amount > 0:
        lines.append("## 대출 규제 검증 (LTV·DSR)")
        lines.append("")
        lines.append("| 항목 | 값 | 한도 | 판정 |")
        lines.append("|------|-----|------|------|")
        ltv_verdict = "❌ 초과" if fc.ltv_exceeded else "✅ 충족"
        lines.append(f"| LTV | {fc.ltv:.1%} | {fc.ltv_limit:.0%} | {ltv_verdict}"
                     f" (한도 내 최대 {_fmt_won(fc.ltv_max_loan)}) |")
        if fc.dsr is not None:
            dsr_verdict = "❌ 초과" if fc.dsr_exceeded else "✅ 충족"
            lines.append(f"| DSR (스트레스 {fc.stress_rate}%) | {fc.dsr:.1%} | {fc.dsr_limit:.0%} | {dsr_verdict}"
                         f" (한도 내 최대 {_fmt_won(fc.dsr_max_loan or 0)}) |")
        lines.append("")
        if fc.ltv_exceeded or fc.dsr_exceeded:
            lines.append("> ⚠️ **규제 한도 초과 — 이 조건의 대출은 실행이 어렵습니다.** 대출액을 줄이거나 조건을 조정하세요.")
            lines.append("")

    # ── 손익분기·민감도 ───────────────────────────────────────────────────
    if result.breakeven_growth_rate is not None:
        lines.append(f"## 손익분기 상승률: 연 {result.breakeven_growth_rate}%")
        lines.append("")
        lines.append(f"> 모든 비용·세금을 회수하려면 연 {result.breakeven_growth_rate}% 이상 상승해야 합니다.")
        lines.append("")

    if result.rate_sensitivity:
        lines.append("## 금리 × 상승률 민감도 (세후 연환산 수익률)")
        lines.append("")
        rates   = sorted({c.interest_rate for c in result.rate_sensitivity})
        growths = sorted({c.growth_rate for c in result.rate_sensitivity})
        lines.append("| 상승률 \\ 금리 | " + " | ".join(f"{r}%" for r in rates) + " |")
        lines.append("|" + "---|" * (len(rates) + 1))
        cell_map = {(c.growth_rate, c.interest_rate): c for c in result.rate_sensitivity}
        for g in growths:
            row = [f"연 {g:+.1f}%"]
            for r in rates:
                c = cell_map.get((g, r))
                row.append(_fmt_pct(c.annual_equity_roi) if c else "—")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    # ── 투자 판단 요약 ────────────────────────────────────────────────────
    lines.append("## 투자 판단 요약")
    lines.append("")
    roi   = sm.equity_roi
    aroi  = sm.annual_equity_roi

    if aroi >= 10:
        verdict = "✅ 우수한 투자 수익률 (연 10% 이상)"
    elif aroi >= 5:
        verdict = "🟡 양호한 투자 수익률 (연 5~10%)"
    elif aroi >= 0:
        verdict = "🟠 낮은 수익률 (연 0~5%) — 시세 상승 가정에 의존"
    else:
        verdict = "🔴 마이너스 수익률 — 투자 재검토 필요"

    lines.append(f"- **기본 시나리오 자기자본 수익률**: {_fmt_pct(roi)} (연환산 {_fmt_pct(aroi)})")
    lines.append(f"- **판단**: {verdict}")
    if cf.monthly_net < 0:
        lines.append(
            f"- ⚠️ **월 현금흐름 적자** {_fmt_won(abs(cf.monthly_net))} — "
            "보유 기간 동안 추가 현금 필요"
        )
    lines.append("")

    return "\n".join(lines)
