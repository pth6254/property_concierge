"""API와 컨시어지 도구가 함께 사용하는 실거래 시장 집계 서비스."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import and_, or_, case, cast, Integer, func, select

from db.base import session_scope
from db.models import LegalRegion, Transaction

PROPERTY_ENDPOINTS = {
    "all": None,
    "apartment": "RTMSDataSvcAptTrade",
    "row_house": "RTMSDataSvcRHTrade",
    "detached": "RTMSDataSvcSHTrade",
    "officetel": "RTMSDataSvcOffiTrade",
    "non_residential": "RTMSDataSvcNrgTrade",
    "industrial": "RTMSDataSvcInduTrade",
    "land": "RTMSDataSvcLandTrade",
}


def list_legal_regions(*, level: str, parent_code: str | None) -> list[dict]:
    level = "eup_myeon_dong" if level == "eupmyeondong" else level
    with session_scope() as session:
        stmt = (
            select(LegalRegion)
            .where(LegalRegion.is_active.is_(True), LegalRegion.level == level)
            .order_by(LegalRegion.sort_order, LegalRegion.name)
        )
        stmt = stmt.where(
            LegalRegion.parent_code.is_(None)
            if parent_code is None else LegalRegion.parent_code == parent_code
        )
        rows = session.scalars(stmt).all()
        return [
            {
                "code": row.code,
                "parent_code": row.parent_code,
                "name": row.name,
                "full_name": row.full_name,
                "level": row.level,
                "lawd_code": row.lawd_code,
            }
            for row in rows
        ]


def resolve_region_name(name: str) -> dict:
    """LLM이 만든 코드를 신뢰하지 않고 정식 법정동 마스터에서 지역명을 해석한다."""
    normalized = name.strip()
    aliases = {"서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
               "인천": "인천광역시", "광주": "광주광역시", "대전": "대전광역시",
               "울산": "울산광역시", "세종": "세종특별자치시", "제주": "제주특별자치도"}
    normalized = aliases.get(normalized, normalized)
    with session_scope() as session:
        exact = session.scalars(
            select(LegalRegion).where(
                LegalRegion.is_active.is_(True),
                (LegalRegion.full_name == normalized) | (LegalRegion.name == normalized),
            ).order_by(LegalRegion.depth, LegalRegion.sort_order)
        ).all()
    if len(exact) == 1:
        row = exact[0]
        return {"status": "resolved", "code": row.code, "full_name": row.full_name, "level": row.level}
    if exact:
        return {"status": "ambiguous", "candidates": [
            {"code": row.code, "full_name": row.full_name, "level": row.level} for row in exact[:10]
        ]}
    return {"status": "not_found", "candidates": []}


def get_region_market_summary(
    *,
    months: int,
    property_type: str,
    budget_max_won: int | None = None,
    region_code: str | None = None,
    legacy_sido_name: str | None = None,
    group_level: str = "sigungu",
    area_min_sqm: float | None = None,
    area_max_sqm: float | None = None,
    min_build_year: int | None = None,
    max_build_year: int | None = None,
) -> dict:
    if area_min_sqm and area_max_sqm and area_min_sqm > area_max_sqm:
        raise HTTPException(422, "최소 면적은 최대 면적보다 클 수 없습니다")
    if min_build_year and max_build_year and min_build_year > max_build_year:
        raise HTTPException(422, "준공연도 범위를 확인해주세요")
    if property_type not in PROPERTY_ENDPOINTS:
        raise ValueError(f"지원하지 않는 부동산 유형: {property_type}")
    endpoint = PROPERTY_ENDPOINTS[property_type]
    budget_max = budget_max_won // 10_000 if budget_max_won else 0

    with session_scope() as session:
        selected_region = session.get(LegalRegion, region_code) if region_code else None
        if region_code and (not selected_region or not selected_region.is_active):
            raise HTTPException(status_code=404, detail="선택한 행정구역을 찾을 수 없습니다")
        if selected_region and selected_region.level == "eup_myeon_dong":
            group_level = "eup_myeon_dong"
        if group_level not in {"sigungu", "eup_myeon_dong"}:
            raise HTTPException(status_code=422, detail="지원하지 않는 집계 단위입니다")
        join_condition = Transaction.lawd_cd == LegalRegion.lawd_code
        if group_level == "eup_myeon_dong":
            # 공식 코드가 있는 거래는 이름으로 재매칭하지 않아 잘못된 동에 중복 집계하지 않는다.
            join_condition = and_(join_condition, or_(
                Transaction.bjdong_code == LegalRegion.code,
                and_(or_(Transaction.bjdong_code.is_(None), Transaction.bjdong_code == ""),
                     func.trim(Transaction.dong) == LegalRegion.name),
            ))
        max_ym = session.scalar(select(func.max(Transaction.deal_ym)))
        if not max_ym:
            return {"source": "국토교통부 실거래가", "period": None, "items": []}
        year, month = int(max_ym[:4]), int(max_ym[4:])
        absolute = year * 12 + month - months
        min_ym = f"{absolute // 12:04d}{absolute % 12 + 1:02d}"

        budget_fit = func.sum(case((Transaction.price <= budget_max, 1), else_=0)) if budget_max else func.count()
        stmt = (
            select(
                LegalRegion.full_name.label("region_name"), LegalRegion.code.label("region_code"),
                LegalRegion.lawd_code, func.count(Transaction.id).label("deal_count"),
                func.round(func.avg(Transaction.price)).label("avg_price"),
                func.percentile_cont(0.5).within_group(Transaction.price).label("median_price"),
                func.percentile_cont(0.25).within_group(Transaction.price).label("price_q1"),
                func.percentile_cont(0.75).within_group(Transaction.price).label("price_q3"),
                func.round(func.avg(Transaction.per_sqm)).label("avg_per_sqm"),
                func.percentile_cont(0.5).within_group(Transaction.per_sqm).label("median_per_sqm"),
                func.count(func.distinct(Transaction.apt_name)).label("asset_count"),
                func.max(Transaction.deal_ym).label("last_deal_ym"), budget_fit.label("budget_fit_count"),
            )
            .join(Transaction, join_condition)
            .where(
                LegalRegion.is_active.is_(True), LegalRegion.level == group_level,
                Transaction.deal_ym >= min_ym, Transaction.deal_ym <= max_ym,
                Transaction.is_cancelled.is_(False),
            )
            .group_by(LegalRegion.full_name, LegalRegion.code, LegalRegion.lawd_code)
            .order_by(func.avg(Transaction.per_sqm), LegalRegion.full_name)
        )
        if selected_region:
            if selected_region.level == "sido":
                stmt = stmt.where(LegalRegion.sido_code == selected_region.sido_code)
            elif selected_region.level == "sigungu":
                stmt = stmt.where(LegalRegion.lawd_code == selected_region.lawd_code)
            elif selected_region.level == "eup_myeon_dong":
                stmt = stmt.where(LegalRegion.code == selected_region.code)
            else:
                raise HTTPException(status_code=422, detail="시장 비교는 시·도, 시·군·구, 읍·면·동까지 지원합니다")
        elif legacy_sido_name:
            stmt = stmt.where(LegalRegion.full_name.like(f"{legacy_sido_name} %"))
        if endpoint:
            stmt = stmt.where(Transaction.endpoint == endpoint)
        if area_min_sqm is not None:
            stmt = stmt.where(Transaction.area_sqm >= area_min_sqm)
        if area_max_sqm is not None:
            stmt = stmt.where(Transaction.area_sqm <= area_max_sqm)
        # 원천에는 빈 문자열·미상 연도가 있어 무조건 정수 변환하면 조회 전체가 실패한다.
        build_year = case((Transaction.year_built.op("~")(r"^\d{4}$"), cast(Transaction.year_built, Integer)), else_=None)
        if min_build_year is not None:
            stmt = stmt.where(build_year >= min_build_year)
        if max_build_year is not None:
            stmt = stmt.where(build_year <= max_build_year)
        rows = session.execute(stmt).mappings().all()

    return {
        "source": "국토교통부 실거래가", "price_unit": "만원",
        "period": {"from": min_ym, "to": max_ym}, "property_type": property_type,
        "group_level": group_level,
        "scope": ({"code": selected_region.code, "name": selected_region.name,
                   "full_name": selected_region.full_name, "level": selected_region.level}
                  if selected_region else None),
        "items": [_market_item(row) for row in rows],
        "criteria": {"area_min_sqm": area_min_sqm, "area_max_sqm": area_max_sqm,
                     "min_build_year": min_build_year, "max_build_year": max_build_year, "months": months},
        "notice": "동일 조건의 신고 거래 분포입니다. 표본 수준은 거래 건수 기준이며 가격 예측 정확도가 아닙니다.",
    }


def _market_item(row) -> dict:
    sample_size = int(row["deal_count"] or 0)
    budget_fit_count = int(row["budget_fit_count"] or 0)
    return {
        "region_name": row["region_name"], "region_code": row["region_code"],
        "lawd_code": row["lawd_code"], "deal_count": sample_size,
        "sample_size": sample_size,
        "avg_price": int(row["avg_price"] or 0),
        "median_price": int(row["median_price"] or 0),
        "price_q1": int(row["price_q1"] or 0),
        "price_q3": int(row["price_q3"] or 0),
        "avg_per_sqm": int(row["avg_per_sqm"] or 0),
        "median_per_sqm": int(row["median_per_sqm"] or 0),
        "asset_count": row["asset_count"], "last_deal_ym": row["last_deal_ym"],
        "budget_fit_count": budget_fit_count,
        "budget_fit_ratio": round(budget_fit_count / sample_size, 4) if sample_size else 0.0,
        # 지역 간 동일한 결정 규칙을 적용해 LLM이 신뢰도를 자의적으로 만들지 못하게 한다.
        "confidence": "high" if sample_size >= 100 else "medium" if sample_size >= 30 else "low",
        "comparison_eligible": sample_size >= 5,
        "warnings": ["표본 5건 미만: 지역 순위 판단에 사용하지 마세요"] if sample_size < 5 else [],
    }
