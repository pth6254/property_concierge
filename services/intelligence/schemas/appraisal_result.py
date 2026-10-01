"""
appraisal_result.py — 감정평가·가격 분석 결과 스키마

금액 단위: 원 (int)
면적 단위: m² (float)
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ComparableTransaction(BaseModel):
    """인근 실거래 사례 (비교사례법 요인 보정 포함)"""

    complex_name: Optional[str]   = None   # 단지명
    address: Optional[str]        = None   # 주소
    area_m2: Optional[float]      = None   # 전용면적 m²
    floor: Optional[str]          = None   # 층수
    year_built: Optional[str]     = None   # 건축연도
    deal_price: Optional[int]     = None   # 거래금액 — 시점수정 후 (원)
    original_price: Optional[int] = None   # 거래금액 — 시점수정 전 (원)
    deal_date: Optional[str]      = None   # 거래일 (YYYY-MM 또는 YYYY-MM-DD)
    price_per_m2: Optional[int]   = None   # 원거래 기준 m²당 금액 (원)
    source: Optional[str]         = None   # 데이터 출처

    # 시점수정
    time_adj_months: int   = 0     # 거래일 ~ 기준시점 월수
    time_adj_factor: float = 1.0   # 시점수정 계수

    # 요인 보정 (감정평가 비교사례법)
    circumstance_adj: float  = 1.0   # 사정보정치 (정상거래 = 1.0)
    region_factor: float     = 1.0   # 지역요인 보정치 (대상지역 / 사례지역)
    individual_factor: float = 1.0   # 개별요인 보정치 (대상물건 / 사례물건)
    adjusted_price_per_m2: Optional[int] = None  # 요인보정 후 비준단가 (원/m²)

    match_level: Optional[Literal[
        "same_complex",   # 동일 단지
        "same_dong",      # 동일 동
        "same_gu",        # 동일 구
        "nearby",         # 인근 지역
        "fallback",       # 폴백 (공시가격 역산 등)
    ]] = None


class ValuationMethodResult(BaseModel):
    """평가방법별 시산가액"""
    method: str                      # 평가방법명 (비교사례법, 수익환원법, 건축원가법 등)
    estimated_value: Optional[int]   = None   # 시산가액 (원)
    weight: Optional[float]          = None   # 최종가액 결정 가중치 (0.0~1.0)
    note: Optional[str]              = None   # 비고 (적용근거, 신뢰도 등)


class AppraisalResult(BaseModel):
    """가격 분석·감정평가 결과"""

    # 추정 가격 범위 (원 단위)
    estimated_price: Optional[int]  = None
    low_price: Optional[int]        = None
    high_price: Optional[int]       = None
    asking_price: Optional[int]     = None

    # 신뢰도 (0.0 ~ 1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # ── 기준시점 & 목적 ───────────────────────────────────────────────────────
    appraisal_date: Optional[str]    = None   # 기준시점 표시 문자열 (예: 2025년 05월 01일)
    appraisal_purpose: Optional[str] = None   # 감정평가 목적 (담보/경매/과세/매매/보상/임의)

    # ── 물건 기본사항 — 토지 ────────────────────────────────────────────────
    land_use_zone: Optional[str]          = None   # 용도지역 (예: 제2종일반주거지역)
    official_land_price: Optional[int]    = None   # 공시지가 (원/m²)
    official_price_ratio: Optional[float] = None   # 감정가 / 공시가 기준추정액 배율
    jimok: Optional[str]                  = None   # 지목 (대, 전, 답, 임야 등)
    road_side: Optional[str]              = None   # 도로접면 (소로한면, 중로각지 등)

    # ── 물건 기본사항 — 건물 ────────────────────────────────────────────────
    exclusive_area_m2: Optional[float] = None  # 전용면적 m²
    common_area_m2: Optional[float]    = None  # 공용면적 m²
    total_area_m2: Optional[float]     = None  # 연면적 m²
    build_year: Optional[int]          = None  # 건축연도 (사용승인연도)

    # ── 시산가액 조정 ────────────────────────────────────────────────────────
    valuation_breakdown: list[ValuationMethodResult] = Field(default_factory=list)

    # ── 공법상 제한 & 개발계획 ───────────────────────────────────────────────
    legal_restrictions: list[str] = Field(default_factory=list)
    development_plans: list[str]  = Field(default_factory=list)

    # 비교 사례
    comparables: list[ComparableTransaction] = Field(default_factory=list)

    # 경고 메시지 (예: "실거래 3건 미만", "공시가격 역산 사용")
    warnings: list[str]    = Field(default_factory=list)

    # 데이터 출처 (예: ["국토부 실거래가", "공시가격 역산"])
    data_source: list[str] = Field(default_factory=list)

    # 기존 analysis_result dict 원본 보존 (하위 호환용)
    raw: dict[str, Any] = Field(default_factory=dict)
