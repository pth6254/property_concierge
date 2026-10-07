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
