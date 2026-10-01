"""사람 채점은 자동 검사 점수와 섞지 않고 미검토·치명적 오류를 별도로 집계한다."""
from __future__ import annotations

from typing import Literal
from pydantic import Field, model_validator
from evaluation.schema import StrictModel


class ReviewScores(StrictModel):
    relevance: int | None = Field(default=None, ge=1, le=5, strict=True)
    groundedness: int | None = Field(default=None, ge=1, le=5, strict=True)
    context_retention: int | None = Field(default=None, ge=1, le=5, strict=True)
    clarity: int | None = Field(default=None, ge=1, le=5, strict=True)


class HumanReview(StrictModel):
    id: str
    repeat: int = Field(ge=1)
    status: Literal["pending", "reviewed"]
    scores: ReviewScores
    critical_error: bool | None = None
    reviewer: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def completed_review(self):
        if self.status == "reviewed" and (not self.reviewer.strip() or self.critical_error is None or
                                          any(value is None for value in self.scores.model_dump().values())):
            raise ValueError("검토 완료에는 확인자·전체 점수·치명적 오류 여부가 필요합니다")
        return self


class Reviews(StrictModel):
    run_id: str
    reviews: list[HumanReview]


def summarize_reviews(report: dict, reviews: Reviews) -> dict:
    if report["metadata"]["run_id"] != reviews.run_id:
        raise ValueError("평가 실행과 사람 검토의 run_id가 다릅니다")
    expected = {(r["id"], r["repeat"]) for r in report["results"] if r.get("review_required")}
    keys = [(r.id, r.repeat) for r in reviews.reviews]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("검토 대상이 누락·중복되거나 실행 결과와 다릅니다")
    completed = [r for r in reviews.reviews if r.status == "reviewed"]
    failed = [r for r in completed if r.critical_error or min(r.scores.model_dump().values()) < 3]
    return {"total": len(expected), "reviewed": len(completed), "pending": len(expected) - len(completed),
            "failed": len(failed), "critical_errors": sum(bool(r.critical_error) for r in completed),
            "criteria": "각 항목 3/5 이상, 치명적 오류 없음. 자동 검사 결과와 별도 판정."}
