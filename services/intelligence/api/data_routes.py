"""전국 법정동 계층과 실거래 시장 집계를 노출하는 얇은 API 라우터."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from schemas.purchase_case import CaseRegionCreate

from api.internal_contracts import require_service
from backend.services.market_service import get_region_market_summary, list_legal_regions

router = APIRouter(prefix="/internal/v1/data", tags=["data-analysis"], dependencies=[Depends(require_service)])
_PROPERTY_PATTERN = "^(all|apartment|row_house|detached|officetel|non_residential|industrial|land)$"


@router.get("/market/regions")
def list_regions(
    level: str = Query(default="sido", pattern="^(sido|sigungu|eupmyeondong|eup_myeon_dong|ri)$"),
    parent_code: str | None = Query(default=None, min_length=10, max_length=10),
):
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
):
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
):
    """기존 클라이언트를 위한 호환 API. 신규 화면은 regions/summary를 사용한다."""
    return get_region_market_summary(
        legacy_sido_name=sido, months=months, property_type=property_type,
        budget_max_won=budget_max * 10_000 if budget_max else None,
    )

@router.post("/mortgage-rate")
def mortgage_rate():
    from backend.bok_rates import get_mortgage_rate
    return get_mortgage_rate()

@router.post("/runtime-status")
def runtime_status():
    from api.operational_health import snapshot
    return snapshot()

@router.get("/ingestion")
def ingestion(lawd_code: str = Query("11350", pattern=r"^\d{5}$"), months: int = Query(12, ge=1, le=24)):
    from backend.services.ingestion_operations import coverage
    try:
        return coverage(lawd_code, months)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None

class RetryIngestion(BaseModel):
    lawd_code: str = Field(pattern=r"^\d{5}$")
    endpoint: str = Field(min_length=1, max_length=80)
    month: str = Field(pattern=r"^\d{4}(0[1-9]|1[0-2])$")

@router.post("/ingestion/validate-retry")
def retry_input(body: RetryIngestion):
    items = ingestion(body.lawd_code, 24)["items"]
    if not any(row["endpoint"] == body.endpoint and row["month"] == body.month and row["status"] in {"failed", "missing", "interrupted", "stale"} for row in items):
        raise HTTPException(422, "실패·누락·중단·만료된 최근 24개월 자료만 재수집할 수 있습니다")
    return body.model_dump()

class RegionSnapshot(BaseModel):
    case: dict
    request: CaseRegionCreate

@router.post("/case-region")
def region_snapshot(body: RegionSnapshot):
    request, profile = body.request, body.case.get("buyer_profile") or {}
    summary = get_region_market_summary(region_code=request.region_code, property_type=request.property_type,
        months=request.months, budget_max_won=request.budget_max_won,
        area_min_sqm=profile.get("min_area_sqm"), area_max_sqm=profile.get("max_area_sqm"),
        min_build_year=profile.get("min_build_year"), max_build_year=profile.get("max_build_year"))
    item = next((item for item in summary.get("items", []) if item["region_code"] == request.region_code), None)
    if item is None:
        raise HTTPException(422, "해당 지역에 저장할 수집 실거래 통계가 없습니다")
    item["comparison_criteria"] = summary.get("criteria", {})
    period = summary.get("period") or {}
    return {"region_code":request.region_code, "source":request.source, "property_type":request.property_type,
        "budget_max_won":request.budget_max_won, "period_from":period.get("from"), "period_to":period.get("to"), "stats_snapshot":item}
