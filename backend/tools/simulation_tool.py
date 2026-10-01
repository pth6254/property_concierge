"""Kotlin 금융 계산 계약. Python에 중복 수식이나 장애 폴백을 두지 않는다."""
from __future__ import annotations
from backend.services.core_calculations import calculate, core_calculation
from schemas.simulation import AcquisitionCost, LoanSummary, CashFlowSummary, ScenarioResult, SimulationInput, SimulationResult


@core_calculation()
def calc_acquisition_tax(purchase_price: int, property_type: str | None, owned_homes: int=1) -> int:
    ...

@core_calculation()
def calc_brokerage_fee(purchase_price: int) -> int:
    ...

@core_calculation()
def calc_other_acquisition_cost(purchase_price: int) -> int:
    ...

@core_calculation(AcquisitionCost)
def calc_total_acquisition_cost(purchase_price: int, property_type: str | None, owned_homes: int=1) -> AcquisitionCost:
    ...

@core_calculation()
def calc_monthly_payment(loan_amount: int, annual_interest_rate: float, loan_years: int, repayment_type: str='equal_payment') -> int:
    ...

@core_calculation()
def calc_interest_during_holding(loan_amount: int, annual_interest_rate: float, loan_years: int, holding_years: int, repayment_type: str='equal_payment') -> int:
    ...

@core_calculation(LoanSummary)
def calc_loan_summary(loan_amount: int, annual_interest_rate: float, loan_years: int, repayment_type: str='equal_payment') -> LoanSummary:
    ...

@core_calculation(CashFlowSummary)
def calc_cash_flow(rent_fee: int | None, monthly_payment: int, monthly_management_fee: int | None) -> CashFlowSummary:
    ...

@core_calculation()
def calc_expected_sale_price(purchase_price: int, annual_growth_rate: float, holding_years: int) -> int:
    ...

@core_calculation(ScenarioResult)
def calc_scenario(purchase_price: int, equity: int, annual_growth_rate: float, holding_years: int, total_acquisition_cost: int, total_interest: int, rent_fee: int | None, rent_deposit: int | None, jeonse_opportunity_rate: float=3.5, owned_homes: int=1, official_price: int=0, vacancy_rate: float=0.0, residence_years: int | None=None) -> ScenarioResult:
    ...
def run_simulation(inp: SimulationInput) -> SimulationResult:
    """
    SimulationInput → SimulationResult 변환.

    Kotlin 결과의 입력 조건과 계산 버전을 검증한다.
    """
    from backend.services.core_calculations import calculate
    remote = calculate("simulation", inp.model_dump(mode="json"))
    from pydantic import ValidationError
    from fastapi import HTTPException
    try:
        validated = SimulationResult.model_validate(remote)
    except ValidationError:
        raise HTTPException(503, "계산 결과의 형식을 확인하지 못했습니다") from None
    if (validated.purchase_price != inp.purchase_price or validated.loan_amount != inp.loan_amount
            or validated.owned_homes != inp.owned_homes or validated.calculator_engine != "kotlin-spring"
            or validated.calculation_version != "finance-v1"):
        raise HTTPException(503, "계산 결과와 입력 조건이 일치하지 않습니다")
    return validated
