"""
bok_rates.py — 한국은행 ECOS 금리 조회

시뮬레이션의 금리 기본값을 하드코딩(4.0%) 대신
실제 예금은행 주택담보대출 가중평균금리(신규취급액)로 제공한다.

.env: ECOS_API_KEY  (ecos.bok.or.kr → OpenAPI 신청, 즉시 발급)
  키가 없으면 "sample" 키로 시도(한은 제공 테스트 키, 호출 제한 있음),
  그마저 실패하면 DEFAULT_MORTGAGE_RATE 폴백.

통계: 121Y006 예금은행 대출금리(신규취급액) / BECBLA0302 주택담보대출 (월, 연리%)
  — 라이브 검증됨 (2026-01: 4.29%)
"""

from __future__ import annotations

import os
from datetime import datetime

import requests
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

ECOS_API_KEY = os.getenv("ECOS_API_KEY", "") or "sample"

ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

STAT_CODE = os.getenv("ECOS_MORTGAGE_STAT", "121Y006")      # 예금은행 대출금리(신규)
ITEM_CODE = os.getenv("ECOS_MORTGAGE_ITEM", "BECBLA0302")   # 주택담보대출

DEFAULT_MORTGAGE_RATE = 4.0    # 조회 실패 시 폴백 (%)

_CACHE_TTL = 60 * 60 * 24      # 24시간


def _shift_ym(ym: str, months: int) -> str:
    d = datetime.strptime(ym, "%Y%m")
    total = d.year * 12 + (d.month - 1) + months
    return f"{total // 12}{total % 12 + 1:02d}"


def _fetch_latest_rate() -> dict | None:
    """최근 6개월 조회 → 가장 최신 값. 실패 시 None."""
    now = datetime.now().strftime("%Y%m")
    start = _shift_ym(now, -6)
    url = (f"{ECOS_BASE}/{ECOS_API_KEY}/json/kr/1/10"
           f"/{STAT_CODE}/M/{start}/{now}/{ITEM_CODE}")
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        rows = (data.get("StatisticSearch") or {}).get("row") or []
        if not rows:
            code = (data.get("RESULT") or {}).get("CODE", "?")
            print(f"[bok] 금리 조회 실패: {code}")
            return None
        latest = max(rows, key=lambda r: r.get("TIME", ""))
        return {
            "rate":   float(latest["DATA_VALUE"]),
            "ym":     latest["TIME"],
            "source": f"한국은행 ECOS — 예금은행 주택담보대출 금리(신규취급액, {latest['TIME'][:4]}.{latest['TIME'][4:]})",
        }
    except Exception as e:
        print(f"[bok] 금리 조회 오류: {e}")
        return None


def get_mortgage_rate() -> dict:
    """
    최신 주담대 평균금리 (24시간 캐시).

    반환: {rate, ym, source, is_live}
      is_live=False → 폴백 기본값 (ECOS 미연결)
    """
    from cache_db import cache_get, cache_set

    cached = cache_get(namespace="bok_rate", stat=STAT_CODE, item=ITEM_CODE)
    if cached is not None:
        return cached

    live = _fetch_latest_rate()
    if live:
        result = {**live, "is_live": True}
        cache_set(result, ttl=_CACHE_TTL, namespace="bok_rate", stat=STAT_CODE, item=ITEM_CODE)
        return result

    return {"rate": DEFAULT_MORTGAGE_RATE, "ym": "",
            "source": "기본값 (ECOS 미연결)", "is_live": False}


if __name__ == "__main__":
    key_state = "설정됨" if os.getenv("ECOS_API_KEY") else "미설정 → sample 키 시도"
    print(f"ECOS_API_KEY: {key_state}")
    r = get_mortgage_rate()
    print(f"주담대 금리: {r['rate']}% ({r['source']})")
    print("✅ 라이브" if r["is_live"] else "⚠️ 폴백 기본값 — .env에 ECOS_API_KEY 추가 권장")
