"""동일 단지 전세 실거래와 매매 실거래를 대조한 전세가율 참고. 가격 추정·비교에는 쓰지 않는다."""
from datetime import date
from statistics import median
import json
import os
import xml.etree.ElementTree as ET

import requests

from backend.valuation.policy import reference_context

RENT_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"
WINDOW_MONTHS = 6
AREA_TOLERANCE = .10
MIN_PER_SIDE = 3
CACHE_SECONDS = 60 * 60 * 12


def _int(text):
    try:
        return int(str(text or "").replace(",", "").strip() or 0)
    except ValueError:
        return 0


def fetch_month(lawd_code, deal_ym):
    """전월세 신고를 읽어 전세(월세 0)만 반환한다. 실패는 None이며 캐시하지 않는다. 금액은 원."""
    key = os.getenv("MOLIT_API_KEY", "")
    if not key or not lawd_code:
        return None
    cache_key = f"jeonse:v1:{lawd_code}:{deal_ym}"
    try:
        from db.redis_client import get_redis
        cached = get_redis().get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    # 원문 키의 +, = 를 보존해 한 번만 인코딩한다(AGENTS 2-13과 같은 이유).
    safe_key = key.replace("+", "%2B").replace("=", "%3D")
    rows, page = [], 1
    try:
        while True:
            res = requests.get(f"{RENT_URL}?serviceKey={safe_key}&LAWD_CD={lawd_code}&DEAL_YMD={deal_ym}&numOfRows=1000&pageNo={page}", timeout=20)
            res.raise_for_status()
            root = ET.fromstring(res.text)
            code = root.findtext(".//resultCode", "")
            if code and code.lstrip("0"):
                return None
            items = root.findall(".//item")
            for item in items:
                deposit, monthly = _int(item.findtext("deposit")), _int(item.findtext("monthlyRent"))
                try:
                    area = float(item.findtext("excluUseAr", "").strip())
                except ValueError:
                    continue
                if monthly != 0 or deposit <= 0 or area <= 0:
                    continue  # 월세·반전세는 전세가율 계산에서 제외한다.
                rows.append({"apt_name": item.findtext("aptNm", "").strip(), "dong": item.findtext("umdNm", "").strip(),
                    "area_sqm": area, "deposit_won": deposit * 10_000, "floor": item.findtext("floor", "").strip(),
                    "deal_year": item.findtext("dealYear", "").strip(), "deal_month": item.findtext("dealMonth", "").strip(),
                    "deal_day": item.findtext("dealDay", "").strip(), "contract_type": item.findtext("contractType", "").strip()})
            if page * 1000 >= _int(root.findtext(".//totalCount", "0")) or not items:
                break
            page += 1
    except Exception as exc:  # requests 예외 문자열에는 serviceKey가 들어갈 수 있다.
        print(f"[jeonse] {deal_ym} 조회 실패: {type(exc).__name__}")
        return None
    try:
        from db.redis_client import get_redis
        get_redis().setex(cache_key, CACHE_SECONDS, json.dumps(rows))
    except Exception:
        pass
    return rows


def _months(as_of, count):
    base = as_of.year * 12 + as_of.month - 1
    return [f"{(base - i) // 12:04d}{(base - i) % 12 + 1:02d}" for i in range(count)]


def build(price_data, target, as_of, fetch=fetch_month):
    """같은 단지·전용면적 ±10%·최근 6개월의 전세와 매매 ㎡당 중앙값을 대조한다. 조회 불가면 None."""
    from backend.comparable_matching import normalized_name
    name = price_data.get("apt_name_matched") or ""
    lawd = price_data.get("target_sigungu_code") or ""
    if not name or not lawd or not target.get("area_sqm"):
        return None
    index = as_of.year * 12 + as_of.month - 1 - WINDOW_MONTHS
    start = date(index // 12, index % 12 + 1, 1)
    leases, failed = [], 0
    for ym in _months(as_of, WINDOW_MONTHS + 1):
        rows = fetch(lawd, ym)
        if rows is None:
            failed += 1
            continue
        for row in rows:
            try:
                day = date(int(row["deal_year"]), int(row["deal_month"]), int(row["deal_day"]))
            except (ValueError, KeyError):
                continue
            if (normalized_name(row["apt_name"]) == normalized_name(name) and start <= day <= as_of
                    and abs(row["area_sqm"] / target["area_sqm"] - 1) <= AREA_TOLERANCE + 1e-6):
                leases.append({"deal_date": day.isoformat(), "area_sqm": row["area_sqm"], "deposit_won": row["deposit_won"],
                    "deposit_per_sqm_won": round(row["deposit_won"] / row["area_sqm"]), "renewal": row["contract_type"] == "갱신"})
    if failed == WINDOW_MONTHS + 1:
        return None
    sales = reference_context(price_data, target, as_of, months=WINDOW_MONTHS, tolerance=AREA_TOLERANCE, limit=1000)
    sale_unit = [t["price_per_sqm_won"] for t in sales["trades"]]
    lease_unit = [t["deposit_per_sqm_won"] for t in leases]
    sufficient = len(lease_unit) >= MIN_PER_SIDE and len(sale_unit) >= MIN_PER_SIDE
    ratio = round(median(lease_unit) / median(sale_unit) * 100, 1) if lease_unit and sale_unit else None
    leases.sort(key=lambda row: row["deal_date"], reverse=True)
    return {"window_months": WINDOW_MONTHS, "area_tolerance_pct": round(AREA_TOLERANCE * 100), "complex_name": name,
        "lease_count": len(lease_unit), "sale_count": len(sale_unit), "renewal_count": sum(1 for row in leases if row["renewal"]),
        "lease_per_sqm_median_won": round(median(lease_unit)) if lease_unit else None,
        "sale_per_sqm_median_won": round(median(sale_unit)) if sale_unit else None,
        "ratio_pct": ratio, "sufficient": sufficient, "missing_months": failed, "leases": leases[:10]}
