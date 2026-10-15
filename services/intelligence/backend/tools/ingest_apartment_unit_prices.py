"""공동주택 공시가격(호별) 수집 — VWorld getApartHousingPriceAttr.

아파트 실거래가 있는 필지(시군구·법정동·지번)를 PNU로 바꿔 기준연도별로 수집한다. 이전 공공데이터포털 공시가격 API
(PblntfPublicWrtPrcInfo)는 폐기됐다(2026-10-15 확인). VWorld 일일 호출 한도를 알 수 없어 실행마다 호출 상한(--max-calls)을 두고,
필지·연도별 상태(apartment_unit_price_fetches)로 끝난 것은 다시 부르지 않고 이어서 수집한다. 키·키 포함 URL은 출력하지 않는다.

python -m backend.tools.ingest_apartment_unit_prices --sido 서울특별시 --years 2023,2024,2025,2026 --max-calls 8000
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

VWORLD_URL = "https://api.vworld.kr/ned/data/getApartHousingPriceAttr"
PAGE_SIZE = 1000


def to_pnu(ld_code: str, jibun: str) -> str | None:
    """법정동 코드(10) + 산 여부(1 일반, 2 산) + 본번(4) + 부번(4). 형식이 다르면 None."""
    text = (jibun or "").strip()
    mountain = text.startswith("산")
    text = text.removeprefix("산").strip()
    match = re.fullmatch(r"(\d{1,4})(?:-(\d{1,4}))?", text)
    if not ld_code or len(ld_code) != 10 or not match:
        return None
    return f"{ld_code}{'2' if mountain else '1'}{int(match.group(1)):04d}{int(match.group(2) or 0):04d}"


def parcels(sido: str) -> list[str]:
    """아파트 실거래가 있는 필지의 PNU 목록. 법정동 이름은 같은 시군구 안에서만 코드로 바꾼다."""
    from sqlalchemy import text
    from db.base import get_engine
    with get_engine().connect() as connection:
        rows = connection.execute(text("""
            SELECT DISTINCT t.jibun, r.code
            FROM transactions t
            JOIN legal_regions r ON r.lawd_code = t.lawd_cd AND r.name = t.dong AND r.level = 'eup_myeon_dong' AND r.is_active
            WHERE t.endpoint = 'RTMSDataSvcAptTrade' AND t.jibun IS NOT NULL AND t.jibun <> '' AND r.full_name LIKE :sido
        """), {"sido": f"{sido} %"}).all()
    return sorted({pnu for jibun, code in rows if (pnu := to_pnu(code, jibun))})


def pending(pnus: list[str], years: list[int], force: bool) -> list[tuple[str, int]]:
    from sqlalchemy import text
    from db.base import get_engine
    if force:
        return [(p, y) for y in years for p in pnus]
    with get_engine().connect() as connection:
        finished = {(p, y) for p, y in connection.execute(text(
            "SELECT pnu, stdr_year FROM apartment_unit_price_fetches WHERE status IN ('done', 'empty')")).all()}
    # 최근 연도부터 받는다. 서비스 보정에는 최신 공시가격이 먼저 필요하다.
    return [(p, y) for y in sorted(years, reverse=True) for p in pnus if (p, y) not in finished]


def fetch(pnu: str, year: int, key: str, domain: str, session=requests) -> tuple[list[dict], int, int]:
    """한 필지·연도의 모든 쪽. (행, 전체 건수, 호출 수). 오류 응답은 예외로 올린다(메시지에 키를 넣지 않는다)."""
    rows, page, calls, total = [], 1, 0, 0
    while True:
        response = session.get(VWORLD_URL, params={"key": key, "domain": domain, "pnu": pnu, "stdrYear": str(year),
                                                   "format": "json", "numOfRows": str(PAGE_SIZE), "pageNo": str(page)}, timeout=30)
        calls += 1
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        try:
            body = response.json().get("apartHousingPrices") or {}
        except ValueError:
            raise RuntimeError("JSON이 아닌 응답") from None
        if body.get("resultCode") and str(body.get("resultCode")) not in ("", "0", "INFO-000"):
            raise RuntimeError(f"결과 코드 {body.get('resultCode')}")
        total = int(body.get("totalCount") or 0)
        items = body.get("field") or []
        rows += items
        if not items or len(rows) >= total:
            return rows, total, calls
        page += 1


def _row(item: dict, pnu: str, year: int, now: float) -> dict | None:
    try:
        price = int(str(item.get("pblntfPc") or "").replace(",", ""))
    except ValueError:
        return None
    if price <= 0:
        return None
    try:
        area = float(item.get("prvuseAr")) if item.get("prvuseAr") not in (None, "") else None
    except ValueError:
        area = None
    return {"pnu": pnu, "stdr_year": year, "aphus_code": str(item.get("aphusCode") or ""), "aphus_name": item.get("aphusNm"),
            "dong_name": str(item.get("dongNm") or "").strip(), "ho_name": str(item.get("hoNm") or "").strip(),
            "floor_name": str(item.get("floorNm") or "").strip() or None, "exclusive_area": area, "official_price": price,
            "ld_code": item.get("ldCode"), "lot_number": item.get("mnnmSlno"), "source_updated": item.get("lastUpdtDt"), "fetched_at": now}


def store(pnu: str, year: int, items: list[dict], total: int, error: str | None = None) -> int:
    from sqlalchemy import text
    from db.base import get_engine
    now = time.time()
    rows = [r for r in (_row(item, pnu, year, now) for item in items) if r and r["aphus_code"]]
    with get_engine().begin() as connection:
        if rows:
            connection.execute(text("""
                INSERT INTO apartment_unit_prices (pnu, stdr_year, aphus_code, aphus_name, dong_name, ho_name, floor_name, exclusive_area,
                    official_price, ld_code, lot_number, source_updated, fetched_at)
                VALUES (:pnu, :stdr_year, :aphus_code, :aphus_name, :dong_name, :ho_name, :floor_name, :exclusive_area,
                    :official_price, :ld_code, :lot_number, :source_updated, :fetched_at)
                ON CONFLICT (pnu, stdr_year, aphus_code, dong_name, ho_name) DO UPDATE SET official_price = EXCLUDED.official_price,
                    floor_name = EXCLUDED.floor_name, exclusive_area = EXCLUDED.exclusive_area, aphus_name = EXCLUDED.aphus_name,
                    source_updated = EXCLUDED.source_updated, fetched_at = EXCLUDED.fetched_at
            """), rows)
        status = "failed" if error else "done" if rows else "empty"
        connection.execute(text("""
            INSERT INTO apartment_unit_price_fetches (pnu, stdr_year, status, total_count, row_count, fetched_at, error_message)
            VALUES (:pnu, :year, :status, :total, :count, :now, :error)
            ON CONFLICT (pnu, stdr_year) DO UPDATE SET status = EXCLUDED.status, total_count = EXCLUDED.total_count,
                row_count = EXCLUDED.row_count, fetched_at = EXCLUDED.fetched_at, error_message = EXCLUDED.error_message
        """), {"pnu": pnu, "year": year, "status": status, "total": total, "count": len(rows), "now": now, "error": error})
    return len(rows)


def run(jobs: list[tuple[str, int]], key: str, domain: str, max_calls: int, workers: int = 4, fetcher=fetch, saver=store) -> dict:
    """호출 상한 안에서 필지·연도를 수집한다. 상한에 닿으면 남은 작업은 다음 실행으로 넘긴다."""
    counts = {"done": 0, "empty": 0, "failed": 0, "calls": 0, "rows": 0, "remaining": 0}
    index = 0
    while index < len(jobs) and counts["calls"] < max_calls:
        # 한 묶음에서 쓸 수 있는 호출 수만큼만 보낸다(필지 한 곳은 보통 1~3쪽).
        batch = jobs[index:index + max(1, min(workers * 4, max_calls - counts["calls"]))]
        index += len(batch)
        def one(job):
            pnu, year = job
            try:
                items, total, calls = fetcher(pnu, year, key, domain)
                return job, items, total, calls, None
            except Exception as exc:
                return job, [], 0, 1, f"{type(exc).__name__}: {exc}"[:300]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for (pnu, year), items, total, calls, error in executor.map(one, batch):
                counts["calls"] += calls
                stored = saver(pnu, year, items, total, error)
                counts["rows"] += stored
                counts["failed" if error else "done" if stored else "empty"] += 1
        print(f"진행 {index}/{len(jobs)} · 호출 {counts['calls']} · 저장 {counts['rows']}행 · 실패 {counts['failed']}", flush=True)
    counts["remaining"] = len(jobs) - index
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="공동주택 공시가격(호별) 수집 — VWorld")
    parser.add_argument("--sido", default="서울특별시")
    this_year = time.localtime().tm_year
    # 기본은 올해와 이전 3년: 학습 거래(최근 3년)의 거래 연도 공시가격과 서비스용 최신 공시가격.
    parser.add_argument("--years", default=",".join(str(y) for y in range(this_year - 3, this_year + 1)))
    parser.add_argument("--max-calls", type=int, default=int(os.getenv("APT_UNIT_PRICE_MAX_CALLS", "8000")))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true", help="끝난 필지·연도도 다시 수집")
    parser.add_argument("--limit", type=int, default=0, help="시험용: 앞에서부터 이만큼만")
    args = parser.parse_args()
    key, domain = os.getenv("VWORLD_API_KEY", "").strip(), os.getenv("VWORLD_DOMAIN", "localhost").strip()
    if not key:
        sys.exit("VWORLD_API_KEY가 설정되지 않았습니다")
    years = [int(y) for y in args.years.split(",") if y.strip()]
    pnus = parcels(args.sido)
    jobs = pending(pnus, years, args.force)
    if args.limit:
        jobs = jobs[:args.limit]
    print(f"필지 {len(pnus)}곳 × {len(years)}개 연도 · 남은 작업 {len(jobs)} · 호출 상한 {args.max_calls}", flush=True)
    result = run(jobs, key, domain, args.max_calls, args.workers)
    print(f"완료: {result}", flush=True)


if __name__ == "__main__":
    main()
