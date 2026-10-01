"""
recommendation_result.py — 매물 추천 결과 스키마
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from schemas.appraisal_result import AppraisalResult
from schemas.property_listing import PropertyListing


class RecommendationResult(BaseModel):
    """매물 추천 결과 1건"""

    # 원본 매물 정보
    listing: PropertyListing

    # 해당 매물에 대한 감정평가 결과 (분석 전이면 None)
    appraisal: Optional[AppraisalResult] = None

    # 종합 점수 (0.0 ~ 10.0)
    total_score: float      = 0.0

    # 세부 점수 (0.0 ~ 10.0)
    price_score: float      = 0.0   # 가격 적정성
    location_score: float   = 0.0   # 입지 조건
    investment_score: float = 0.0   # 투자 수익성
    risk_score: float       = 0.0   # 리스크 (낮을수록 안전)

    # 추천 라벨
    recommendation_label: str = ""  # 예: "적극 추천" / "검토 필요" / "비추천"

    # 추천 근거 및 리스크
    reasons: list[str] = Field(default_factory=list)   # 추천 이유
    risks: list[str]   = Field(default_factory=list)   # 주의사항
