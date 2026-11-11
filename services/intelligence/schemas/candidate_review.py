"""후보 한 번에 검토(자금 계산·시세추정 접수·권리 안내)의 내부 계약."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CandidateQuickReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: int = Field(..., gt=0)
    candidate_id: int = Field(..., gt=0)


class QuickReviewFunding(BaseModel):
    # current: 유효한 저장 분석 유지, calculated: 이번에 계산·저장, needs_input: 조건 부족으로 미실행, error: 실행 실패
    status: Literal["current", "calculated", "needs_input", "error"]
    input_source: Literal["profile", "saved"] | None = None
    missing: list[str] = Field(default_factory=list)
    summary: dict[str, int | None] | None = None
    warnings: list[str] = Field(default_factory=list)
    message: str | None = None


class QuickReviewAppraisal(BaseModel):
    # queued: 작업 접수(결과는 실행기가 후보에 연결), 나머지는 자금과 같은 의미
    status: Literal["current", "queued", "needs_input", "error"]
    job_id: str | None = None
    missing: list[str] = Field(default_factory=list)
    input_url: str | None = None
    message: str | None = None


class QuickReviewRights(BaseModel):
    # 권리 점검은 등기부 PDF 업로드가 필요해 실행하지 않는다.
    status: Literal["current", "stale", "needs_document"]


class CandidateQuickReviewResponse(BaseModel):
    case_id: int
    candidate_id: int
    funding: QuickReviewFunding
    appraisal: QuickReviewAppraisal
    rights: QuickReviewRights
