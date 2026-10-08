"""평가 대상·실행 정책·근거를 보존하는 공통 AVM 계약. 금액은 원이다."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


ResultKind = Literal["market_reference", "conditional_scenario", "public_reference", "partial_reference", "withheld", "unsupported"]


class ValuationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    scope: Literal["single_unit", "whole_building", "land_and_building", "single_parcel", "unknown"] = "unknown"
    area_basis: Literal["exclusive", "supply", "gross", "land", "unknown"] = "unknown"
    transaction_type: Literal["sale", "jeonse", "rent", "unknown"] = "sale"
    dong: str = Field(default="", max_length=50)
    ho: str = Field(default="", max_length=50)


class ValuationSubject(ValuationContext):
    category: str
    subtype: str
    address: str
    building_name: str = ""
    area_sqm: float | None = None
    as_of_date: str
    purpose: str
    identity_level: Literal["user_address", "parcel", "complex_area", "unknown"] = "user_address"


class ValuationCheck(BaseModel):
    code: str
    status: Literal["available", "missing", "conflict"]
    message: str
    source: Literal["user_input", "official_data", "analysis", "policy"]
    reference_date: str | None = None
    observed_at: str | None = None


class ValuationMethod(BaseModel):
    method: str
    status: Literal["selected", "blocked", "not_applicable"]
    reason: str
    engine_version: str | None = None


class ReferenceTrade(BaseModel):
    deal_date: str
    floor: str = ""
    area_sqm: float
    price_won: int
    price_per_sqm_won: int


class ReferenceContext(BaseModel):
    """가격 산출이 보류된 경우에도 사용자가 직접 볼 수 있는 동일 단지 거래 목록. 추정가로 쓰지 않는다."""
    model_config = ConfigDict(extra="forbid")
    window_months: int
    area_tolerance_pct: int
    time_adjusted: Literal[False] = False
    complex_name: str
    trade_count: int
    trades: list[ReferenceTrade] = Field(default_factory=list)
    per_sqm_min_won: int | None = None
    per_sqm_median_won: int | None = None
    per_sqm_max_won: int | None = None


class JeonseLease(BaseModel):
    deal_date: str
    area_sqm: float
    deposit_won: int
    deposit_per_sqm_won: int
    renewal: bool = False


class JeonseContext(BaseModel):
    """동일 단지 전세·매매 ㎡당 중앙값의 대조. 가격 추정이 아니며 표본이 적으면 sufficient=false다."""
    model_config = ConfigDict(extra="forbid")
    window_months: int
    area_tolerance_pct: int
    complex_name: str
    lease_count: int
    sale_count: int
    renewal_count: int = 0
    lease_per_sqm_median_won: int | None = None
    sale_per_sqm_median_won: int | None = None
    ratio_pct: float | None = None
    sufficient: bool = False
    missing_months: int = 0
    leases: list[JeonseLease] = Field(default_factory=list)


class ValuationAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["valuation-assessment-1.0"] = "valuation-assessment-1.0"
    policy_version: Literal["PC-AVM-1.0-runtime-1"] = "PC-AVM-1.0-runtime-1"
    subject: ValuationSubject
    input_fingerprint: str
    result_kind: ResultKind
    comparison_eligible: bool = False
    checks: list[ValuationCheck] = Field(default_factory=list)
    methods: list[ValuationMethod] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    interval_basis: str = "not_provided"
    model_status: Literal["not_used"] = "not_used"
    reference_context: ReferenceContext | None = None
    jeonse_context: JeonseContext | None = None
