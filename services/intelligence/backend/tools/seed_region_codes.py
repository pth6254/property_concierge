"""
seed_region_codes.py — 전국 시군구 법정동코드 일괄 등록

행정안전부 표준지역코드(StanReginCd) API에서 전국 시군구(~250개)를 받아
cache_db.region_codes 테이블에 등록한다. (data.go.kr 키 재사용 — MOLIT_API_KEY)

시세추정의 주 경로는 지오코딩 sigungu_cd를 직접 쓰므로 이 시드 없이도
전국이 동작하지만, 지역명 기반 도구(ingest_transactions·backtest_avm·
단지 추천의 지역명 입력)가 미조회 지역을 즉시 쓸 수 있게 해준다.

사용:
  python backend/tools/seed_region_codes.py
"""

from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv, find_dotenv

_TOOLS_DIR    = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_TOOLS_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

load_dotenv(find_dotenv())

from cache_db import add_region_code, init_cache_db, list_region_codes

API_URL = "https://apis.data.go.kr/1741000/StanReginCd/getStanReginCdList"
API_KEY = os.getenv("MOLIT_API_KEY", "")   # data.go.kr 공용 키

SIDO_NAMES = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시",
    "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도",
    "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도",
    "경상남도", "제주특별자치도",
]


def fetch_sigungu(sido: str) -> list[dict]:
    """시도 1곳의 시군구 레벨 행 조회 (페이지네이션). [{name, lawd, sido}, ...]"""
    rows: list[dict] = []
    page, page_size = 1, 1000   # API 최대 1000행/페이지
    try:
        while True:
            res = requests.get(API_URL, params={
                "serviceKey": API_KEY, "type": "json",
                "pageNo": page, "numOfRows": page_size,
                "locatadd_nm": sido,
            }, timeout=20)
            res.raise_for_status()
            body = res.json().get("StanReginCd")
            if not body or len(body) < 2:
                break
            total = next((h["totalCount"] for h in body[0]["head"]
                          if isinstance(h, dict) and "totalCount" in h), 0)
            rows.extend(body[1].get("row", []))
            if len(rows) >= total:
                break
            page += 1
    except Exception as e:
        print(f"  ⚠️ {sido} 조회 실패: {e}")
        return []

    out = []
    for r in rows:
        # 시군구 레벨: 읍면동·리 코드가 0이고 시군구 코드가 존재
        if r.get("umd_cd") != "000" or r.get("ri_cd") != "00" or r.get("sgg_cd") == "000":
            continue
        full = (r.get("locatadd_nm") or "").strip()
        tokens = full.split()
        if len(tokens) < 2 and full != sido:
            continue
        name = " ".join(tokens[1:]) if len(tokens) >= 2 else full   # "수원시 장안구" / "송파구"
        lawd = (r.get("region_cd") or "")[:5]
        if name and len(lawd) == 5:
            out.append({"name": name, "lawd": lawd, "sido": sido})
    return out


def main():
    if not API_KEY:
        sys.exit("❌ MOLIT_API_KEY 미설정 — .env 확인 (data.go.kr 공용 키)")

    init_cache_db()
    before = len(list_region_codes())

    total = 0
    for sido in SIDO_NAMES:
        rows = fetch_sigungu(sido)
        for r in rows:
            # 기존 시드(정확 코드)를 보존 — 동명이구는 최초 등록 유지
            add_region_code(r["name"], r["lawd"], sido=r["sido"],
                            sigungu=r["name"], overwrite=False)
        total += len(rows)
        print(f"  {sido}: {len(rows)}개 시군구")

    after = len(list_region_codes())
    print(f"\n✅ 전국 시군구 {total}개 처리 — 지역코드 테이블 {before} → {after}개")


if __name__ == "__main__":
    main()
