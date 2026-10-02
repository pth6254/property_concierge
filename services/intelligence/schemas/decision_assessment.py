"""저장된 사실과 계산 결과를 구분하는 후보별 의사결정 조회 계약."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AssessmentStatus = Literal["confirmed", "warning", "unknown", "stale", "error", "pending"]
AxisKey = Literal["fit", "price", "funding", "risk", "execution"]


class DecisionEvidence(BaseModel):
    provenance: dict | None = None
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    key: str
    label: str
    value: str | int | float | bool | None
    unit: str = ""
    source: Literal["user_input", "calculation", "document", "workflow", "official_data"]
    as_of: str | None = None
    usable: bool = True
    reference_url: str | None = None


class DecisionAxis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: AxisKey
    label: str
    status: AssessmentStatus
    headline: str
    explanation: str
    evidence: list[DecisionEvidence] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    review_target: Literal["profile", "appraisal", "simulation", "rights", "checklist", "execution"]
    review_label: str


class DecisionMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    asking_price: int | None = None
    required_cash: int | None = None
    monthly_payment: int | None = None
    cash_shortfall: int | None = None
    price_gap: int | None = None
    price_gap_ratio: float | None = None


class DecisionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    title: str
    reason: str
    target: Literal["price", "appraisal", "simulation", "rights", "checklist", "listings", "profile"]
    priority: Literal["warning", "input", "normal"]
    checklist_id: int | None = None


class CandidateDecisionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: dict | None = None
    property_id: int
    name: str
    status: Literal["reviewing", "shortlisted", "selected", "rejected"]
    review_ready: bool
    metrics: DecisionMetrics
    axes: list[DecisionAxis] = Field(min_length=5, max_length=5)
    next_actions: list[DecisionAction] = Field(default_factory=list)


class CaseDecisionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    case_id: int
    evaluated_at: str
    candidates: list[CandidateDecisionAssessment]
    boundary: str = "저장된 자료를 검토하는 참고용 결과입니다. AVM은 법정 감정평가가 아니며 대출 승인·매물 존재·거래 안전성을 보장하지 않습니다. 최종 선택은 사용자가 합니다."
