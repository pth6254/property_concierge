"""Python 분석이 사용하는 매수 조건·지역 통계 입력. 업무 CRUD 입력은 Kotlin에 있다."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator

MarketPropertyType = Literal[
    "all", "apartment", "row_house", "detached", "officetel",
    "non_residential", "industrial", "land",
]


class BuyerProfile(BaseModel):
    cash_available: int | None = Field(default=None, ge=0, le=10**15)
    emergency_reserve: int = Field(default=0, ge=0, le=10**15)
    monthly_payment_limit: int | None = Field(default=None, ge=0, le=10**12)
    annual_income: int | None = Field(default=None, ge=0, le=10**15)
    existing_loan_annual_payment: int = Field(default=0, ge=0, le=10**15)
    loan_ratio: float | None = Field(default=None, ge=0, le=0.9)
    annual_interest_rate: float | None = Field(default=None, ge=0, le=30)
    loan_years: int | None = Field(default=None, ge=1, le=50)
    owned_homes: int | None = Field(default=None, ge=1, le=100, description="취득 후 주택 수. 첫 주택 취득은 1")
    adjusted_area: bool | None = None
    min_area_sqm: float | None = Field(default=None, gt=0, le=100000)
    max_area_sqm: float | None = Field(default=None, gt=0, le=100000)
    min_build_year: int | None = Field(default=None, ge=1800, le=2100)
    max_build_year: int | None = Field(default=None, ge=1800, le=2100)
    market_months: int = Field(default=12, ge=1, le=60)
    property_types: list[Literal["apartment", "officetel", "row_house", "detached", "non_residential", "industrial", "land"]] = Field(default_factory=list, max_length=7)
    priority: Literal["cash", "monthly", "value", "liquidity", "age"] = "cash"

    @model_validator(mode="after")
    def validate_cash(self):
        if self.min_area_sqm and self.max_area_sqm and self.min_area_sqm > self.max_area_sqm:
            raise ValueError("최소 면적은 최대 면적보다 클 수 없습니다")
        if self.min_build_year and self.max_build_year and self.min_build_year > self.max_build_year:
            raise ValueError("준공연도 범위를 확인해주세요")
        if self.cash_available is not None and self.emergency_reserve > self.cash_available:
            raise ValueError("비상자금은 보유 현금보다 클 수 없습니다")
        return self


class CaseRegionCreate(BaseModel):
    region_code: str = Field(pattern=r"^\d{10}$")
    property_type: MarketPropertyType = "all"
    budget_max_won: int | None = Field(default=None, ge=0)
    months: int = Field(default=12, ge=1, le=60)
    source: Literal["market_explorer", "concierge"] = "market_explorer"
