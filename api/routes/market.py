"""전국 법정동 계층과 실거래 시장 집계를 노출하는 얇은 API 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.deps import get_current_user
from backend.services.market_service import get_region_market_summary, list_legal_regions

router = APIRouter(tags=["market-explorer"])
_PROPERTY_PATTERN = "^(all|apartment|row_house|detached|officetel|non_residential|industrial|land)$"


@router.get("/market/regions")
def list_regions(
    level: str = Query(default="sido", pattern="^(sido|sigungu|eupmyeondong|eup_myeon_dong|ri)$"),
    parent_code: str | None = Query(default=None, min_length=10, max_length=10),
    user: dict = Depends(get_current_user),
):
    del user
    return {"items": list_legal_regions(level=level, parent_code=parent_code)}


@router.get("/market/regions/summary")
def region_market_summary(
    region_code: str = Query(..., min_length=10, max_length=10),
    group_level: str = Query(default="sigungu", pattern="^(sigungu|eup_myeon_dong)$"),
    months: int = Query(default=12, ge=1, le=60),
    property_type: str = Query(default="all", pattern=_PROPERTY_PATTERN),
    budget_max: int = Query(default=0, ge=0, description="만원 단위"),
    area_min_sqm: float | None = Query(default=None, gt=0, le=100000),
    area_max_sqm: float | None = Query(default=None, gt=0, le=100000),
    min_build_year: int | None = Query(default=None, ge=1800, le=2100),
    max_build_year: int | None = Query(default=None, ge=1800, le=2100),
    user: dict = Depends(get_current_user),
):
    del user
    return get_region_market_summary(
        region_code=region_code, months=months, property_type=property_type,
        group_level=group_level,
        budget_max_won=budget_max * 10_000 if budget_max else None,
        area_min_sqm=area_min_sqm, area_max_sqm=area_max_sqm,
        min_build_year=min_build_year, max_build_year=max_build_year,
    )


@router.get("/market/districts")
def district_market_summary(
    sido: str = "서울특별시",
    months: int = Query(default=12, ge=1, le=60),
    property_type: str = Query(default="all", pattern=_PROPERTY_PATTERN),
    budget_max: int = Query(default=0, ge=0, description="만원 단위"),
    user: dict = Depends(get_current_user),
):
    """기존 클라이언트를 위한 호환 API. 신규 화면은 regions/summary를 사용한다."""
    del user
    return get_region_market_summary(
        legacy_sido_name=sido, months=months, property_type=property_type,
        budget_max_won=budget_max * 10_000 if budget_max else None,
    )
