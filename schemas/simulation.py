"""
simulation.py — 부동산 시뮬레이션 입출력 스키마

금액 단위: 원 (int)
비율 단위: % (float, 예: 4.0 = 4%)
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ─────────────────────────────────────────
#  입력
# ─────────────────────────────────────────

class SimulationInput(BaseModel):
    """시뮬레이션 입력 파라미터"""

    # 매수 조건
    purchase_price: int = Field(..., gt=0, description="매수가 (원)")
    cash_available: Optional[int] = Field(None, ge=0, description="보유 현금 (원). None이면 purchase_price − loan_amount")
    loan_amount: int = Field(0, ge=0, description="대출금 (원)")

    # 대출 조건
    annual_interest_rate: float = Field(4.0, ge=0.0, le=30.0, description="연이율 (%)")
    loan_years: int = Field(30, ge=1, le=50, description="대출 기간 (년)")
    repayment_type: Literal[
        "equal_payment",    # 원리금균등상환
        "equal_principal",  # 원금균등상환
        "interest_only",    # 만기일시상환
    ] = "equal_payment"

    # 보유·매도 계획
    holding_years: int = Field(3, ge=1, le=50, description="보유 기간 (년)")
    expected_annual_growth_rate: float = Field(0.0, ge=-20.0, le=50.0, description="연간 예상 상승률 (%)")

    # 임대 수입
    rent_deposit: Optional[int] = Field(None, ge=0, description="전세 보증금 (원)")
    rent_fee: Optional[int] = Field(None, ge=0, description="월세 (원)")
    monthly_management_fee: Optional[int] = Field(None, ge=0, description="월 관리비 (원)")

    # 물건 정보 (취득세율 결정)
    property_type: Optional[str] = Field("아파트", description="매물 유형 (아파트·오피스텔·상가·토지 등)")
    owned_homes: int = Field(1, ge=1, le=100, description="취득하는 주택을 포함한 취득 후 주택 수. 무주택자의 첫 주택 취득은 1")

    # 세금 산정 (양도세·보유세)
    official_price: Optional[int] = Field(None, ge=0, description="공시가격 (원, 보유세 산정용). None이면 시세×현실화율로 추정")
    residence_years: Optional[int] = Field(None, ge=0, description="거주 연수 (1주택 장특공 거주분). None이면 임대 여부로 자동 판단")
    vacancy_rate: float = Field(5.0, ge=0.0, le=50.0, description="월세 공실률 (%, 기본 5%)")
    adjusted_area: bool = Field(False, description="조정대상지역 여부 (LTV·취득세 중과)")

    # DSR 검증 (선택)
    annual_income: Optional[int] = Field(None, ge=0, description="연소득 (원). 입력 시 DSR 검증 수행")
    existing_loan_annual_payment: int = Field(0, ge=0, description="기존 대출 연 원리금 상환액 (원)")

    # 시나리오 설정
    scenario_spread: float = Field(5.0, ge=1.0, le=20.0, description="강세/약세 시나리오 편차 (%p, 기본 ±5%p)")
    jeonse_opportunity_rate: float = Field(3.5, ge=0.0, le=20.0, description="전세 보증금 기회수익률 (%, 기본 3.5% — 정기예금 기준)")

    @model_validator(mode="after")
    def _validate_loan(self) -> "SimulationInput":
        if self.loan_amount >= self.purchase_price:
            raise ValueError("loan_amount는 purchase_price보다 작아야 합니다.")
        if self.rent_deposit and self.rent_fee:
            raise ValueError("rent_deposit과 rent_fee는 동시에 입력할 수 없습니다.")
        if self.rent_deposit and self.rent_deposit >= self.purchase_price:
            raise ValueError("rent_deposit은 purchase_price보다 작아야 합니다.")
        return self


# ─────────────────────────────────────────
#  출력 — 중간 집계 모델
# ─────────────────────────────────────────

class AcquisitionCost(BaseModel):
    """취득 시 발생 비용"""
    acquisition_tax: int    # 취득세 (원)
    brokerage_fee: int      # 중개보수 (원)
    other_cost: int         # 기타 비용 (등기·인지세 등, 원)
    total: int              # 합계 (원)


class LoanSummary(BaseModel):
    """대출 요약"""
    monthly_payment: int    # 첫 달 월 상환액 (원)
    total_repayment: int    # 총 상환액 (원) = 원금 + 이자
    total_interest: int     # 총 이자 납부액 (원)


class CashFlowSummary(BaseModel):
    """월 현금흐름 요약"""
    monthly_rental_income: int      # 월 임대 수입 (원)
    monthly_loan_payment: int       # 월 대출 상환 (원)
    monthly_management_fee: int     # 월 관리비 (원)
    monthly_net: int                # 순 월 현금흐름 = 수입 − 상환 − 관리비 (원)


class ScenarioResult(BaseModel):
    """단일 시나리오 수익성 결과 (net_profit은 세후)"""
    annual_growth_rate: float       # 적용된 연간 상승률 (%)
    expected_sale_price: int        # 보유 기간 후 예상 매도가 (원)
    capital_gain: int               # 시세 차익 = 매도가 − 매수가 (원)
    total_rental_income: int        # 보유 기간 총 임대 수입 (공실률 반영, 원)
    net_profit: int                 # 세후 순손익 (원)
    equity_roi: float               # 자기자본 수익률 (%, 세후)
    annual_equity_roi: float        # 연환산 자기자본 수익률 (%, 세후)
    rental_yield: float             # 연 임대 수익률 = 연 임대수입 / 매수가 × 100 (%)

    # 세금·매도비용 내역 (tax_rules.py 기준)
    pre_tax_profit: int = 0         # 세전 순손익 (원)
    capital_gains_tax: int = 0      # 양도소득세 (지방소득세 포함, 원)
    holding_tax_total: int = 0      # 보유 기간 재산세+종부세 합계 (원)
    sale_brokerage_fee: int = 0     # 매도 중개보수 (원)
    cgt_note: str = ""              # 양도세 적용 근거 (비과세·장특공 등)
    infinite_leverage: bool = False # 실투자금 ≤ 0 (무자본 갭투자) — ROI 정의 불가


class FinanceCheck(BaseModel):
    """LTV·DSR 규제 검증 (tax_rules.py 규정 테이블 기준)"""
    ltv: float                      # 신청 LTV 비율
    ltv_limit: float                # 규제 한도
    ltv_exceeded: bool
    ltv_max_loan: int               # LTV 한도 내 최대 대출액 (원)

    dsr: Optional[float] = None     # 연소득 입력 시에만
    dsr_limit: float = 0.40
    dsr_exceeded: bool = False
    stress_rate: Optional[float] = None       # 스트레스 금리 (%)
    dsr_annual_payment: Optional[int] = None  # 스트레스 기준 연 상환액 (원)
    dsr_max_loan: Optional[int] = None        # DSR 한도 내 최대 대출액 (원)


class RateSensitivityCell(BaseModel):
    """성장률 × 금리 민감도 셀"""
    growth_rate: float
    interest_rate: float
    annual_equity_roi: float
    net_profit: int


# ─────────────────────────────────────────
#  출력 — 최종 결과
# ─────────────────────────────────────────

class SimulationResult(BaseModel):
    """시뮬레이션 최종 결과"""

    # 입력 요약 (검증용 echo)
    purchase_price: int
    loan_amount: int
    owned_homes: int | None = None
    home_count_basis: Literal["after_purchase"] | None = None
    equity: int             # 실투자금 = 필요 현금 − 전세 보증금 (원)
    required_cash: int      # 필요 현금 = 매수가 − 대출 + 취득 비용 (원)

    # 취득 비용
    acquisition_cost: AcquisitionCost

    # 대출
    loan: LoanSummary

    # 현금흐름
    cash_flow: CashFlowSummary

    # 시나리오
    scenario_base: ScenarioResult   # 입력 growth_rate 그대로
    scenario_bull: ScenarioResult   # growth_rate + 5%p
    scenario_bear: ScenarioResult   # growth_rate − 5%p

    # 세금·규제·민감도 (tax_rules.py)
    tax_rules_as_of: str = ""                       # 세법·규정 기준일
    official_price_used: int = 0                    # 보유세 산정에 쓴 공시가격 (원)
    official_price_estimated: bool = False          # True면 시세×현실화율 추정치
    finance_check: Optional[FinanceCheck] = None    # LTV·DSR 검증
    breakeven_growth_rate: Optional[float] = None   # 세후 손익분기 연 상승률 (%)
    rate_sensitivity: list[RateSensitivityCell] = []  # 성장률×금리 3×3
