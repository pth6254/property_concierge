"""POST /api/recommendation — 매물 추천"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)
router = APIRouter(tags=["recommendation"])


class RecommendationRequest(BaseModel):
    region: Optional[str] = None
    property_type: Optional[str] = None
    budget_min: Optional[int] = Field(None, ge=0)
    budget_max: Optional[int] = Field(None, ge=0)
    area_m2: Optional[float] = Field(None, gt=0)
    purpose: Literal["live", "investment", "sell", "hold"] | None = None
    complex_name: Optional[str] = None
    limit: int = Field(5, ge=1, le=50)
    run_appraisal: bool = False

    @field_validator("purpose", mode="before")
    @classmethod
    def normalize_purpose(cls, value):
        # 기존 화면의 한글 선택값도 내부 의사결정 스키마와 같은 의도로 변환한다.
        return {"실거주": "live", "투자": "investment", "매도": "sell", "보유": "hold", "전체": None}.get(value, value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_budget(self):
        if self.budget_min is not None and self.budget_max is not None and self.budget_min > self.budget_max:
            raise ValueError("최소 예산은 최대 예산보다 클 수 없습니다")
        return self


class ComplexRecommendRequest(BaseModel):
    region_code: str | None = Field(default=None, pattern=r"^\d{10}$")
    """실거래 기반 단지 추천 (전국) — 금액 단위: 만원"""
    region: str
    budget_min: int = Field(0, ge=0)
    budget_max: int = Field(0, ge=0)
    area_m2: float = Field(0, ge=0, allow_inf_nan=False)
    months: int = Field(6, ge=1, le=24)
    limit: int = Field(5, ge=1, le=20)

    @model_validator(mode="after")
    def validate_budget(self):
        if self.budget_max and self.budget_min > self.budget_max:
            raise ValueError("최소 예산은 최대 예산보다 클 수 없습니다")
        return self


@router.post("/recommendation/complexes")
async def recommend_complexes_endpoint(req: ComplexRecommendRequest):
    """국토부 실거래 데이터 기반 아파트 단지 추천 — 전국 시군구 지원."""
    from backend.services.complex_recommend_service import recommend_complexes

    logger.info("단지 추천 요청 — %s / 예산 %s~%s만원 / %s㎡",
                req.region, req.budget_min or "-", req.budget_max or "-", req.area_m2 or "-")
    return await asyncio.to_thread(
        recommend_complexes,
        req.region, req.budget_min, req.budget_max,
        req.area_m2, req.months, req.limit, region_code=req.region_code,
    )


@router.post("/recommendation")
async def run_recommendation_endpoint(req: RecommendationRequest):
    from backend.router import run_recommendation
    from schemas.property_query import PropertyQuery

    query = PropertyQuery(
        intent        = "recommendation",
        region        = req.region,
        property_type = req.property_type,
        budget_min    = req.budget_min,
        budget_max    = req.budget_max,
        area_m2       = req.area_m2,
        purpose       = req.purpose,
        complex_name  = req.complex_name,
    )

    logger.info("매물 추천 요청 — region=%s, type=%s, limit=%d", req.region, req.property_type, req.limit)
    result = await asyncio.to_thread(run_recommendation, query, req.limit, req.run_appraisal)
    return result
