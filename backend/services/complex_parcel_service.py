"""이전 적재에서 누락한 지번만 공식 원문으로 보완하며 거래 금액·행은 유지한다."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import re

from sqlalchemy import select, update

from cache_db import cache_get, cache_set
from db.base import session_scope
from db.models import Transaction


def normalize_parcel(value: str | None) -> str:
    match = re.fullmatch(r"(산)?\s*(\d+)(?:-(\d+))?", (value or "").strip())
    if not match:
        return ""
    mountain, main, sub = match.groups()
    return ("산 " if mountain else "") + str(int(main)) + (f"-{int(sub)}" if sub and int(sub) else "")


def _parcel_index(samples: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], set[str]] = {}
    for sample in samples:
        if sample.get("is_cancelled"):
            continue
        parcel = normalize_parcel(sample.get("jibun"))
        dong, name = (sample.get("dong") or "").strip(), (sample.get("apt_name") or "").strip()
        if parcel and dong and name:
            groups.setdefault((dong, name), set()).add(parcel)
    return [{"dong": dong, "name": name, "jibuns": sorted(parcels)}
            for (dong, name), parcels in groups.items()]


def official_month_parcels(lawd_code: str, month: str, *, force: bool = False) -> list[dict] | None:
    from price_engine import MOLIT_API_KEY, MOLIT_BASE_URL, MOLIT_ENDPOINTS, _fetch_one_month_api
    if not MOLIT_API_KEY or not re.fullmatch(r"\d{5}", lawd_code) or not re.fullmatch(r"\d{6}", month):
        return None
    key = {"lawd_code": lawd_code, "month": month}
    cached = None if force else cache_get("official_complex_parcels_v1", **key)
    if cached is not None:
        return cached
    url = MOLIT_BASE_URL + MOLIT_ENDPOINTS[("주거용", "아파트")]
    safe_key = MOLIT_API_KEY.replace("+", "%2B").replace("=", "%3D")
    samples = _fetch_one_month_api(url, safe_key, lawd_code, month, "주거용")
    if samples is None:
        return None
    index = _parcel_index(samples)
    # 과거 거래를 재적재하면 가격·해제 상태까지 달라질 수 있어 지번 컬럼만 보완한다.
    with session_scope() as session:
        for item in index:
            if len(item["jibuns"]) == 1:
                session.execute(update(Transaction).where(
                    Transaction.endpoint == "RTMSDataSvcAptTrade", Transaction.category == "주거용",
                    Transaction.lawd_cd == lawd_code, Transaction.deal_ym == month,
                    Transaction.dong == item["dong"], Transaction.apt_name == item["name"],
                    Transaction.jibun.is_(None) | (Transaction.jibun == ""),
                ).values(jibun=item["jibuns"][0]))
    cache_set(index, ttl=86400 * 7, namespace="official_complex_parcels_v1", **key)
    return index


def known_parcels(lawd_code: str, dong: str, name: str) -> list[str]:
    with session_scope() as session:
        values = session.scalars(select(Transaction.jibun).where(
            Transaction.endpoint == "RTMSDataSvcAptTrade", Transaction.lawd_cd == lawd_code,
            Transaction.dong == dong, Transaction.apt_name == name,
            Transaction.is_cancelled.is_(False), Transaction.jibun.is_not(None),
        ).distinct())
        return sorted({parcel for value in values if (parcel := normalize_parcel(value))})


def attach_official_parcels(results: list[dict], lawd_code: str) -> None:
    pending = []
    for item in results:
        parcels = item.get("official_jibuns") or known_parcels(lawd_code, item["dong"], item["complex_name"])
        item["official_jibuns"] = parcels
        if not parcels and re.fullmatch(r"\d{6}", item.get("last_deal_ym", "")):
            pending.append(item)
    months = sorted({item["last_deal_ym"] for item in pending})
    # 단지마다 같은 월을 다시 내려받지 않도록 지역·월별로 한 번만 조회한다.
    with ThreadPoolExecutor(max_workers=2) as pool:
        indexes = dict(zip(months, pool.map(lambda month: official_month_parcels(lawd_code, month), months)))
    for item in pending:
        records = indexes.get(item["last_deal_ym"]) or []
        found = next((record for record in records
                      if record["dong"] == item["dong"] and record["name"] == item["complex_name"]), None)
        if found:
            item["official_jibuns"] = found["jibuns"]
