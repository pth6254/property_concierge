"""
report.py — 파이프라인별 구조화 리포트 래퍼

각 파이프라인의 최종 출력을 Markdown 문자열 + 원본 구조화 데이터로 묶는다.
재활용(히스토리, 비교, 내보내기)이 필요한 경우 이 객체를 사용한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from schemas.appraisal_result import AppraisalResult
from schemas.comparison import ComparisonResult
from schemas.recommendation_result import RecommendationResult
from schemas.simulation import SimulationInput, SimulationResult


class AppraisalReport(BaseModel):
    """감정평가 파이프라인 최종 리포트"""

    structured: AppraisalResult
    markdown: str
    generated_at: datetime = Field(default_factory=datetime.now)


class RecommendationReport(BaseModel):
    """매물 추천 파이프라인 최종 리포트"""

    results: list[RecommendationResult]
    markdown: str
    generated_at: datetime = Field(default_factory=datetime.now)


class SimulationReport(BaseModel):
    """투자 시뮬레이션 파이프라인 최종 리포트"""

    result: SimulationResult
    input: Optional[SimulationInput] = None
    markdown: str
    generated_at: datetime = Field(default_factory=datetime.now)


class ComparisonReport(BaseModel):
    """매물 비교 파이프라인 최종 리포트"""

    result: ComparisonResult
    markdown: str
    generated_at: datetime = Field(default_factory=datetime.now)
