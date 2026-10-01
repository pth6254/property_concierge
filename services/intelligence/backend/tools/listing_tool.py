"""
listing_tool.py — 샘플 매물 조회 도구 (Phase 3-1)

data/sample_listings.csv 에서 PropertyQuery 조건에 맞는 매물을 필터링한다.

⚠️  샘플 데이터 고지:
    data/sample_listings.csv 는 실제 매물이 아닌 개발·테스트용 가상 데이터다.
    가격·면적·좌표는 참고 목적으로만 사용하고 실제 거래 판단에 쓰지 마라.

실 API 전환 시 교체 포인트:
    _load_listings() 에서 CSV 대신 외부 API / DB를 호출하도록만 바꾸면 된다.
    search_listings()의 필터·정렬 로직은 그대로 재사용 가능하다.
"""

from __future__ import annotations

import csv
import os
import sys
from functools import lru_cache
from typing import Optional

# schemas/ 는 프로젝트 루트에 위치 — 경로 추가
_TOOLS_DIR    = os.path.dirname(os.path.abspath(__file__))   # backend/tools/
_BACKEND_DIR  = os.path.dirname(_TOOLS_DIR)                   # backend/
from concierge_workspace import REPO_ROOT
_PROJECT_ROOT = str(REPO_ROOT)                 # 프로젝트 루트

for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schemas.property_listing import PropertyListing
from schemas.property_query import PropertyQuery

_DATA_PATH = os.path.join(_PROJECT_ROOT, "data", "sample_listings.csv")

_AREA_TOLERANCE = 0.30   # area_m2 필터 허용 오차 ±30%


# ─────────────────────────────────────────
#  CSV 로더
# ─────────────────────────────────────────

def _row_to_listing(row: dict) -> PropertyListing:
    def _int(v: str) -> Optional[int]:
        return int(v) if v and v.strip() else None

    def _float(v: str) -> Optional[float]:
        return float(v) if v and v.strip() else None

    return PropertyListing(
        listing_id         = row["listing_id"],
        complex_name       = row.get("complex_name") or None,
        address            = row["address"],
        region             = row.get("region") or None,
        property_type      = row["property_type"],
        area_m2            = _float(row.get("area_m2", "")),
        asking_price       = int(row["asking_price"]),
        floor              = _int(row.get("floor", "")),
        built_year         = _int(row.get("built_year", "")),
        lat                = _float(row.get("lat", "")),
        lng                = _float(row.get("lng", "")),
        station_distance_m = _int(row.get("station_distance_m", "")),
        school_distance_m  = _int(row.get("school_distance_m", "")),
        deposit_price      = _int(row.get("deposit_price", "")),
        maintenance_fee    = _int(row.get("maintenance_fee", "")),
        description        = row.get("description") or None,
    )


@lru_cache(maxsize=1)
def _load_listings() -> list[PropertyListing]:
    """
    CSV를 한 번만 파싱해 캐시한다.
    테스트에서 강제 리로드가 필요하면 _load_listings.cache_clear() 를 호출한다.
    """
    if not os.path.exists(_DATA_PATH):
        raise FileNotFoundError(
            f"샘플 매물 데이터 없음: {_DATA_PATH}\n"
            "data/sample_listings.csv 파일을 확인하세요."
        )

    listings = []
    with open(_DATA_PATH, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                listings.append(_row_to_listing(row))
            except Exception as e:
                print(f"[listing_tool] 행 파싱 오류 ({row.get('listing_id', '?')}): {e}")
    return listings


# ─────────────────────────────────────────
#  필터 함수
# ─────────────────────────────────────────

def _match_region(listing: PropertyListing, region: Optional[str]) -> bool:
    if not region:
        return True
    if not listing.region:
        return False
    return region in listing.region or listing.region in region


def _match_property_type(listing: PropertyListing, property_type: Optional[str]) -> bool:
    if not property_type:
        return True
    return listing.property_type == property_type


def _match_budget(
    listing: PropertyListing,
    budget_min: Optional[int],
    budget_max: Optional[int],
) -> bool:
    if budget_min is not None and listing.asking_price < budget_min:
        return False
    if budget_max is not None and listing.asking_price > budget_max:
        return False
    return True


def _match_area(listing: PropertyListing, area_m2: Optional[float]) -> bool:
    """area_m2 ± AREA_TOLERANCE 범위 내 매물만 통과. 면적 정보 없는 매물은 제외하지 않는다."""
    if not area_m2:
        return True
    if not listing.area_m2:
        return True
    lo = area_m2 * (1 - _AREA_TOLERANCE)
    hi = area_m2 * (1 + _AREA_TOLERANCE)
    return lo <= listing.area_m2 <= hi


# ─────────────────────────────────────────
#  공개 인터페이스
# ─────────────────────────────────────────

def search_listings(query: PropertyQuery, limit: int = 20) -> list[PropertyListing]:
    """
    PropertyQuery 조건에 맞는 매물을 샘플 CSV에서 필터링해 반환.

    필터 기준 (모두 선택적):
      region        : 포함 관계 문자열 매칭 ("마포구" → 마포구 매물)
      property_type : 정확 매칭 (주거용 / 상업용 / ...)
      budget_min    : asking_price >= budget_min  [원 단위]
      budget_max    : asking_price <= budget_max  [원 단위]
      area_m2       : ±30% 허용 범위 내 면적

    정렬: asking_price 오름차순
    반환: 최대 limit 건

    ⚠️  반환 매물은 샘플 데이터이며 실제 거래 정보가 아니다.
    """
    all_listings = _load_listings()

    filtered = [
        l for l in all_listings
        if _match_region(l, query.region)
        and _match_property_type(l, query.property_type)
        and _match_budget(l, query.budget_min, query.budget_max)
        and _match_area(l, query.area_m2)
    ]

    filtered.sort(key=lambda l: l.asking_price)
    return filtered[:limit]


def count_listings() -> int:
    """로드된 샘플 매물 총 건수 반환."""
    return len(_load_listings())
