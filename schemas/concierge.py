"""종합 부동산 컨시어지의 기능 간 공통 계약."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConciergeIntent(str, Enum):
    FIND_REGION = "find_region"
    SELECT_PROPERTY = "select_property"
    SEARCH_LISTING = "search_listing"
    APPRAISE = "appraise"
    COMPARE = "compare"
    SIMULATE = "simulate"
    RIGHTS_CHECK = "rights_check"
    TAX_LEGAL = "tax_legal"
    GENERAL = "general"


class ConciergeCriteria(BaseModel):
    property_type: Literal[
        "apartment", "row_house", "detached", "officetel",
        "non_residential", "industrial", "land",
    ] | None = None
    transaction_type: Literal["purchase", "rent", "lease"] | None = None
    budget_max_won: int | None = Field(default=None, ge=0)
    region_name: str | None = None
    region_code: str | None = Field(default=None, pattern=r"^\d{10}$")
    area_min_sqm: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    purpose: Literal["residence", "investment"] | None = None


class ConciergeDecision(BaseModel):
    intent: ConciergeIntent
    criteria: ConciergeCriteria = Field(default_factory=ConciergeCriteria)


class ConciergeExtraction(BaseModel):
    """모델의 부분 추출을 받는 봉투. 필드 오류는 실행 전에 개별 검증한다."""
    model_config = ConfigDict(extra="forbid")
    intent: ConciergeIntent
    criteria: dict[str, Any] = Field(default_factory=dict)
    clear_fields: list[str] = Field(default_factory=list)
    funding: dict[str, Any] = Field(default_factory=dict)


class ConciergeFunding(BaseModel):
    """대화에서 명시한 금융 조건만 보관한다. 미입력은 계산 기본값과 구분한다."""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    cash_available: int | None = Field(None, ge=0)
    monthly_payment_limit: int | None = Field(None, ge=0)
    loan_ratio: float | None = Field(None, ge=0, le=0.9)
    annual_interest_rate: float | None = Field(None, ge=0, le=30)
    loan_years: int | None = Field(None, ge=1, le=50)
    repayment_type: Literal["equal_payment", "equal_principal", "interest_only"] | None = None
    owned_homes: int | None = Field(None, ge=1, le=100)
    adjusted_area: bool | None = None
    annual_income: int | None = Field(None, gt=0)
    existing_loan_annual_payment: int | None = Field(None, ge=0)


class ConciergeMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = None
    case_id: int | None = Field(default=None, gt=0)
    candidate_id: int | None = Field(default=None, gt=0)
    clear_context: bool = False


class ConciergeToolResult(BaseModel):
    tool: str
    status: Literal["completed", "needs_input", "not_available", "error", "queued"]
    data: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)


class ConciergeMessageResponse(BaseModel):
    conversation_id: str
    status: Literal["completed", "needs_input", "not_available", "error", "queued"]
    intent: ConciergeIntent
    answer: str
    criteria: ConciergeCriteria
    data: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    tool_used: str | None = None
    pending_action: dict[str, Any] | None = None
