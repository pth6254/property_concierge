"""행정안전부 10자리 법정동코드 전국 동기화.

현행 법정동 전체를 시도→시군구→읍면동→리 계층으로 ``legal_regions``에
업서트한다. 목록 API는 폐지일을 제공하지 않으므로 전체 조회가 성공한 뒤
이번 응답에서 사라진 기존 코드만 비활성화하고 폐지일은 추정해 채우지 않는다.

사용:
  python backend/tools/sync_legal_regions.py --dry-run
  python backend/tools/sync_legal_regions.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterable
from typing import Any

import requests
from dotenv import find_dotenv, load_dotenv
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_TOOLS_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _path in (_BACKEND_DIR, _PROJECT_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

load_dotenv(find_dotenv())

from db.base import init_db, session_scope
from db.models import LegalRegion

API_URL = "https://apis.data.go.kr/1741000/StanReginCd/getStanReginCdList"
DEFAULT_PAGE_SIZE = 1000
_UPSERT_BATCH_SIZE = 1000


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_date(value: Any) -> str | None:
    text = _text(value).replace("-", "")
    return text if len(text) == 8 and text.isdigit() else None


def _level(row: dict[str, Any]) -> str:
    if _text(row.get("ri_cd")) != "00":
        return "ri"
    if _text(row.get("umd_cd")) != "000":
        return "eup_myeon_dong"
    if _text(row.get("sgg_cd")) != "000":
        return "sigungu"
    return "sido"


def _fallback_depth(level: str) -> int:
    return {"sido": 1, "sigungu": 2, "eup_myeon_dong": 3, "ri": 4}[level]


def parse_row(row: dict[str, Any], synced_at: float) -> dict[str, Any]:
    """공식 API 원천 행을 DB 레코드로 정규화한다."""
    code = _text(row.get("region_cd"))
    if len(code) != 10 or not code.isdigit():
        raise ValueError(f"잘못된 10자리 법정동코드: {code!r}")

    full_name = " ".join(_text(row.get("locatadd_nm")).split())
    if not full_name:
        raise ValueError(f"지역명이 없는 법정동코드: {code}")

    parent_code = _text(row.get("locathigh_cd")) or None
    if parent_code == code or parent_code == "0000000000":
        parent_code = None
    if parent_code is not None and (len(parent_code) != 10 or not parent_code.isdigit()):
        raise ValueError(f"잘못된 상위 법정동코드: {parent_code!r}")

    level = _level(row)
    sigungu_code = _text(row.get("sgg_cd")).zfill(3)
    return {
        "code": code,
        "parent_code": parent_code,
        "sido_code": _text(row.get("sido_cd")).zfill(2),
        "sigungu_code": sigungu_code,
        "eup_myeon_dong_code": _text(row.get("umd_cd")).zfill(3),
        "ri_code": _text(row.get("ri_cd")).zfill(2),
        "name": _text(row.get("locallow_nm")) or full_name.split()[-1],
        "full_name": full_name,
        "level": level,
        "depth": _fallback_depth(level),
        "lawd_code": code[:5] if sigungu_code != "000" else None,
        "resident_code": _text(row.get("locatjumin_cd")),
        "cadastral_code": _text(row.get("locatjijuk_cd")),
        "sort_order": int(row.get("locat_order") or 0),
        "remarks": _text(row.get("locat_rm")),
        "effective_date": _optional_date(row.get("adpt_de")),
        "abolished_date": None,
        "is_active": True,
        "synced_at": synced_at,
    }


def assign_depths(records: list[dict[str, Any]]) -> None:
    """일반시→일반구처럼 같은 코드 레벨이 중첩되는 경우도 실제 부모로 계산한다."""
    by_code = {record["code"]: record for record in records}
    resolved: dict[str, int] = {}

    def resolve(code: str, visiting: set[str]) -> int:
        if code in resolved:
            return resolved[code]
        record = by_code[code]
        parent = record["parent_code"]
        if parent in visiting:
            raise ValueError(f"법정동 상위코드 순환 참조: {code} -> {parent}")
        if not parent or parent not in by_code:
            depth = _fallback_depth(record["level"])
        else:
            depth = resolve(parent, visiting | {code}) + 1
        resolved[code] = depth
        return depth

    for record in records:
        record["depth"] = resolve(record["code"], set())


def _decode_response(response: requests.Response) -> dict[str, Any]:
    # API가 JSON Content-Type에 문자셋을 명시하지 않아 requests가 한글을
    # ISO-8859-1로 오인할 수 있다. 원본 바이트를 UTF-8로 직접 해석한다.
    return json.loads(response.content.decode("utf-8"))


def fetch_all(api_key: str, page_size: int = DEFAULT_PAGE_SIZE,
              http: requests.Session | None = None) -> list[dict[str, Any]]:
    """페이지 누락 없이 현행 전국 법정동 원천 행을 모두 조회한다."""
    if not api_key:
        raise ValueError("MOIS_REGION_API_KEY 또는 MOLIT_API_KEY가 필요합니다.")
    if page_size < 1 or page_size > 1000:
        raise ValueError("page_size는 1~1000이어야 합니다.")

    client = http or requests.Session()
    rows: list[dict[str, Any]] = []
    page = 1
    total = None

    while total is None or len(rows) < total:
        try:
            response = client.get(
                API_URL,
                params={
                    "serviceKey": api_key,
                    "type": "json",
                    "pageNo": page,
                    "numOfRows": page_size,
                },
                timeout=30,
            )
            response.raise_for_status()
            body = _decode_response(response).get("StanReginCd")
        except (requests.RequestException, UnicodeDecodeError, json.JSONDecodeError) as exc:
            # requests 예외 문자열에는 인증키가 포함된 URL이 들어갈 수 있어 출력하지 않는다.
            raise RuntimeError(
                f"법정동코드 API 요청 실패(page={page}, error={type(exc).__name__})"
            ) from None

        if not body or len(body) < 2:
            raise RuntimeError(f"법정동코드 API 응답 형식 오류(page={page})")
        header = body[0].get("head", [])
        result = next((item.get("RESULT") for item in header if "RESULT" in item), {})
        if result.get("resultCode") != "INFO-0":
            raise RuntimeError(
                f"법정동코드 API 오류(page={page}, code={result.get('resultCode', 'unknown')})"
            )
        if total is None:
            total = int(next(item["totalCount"] for item in header if "totalCount" in item))

        page_rows = body[1].get("row", [])
        if not page_rows and len(rows) < total:
            raise RuntimeError(f"법정동코드 API 페이지가 비어 있습니다(page={page})")
        rows.extend(page_rows)
        page += 1

    if len(rows) != total:
        raise RuntimeError(f"법정동코드 건수 불일치(expected={total}, actual={len(rows)})")
    return rows


def _batches(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def sync_records(records: list[dict[str, Any]]) -> None:
    """전체 동기화를 한 트랜잭션으로 적용해 부분 갱신 상태를 남기지 않는다."""
    if not records:
        raise ValueError("빈 법정동 목록은 동기화할 수 없습니다.")
    init_db()
    with session_scope() as session:
        # 전체 조회 성공 후에만 기존 현행 코드를 비활성화한다. 이어지는 업서트가
        # 실패하면 같은 트랜잭션이 롤백되므로 전부 비활성 상태로 남지 않는다.
        session.execute(update(LegalRegion).where(LegalRegion.is_active.is_(True)).values(is_active=False))
        for batch in _batches(records, _UPSERT_BATCH_SIZE):
            statement = pg_insert(LegalRegion).values(batch)
            excluded = statement.excluded
            statement = statement.on_conflict_do_update(
                index_elements=["code"],
                set_={
                    "parent_code": excluded.parent_code,
                    "sido_code": excluded.sido_code,
                    "sigungu_code": excluded.sigungu_code,
                    "eup_myeon_dong_code": excluded.eup_myeon_dong_code,
                    "ri_code": excluded.ri_code,
                    "name": excluded.name,
                    "full_name": excluded.full_name,
                    "level": excluded.level,
                    "depth": excluded.depth,
                    "lawd_code": excluded.lawd_code,
                    "resident_code": excluded.resident_code,
                    "cadastral_code": excluded.cadastral_code,
                    "sort_order": excluded.sort_order,
                    "remarks": excluded.remarks,
                    "effective_date": excluded.effective_date,
                    # 별도 변경이력에서 확보한 폐지일이 있다면 현행 목록 동기화가 지우지 않는다.
                    "is_active": True,
                    "synced_at": excluded.synced_at,
                },
            )
            session.execute(statement)


def prepare_records(rows: list[dict[str, Any]], synced_at: float | None = None) -> list[dict[str, Any]]:
    stamp = time.time() if synced_at is None else synced_at
    records = [parse_row(row, stamp) for row in rows]
    codes = {record["code"] for record in records}
    if len(codes) != len(records):
        raise ValueError("법정동코드 API 응답에 중복 코드가 있습니다.")
    missing_parents = sorted({
        record["parent_code"]
        for record in records
        if record["parent_code"] and record["parent_code"] not in codes
    })
    if missing_parents:
        preview = ", ".join(missing_parents[:5])
        raise ValueError(f"법정동 상위코드가 전체 목록에 없습니다: {preview}")
    assign_depths(records)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="전국 10자리 법정동코드 동기화")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 조회·검증만 수행")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    args = parser.parse_args()

    api_key = os.getenv("MOIS_REGION_API_KEY", "") or os.getenv("MOLIT_API_KEY", "")
    try:
        rows = fetch_all(api_key, page_size=args.page_size)
        records = prepare_records(rows)
        counts: dict[str, int] = {}
        for record in records:
            counts[record["level"]] = counts.get(record["level"], 0) + 1
        print(f"전국 법정동코드 {len(records):,}건 검증 완료: {counts}")
        if args.dry_run:
            print("dry-run: DB에는 저장하지 않았습니다.")
            return
        sync_records(records)
        print(f"legal_regions 동기화 완료: {len(records):,}건")
    except (ValueError, RuntimeError) as exc:
        # 인증키가 포함될 수 있는 requests 원본 예외는 fetch_all에서 제거한다.
        raise SystemExit(f"법정동코드 동기화 실패: {exc}") from None


if __name__ == "__main__":
    main()
