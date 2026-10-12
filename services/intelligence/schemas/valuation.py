"""평가 대상·실행 정책·근거를 보존하는 공통 AVM 계약. 금액은 원이다."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


# model_estimate: 공개 기준(같은 단지 6개월 5건) 미달 근거로 낸 ML 참고 추정. 시장가격 비교·체크리스트 완료에 쓰지 않는다.
ResultKind = Literal["market_reference", "model_estimate", "conditional_scenario", "public_reference", "partial_reference", "withheld", "unsupported"]


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


class ModelContext(BaseModel):
    """혼합 AVM(R-APT)의 근거 단계와 추정. 금액은 원. 구간은 검증 구간 잔차 분위수로 보정한 참고 구간이다."""
    model_config = ConfigDict(extra="forbid")
    level: Literal["A1", "A2", "A3", "A4"]
    basis: str
    complex: str = ""
    counts: dict[str, int] = Field(default_factory=dict)
    model: str
    model_version: str | None = None
    trained_through: str | None = None
    interval: float | None = None
    estimated_value: int | None = None
    value_min: int | None = None
    value_max: int | None = None
    confidence: float | None = None
    comparable_weight: float | None = None
    comparable_per_sqm: int | None = None
    # A1에 혼합 추정을 적용해도 된다고 평가로 승인된 산출물인지. 미승인이면 A1은 기존 비교 규칙 가격을 쓴다.
    hybrid_approved: bool = False
    applied: bool = False


class ValuationAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["valuation-assessment-1.0"] = "valuation-assessment-1.0"
    policy_version: Literal["PC-AVM-1.0-runtime-1"] = "PC-AVM-1.0-runtime-1"
    subject: ValuationSubject
    # 용도×거래 단위 세그먼트(backend/valuation/segments). 기록만 하며 이 값으로 공개 여부를 바꾸지 않는다.
    segment: str | None = None
    input_fingerprint: str
    result_kind: ResultKind
    comparison_eligible: bool = False
    checks: list[ValuationCheck] = Field(default_factory=list)
    methods: list[ValuationMethod] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    interval_basis: str = "not_provided"
    model_status: Literal["not_used", "used"] = "not_used"
    model_context: ModelContext | None = None
    reference_context: ReferenceContext | None = None
    jeonse_context: JeonseContext | None = None
