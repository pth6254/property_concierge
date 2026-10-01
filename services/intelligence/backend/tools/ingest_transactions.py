"""국토부 매매 실거래가를 지역·원천·거래월 단위로 증분 수집한다.

완료 이력은 ``ingest_log``에 남는다. 완료된 월은 TTL 내에서만 건너뛰고,
정정·해제 가능성이 있는 월은 TTL 이후 다시 조회한다. ``--force``는 즉시 재수집용이다.
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from sqlalchemy import select

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_TOOLS_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _path in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

import transaction_store
from cache_db import get_lawd_code, list_region_codes
from db.base import session_scope
from db.models import LegalRegion
from price_engine import MOLIT_API_KEY, MOLIT_BASE_URL, MOLIT_ENDPOINTS, _endpoint_name, _fetch_one_month_api

VALID_CATEGORIES = ["주거용", "상업용", "업무용", "산업용", "토지"]


def _endpoints_for(categories: list[str]) -> list[tuple[str, str]]:
    """동일한 국토부 원천을 유형명만 달리해 중복 수집하지 않는다."""
    result, seen_urls = [], set()
    for (category, _detail), path in MOLIT_ENDPOINTS.items():
        if category not in categories:
            continue
        url = MOLIT_BASE_URL + path
        if url not in seen_urls:
            seen_urls.add(url)
            result.append((category, url))
    return result


def _month_range(start_ym: str, end_ym: str) -> list[str]:
    for value in (start_ym, end_ym):
        datetime.strptime(value, "%Y%m")
    if start_ym > end_ym:
        raise ValueError("시작월은 종료월보다 늦을 수 없습니다")
    year, month = int(start_ym[:4]), int(start_ym[4:])
    result = []
    while f"{year:04d}{month:02d}" <= end_ym:
        result.append(f"{year:04d}{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return result


def _recent_months(count: int) -> list[str]:
    now = datetime.now()
    absolute = now.year * 12 + now.month - 1
    return [f"{(absolute-o)//12:04d}{(absolute-o)%12+1:02d}" for o in range(count - 1, -1, -1)]


def _regions_for_sido(sido: str) -> list[tuple[str, str]]:
    with session_scope() as session:
        rows = session.execute(
            select(LegalRegion.full_name, LegalRegion.lawd_code).where(
                LegalRegion.is_active.is_(True), LegalRegion.level == "sigungu",
                LegalRegion.full_name.like(f"{sido} %"), LegalRegion.lawd_code.is_not(None),
            ).order_by(LegalRegion.sort_order, LegalRegion.code)
        ).all()
    return [(name, code) for name, code in rows if code]


def _ingest_one(job: tuple[str, str, str, str, str], safe_key: str, force: bool) -> tuple[str, str]:
    region_name, lawd_cd, category, url, deal_ym = job
    endpoint = _endpoint_name(url)
    if not force and transaction_store.should_skip_batch_month(endpoint, category, lawd_cd, deal_ym):
        return "skipped", ""
    transaction_store.mark_month_started(endpoint, category, lawd_cd, deal_ym)
    try:
        parsed = _fetch_one_month_api(url, safe_key, lawd_cd, deal_ym, category)
        if parsed is None:
            transaction_store.mark_month_failed(endpoint, category, lawd_cd, deal_ym, "API 응답 실패")
            return "failed", f"{region_name} {endpoint} {deal_ym}"
        transaction_store.put_month(endpoint, category, lawd_cd, deal_ym, parsed)
        return "fetched", ""
    except Exception as exc:
        transaction_store.mark_month_failed(endpoint, category, lawd_cd, deal_ym, str(exc))
        return "failed", f"{region_name} {endpoint} {deal_ym}: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="국토부 매매 실거래가 증분 수집")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sido", help="광역자치단체의 모든 시군구 (예: 서울특별시)")
    group.add_argument("--regions", help="쉼표로 구분한 기존 등록 지역명")
    group.add_argument("--all", action="store_true", help="기존 등록 지역 전체")
    parser.add_argument("--months", type=int, default=12, help="현재월을 포함한 최근 개월 수")
    parser.add_argument("--from", dest="from_ym", help="수집 시작월 YYYYMM (--to와 함께 사용)")
    parser.add_argument("--to", dest="to_ym", help="수집 종료월 YYYYMM")
    parser.add_argument("--categories", default=",".join(VALID_CATEGORIES))
    parser.add_argument("--force", action="store_true", help="완료된 월도 다시 수집")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--yes", "-y", action="store_true")
    args = parser.parse_args()

    if not MOLIT_API_KEY:
        sys.exit("MOLIT_API_KEY가 설정되지 않았습니다")
    if bool(args.from_ym) != bool(args.to_ym):
        sys.exit("--from과 --to는 함께 지정해야 합니다")
    if args.months <= 0:
        sys.exit("--months는 1 이상이어야 합니다")

    if args.sido:
        regions = _regions_for_sido(args.sido.strip())
    elif args.all:
        regions = [(r["region_name"], r["lawd_code"]) for r in list_region_codes()]
    else:
        regions = []
        for name in args.regions.split(","):
            name = name.strip()
            code = get_lawd_code(name)
            if code:
                regions.append((name, code))
            else:
                print(f"경고: '{name}' 지역코드가 없어 건너뜁니다")
    if not regions:
        sys.exit("수집할 지역이 없습니다. 법정동 마스터 동기화 여부를 확인하세요")

    categories = [value.strip() for value in args.categories.split(",") if value.strip()]
    invalid = [value for value in categories if value not in VALID_CATEGORIES]
    if invalid:
        sys.exit(f"잘못된 유형: {invalid}")
    endpoints = _endpoints_for(categories)
    deal_months = _month_range(args.from_ym, args.to_ym) if args.from_ym else _recent_months(args.months)
    jobs = [(name, code, category, url, ym) for name, code in regions for category, url in endpoints for ym in deal_months]

    print(f"수집 계획: {len(regions)}개 지역 × {len(endpoints)}개 원천 × {len(deal_months)}개월 = {len(jobs)}개 작업")
    print(f"수집 기간: {deal_months[0]} ~ {deal_months[-1]}")
    print("완료 작업은 TTL 내에서 건너뛰며 만료·실패·중단 작업을 다시 조회합니다.")
    if not args.yes and input("계속할까요? [y/N] ").strip().lower() != "y":
        sys.exit("중단")

    safe_key = MOLIT_API_KEY.replace("+", "%2B").replace("=", "%3D")
    counts = {"fetched": 0, "skipped": 0, "failed": 0}
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(_ingest_one, job, safe_key, args.force) for job in jobs]
        for done, future in enumerate(as_completed(futures), 1):
            outcome, error = future.result()
            counts[outcome] += 1
            if error:
                failures.append(error)
            if done % 25 == 0 or done == len(jobs):
                print(f"진행 {done}/{len(jobs)} · 수집 {counts['fetched']} · 건너뜀 {counts['skipped']} · 실패 {counts['failed']}")
    print(f"완료: 수집 {counts['fetched']} · 건너뜀 {counts['skipped']} · 실패 {counts['failed']}")
    for failure in failures[:10]:
        print(f"  실패: {failure}")
    print(f"저장소: {transaction_store.store_stats()}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
