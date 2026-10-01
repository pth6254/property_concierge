"""
property_listing.py — 매물 스키마

금액 단위: 원 (int)
면적 단위: m² (float)
거리 단위: m (int)
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PropertyListing(BaseModel):
    """매물 1건"""

    listing_id: str                      # 매물 고유 ID

    # 물건 기본 정보
    complex_name: Optional[str]  = None  # 단지명·건물명
    address: str                         # 도로명 또는 지번 주소
    region: Optional[str]        = None  # 시·군·구 (예: 마포구)
    property_type: str                   # 주거용 / 상업용 / 업무용 / 산업용 / 토지
    area_m2: Optional[float]     = None  # 전용면적 m²
    floor: Optional[int]         = None  # 층수
    built_year: Optional[int]    = None  # 준공연도

    # 가격 (원 단위)
    asking_price: int                          # 매도 호가 (원)
    deposit_price: Optional[int]       = None  # 임대 보증금가 (원, 주거용·반전세)
    monthly_rent_income: Optional[int] = None  # 월 임대수입 (원, 상업용/업무용/산업용)
    maintenance_fee: Optional[int]     = None  # 관리비 (원/월)

    # 위치
    lat: Optional[float]         = None  # 위도
    lng: Optional[float]         = None  # 경도

    # 인프라 접근성 (m 단위)
    station_distance_m: Optional[int]  = None  # 최근접 지하철역 거리 (m)
    school_distance_m: Optional[int]   = None  # 최근접 학교 거리 (m)

    # 기타
    description: Optional[str]  = None  # 매물 설명
