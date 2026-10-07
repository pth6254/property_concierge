"""임대료 시나리오의 입력 계약. 고정 수식의 실행은 Spring이 담당한다."""
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class IncomeValuationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    monthly_rent_won: int = Field(ge=0, le=10**15, strict=True)
    monthly_operating_cost_min_won: int | None = Field(default=None, ge=0, le=10**15, strict=True)
    monthly_operating_cost_max_won: int | None = Field(default=None, ge=0, le=10**15, strict=True)
    cap_rate_min_pct: Decimal = Field(ge=Decimal("0.1"), le=100, decimal_places=4)
    cap_rate_max_pct: Decimal = Field(ge=Decimal("0.1"), le=100, decimal_places=4)
    asking_price_won: int | None = Field(default=None, gt=0, le=10**15, strict=True)
    valuation_unit: Literal["single_unit", "whole_building"]
    as_of_date: date

    @model_validator(mode="after")
    def consistent_ranges(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if self.as_of_date > datetime.now(ZoneInfo("Asia/Seoul")).date():
            raise ValueError("임대료 확인일은 미래일 수 없습니다")
        if self.cap_rate_min_pct > self.cap_rate_max_pct:
            raise ValueError("환원율 범위를 확인해주세요")
        low, high = self.monthly_operating_cost_min_won, self.monthly_operating_cost_max_won
        if (low is None) != (high is None) or (low is not None and high is not None and low > high):
            raise ValueError("운영비 최소·최대값을 함께 입력해주세요")
        return self
