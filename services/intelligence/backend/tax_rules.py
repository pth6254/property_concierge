"""Kotlin 간이 세금·규제 계산 계약. 기준일은 정책 버전이며 최신 법률 검증을 뜻하지 않는다."""
from __future__ import annotations
from backend.services.core_calculations import core_calculation

TAX_RULES_AS_OF = "2026-01-01"

@core_calculation()
def calc_capital_gains_tax(purchase_price: int, sale_price: int, holding_years: int, owned_homes: int=1, expenses: int=0, residence_years: int=0) -> dict:
    ...

@core_calculation()
def calc_annual_holding_tax(official_price: int, owned_homes: int=1) -> dict:
    ...

@core_calculation()
def estimate_official_price(market_price: int) -> int:
    ...

@core_calculation()
def calc_gift_tax(gift_value: int, relation: str='직계존속', prior_gifts_10yr: int=0, marriage_deduction: bool=False) -> dict:
    ...

@core_calculation()
def calc_inheritance_tax(estate_value: int, has_spouse: bool=True, spouse_share: int=0, debts: int=0) -> dict:
    ...

@core_calculation()
def check_dsr(loan_amount: int, annual_interest_rate: float, loan_years: int, annual_income: int, existing_annual_debt_payment: int=0) -> dict:
    ...

@core_calculation()
def check_ltv(purchase_price: int, loan_amount: int, owned_homes: int=1, adjusted_area: bool=False) -> dict:
    ...
