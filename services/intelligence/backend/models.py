"""
models.py — 백엔드 공유 데이터 모델

analysis_tools.py에서 이동.
ValuationResult : 5개 에이전트의 공통 출력 모델 (만원 단위)
_intent_summary : intent 객체 → 요약 문자열 헬퍼
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ValuationResult(BaseModel):
    agent_name: str

    estimated_value: int         = Field(default=0)
    value_min: int               = Field(default=0)
    value_max: int               = Field(default=0)
    value_unit: str              = Field(default="만원")
    valuation_method: str        = Field(default="")

    price_per_pyeong: int        = Field(default=0)
    area_pyeong: float           = Field(default=0.0)
    regional_avg_per_pyeong: int = Field(default=0)
    price_per_sqm: int           = Field(default=0)

    comparable_avg: int          = Field(default=0)
    comparable_count: int        = Field(default=0)
    comparables: list[dict]      = Field(default_factory=list)
    used_months: int             = Field(default=0)   # 비교사례 조회에 사용된 개월 수

    cap_rate: float              = Field(default=0.0)
    annual_income: int           = Field(default=0)
    roi_5yr: float               = Field(default=0.0)
    investment_grade: str        = Field(default="")

    price_avg: int               = Field(default=0)
    price_min: int               = Field(default=0)
    price_max: int               = Field(default=0)
    price_sample_count: int      = Field(default=0)

    nearby_facilities: dict      = Field(default_factory=dict)
    web_summary: str             = Field(default="")

    appraisal_opinion: str       = Field(default="")
    strengths: list[str]         = Field(default_factory=list)
    risk_factors: list[str]      = Field(default_factory=list)
    recommendation: str          = Field(default="")

    price_error: str             = Field(default="")

    # 물건 기본사항 (감정평가서 공부 정보)
    land_use_zone: str           = Field(default="")     # 용도지역
    official_land_price: int     = Field(default=0)      # 공시지가 (원/m²)
    build_year: int              = Field(default=0)      # 건축연도
    exclusive_area_m2: float     = Field(default=0.0)    # 전용면적 m²

    # 공법상 제한 & 개발계획 (web_summary 파싱)
    legal_restrictions: list[str] = Field(default_factory=list)
    development_plans: list[str]  = Field(default_factory=list)


def _intent_summary(intent) -> str:
    if not intent:
        return ""

    price_min = getattr(intent, "price_min", None)
    price_max = getattr(intent, "price_max", None)
    price_raw = getattr(intent, "price_raw", "")
    if not price_raw:
        if price_min and price_max:
            price_raw = f"{price_min:,}만원 ~ {price_max:,}만원"
        elif price_max:
            price_raw = f"{price_max:,}만원 이하"
        elif price_min:
            price_raw = f"{price_min:,}만원 이상"

    parts = [
        f"위치: {getattr(intent, 'location_normalized', '')}",
        f"거래: {getattr(intent, 'transaction_type', '')}",
        f"가격: {price_raw}",
        f"면적: {getattr(intent, 'area_raw', '')}",
        f"특수조건: {', '.join(getattr(intent, 'special_conditions', []))}",
    ]
    return " | ".join(p for p in parts if p.split(": ")[1])
