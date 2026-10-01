"""
reb_index.py — 한국부동산원(R-ONE) 월간 가격지수 조회

시점수정에 실제 부동산원 지수를 사용하기 위한 모듈.
  시점수정 계수 = 기준시점 지수 / 거래시점 지수

동작 조건:
  .env에 REB_API_KEY (또는 RBONE_API_KEY) 설정 시 자동 활성화.
  키가 없으면 모든 함수가 None을 반환하고, price_engine은
  기존 하드코딩 월간 변동률로 폴백한다.

API: https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do
  파라미터: KEY, Type=json, STATBL_ID, DTACYCLE_CD=MM,
            WRTTIME_IDTFR_ID(YYYYMM), pIndex, pSize
  응답 row: WRTTIME_IDTFR_ID, CLS_NM(지역명), CLS_FULLNM(예: "서울>강남지역>서초구"),
            ITM_NM("지수"), DTA_VAL(지수값)
  ※ KEY 미포함 시 샘플 모드로 10건만 반환 → 지역 매칭 실패 → 폴백 (의도된 동작)

지수 공표 시차: 부동산원 월간지수는 익월 중순 공표.
  기준시점 월의 지수가 없으면 가장 최근 공표월까지만 지수로 보정하고,
  잔여 월수는 호출측(price_engine)의 근사 변동률로 보정한다.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import requests
from dotenv import find_dotenv, load_dotenv

_BACKEND_DIR  = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

load_dotenv(find_dotenv())

REB_API_KEY = os.getenv("REB_API_KEY", "") or os.getenv("RBONE_API_KEY", "")

REB_BASE_URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"

# 유형별 통계표 ID (env로 교체 가능)
# 기본값 A_2024_00045 = "(월) 매매가격지수_아파트" — 시군구 단위, 실호출 검증됨.
# 주거용은 아파트 지수를 대표 지수로 사용한다 (연립·단독도 근사 적용).
_CATEGORY_STATBL: dict[str, str] = {
    "주거용": os.getenv("REB_STATBL_RESIDENTIAL", "A_2024_00045"),
    "토지":   os.getenv("REB_STATBL_LAND", ""),          # 지가지수 표 ID 확보 시 설정
    # 상업용·업무용·산업용: 적절한 월간 시군구 지수 없음 → 폴백
}

# 공표 시차 허용: 기준시점 월 지수가 없을 때 최대 몇 개월 전까지 소급 탐색할지
_MAX_LAG_MONTHS = 3

_CACHE_TTL_OLD    = 60 * 60 * 24 * 30   # 완결 월 지수: 30일
_CACHE_TTL_RECENT = 60 * 60 * 24        # 최근 2개월: 24시간 (공표·정정 반영)


def is_enabled() -> bool:
    return bool(REB_API_KEY)


# ─────────────────────────────────────────
#  월별 지수 테이블 조회 (지역 전체)
# ─────────────────────────────────────────

def _fetch_month_rows(statbl_id: str, ym: str) -> dict[str, float] | None:
    """
    특정 월의 전 지역 지수 조회 → {CLS_FULLNM: 지수값}.
    실패(네트워크·API 오류) 시 None. 데이터 없는 월은 빈 dict.
    """
    params = {
        "KEY":               REB_API_KEY,
        "Type":              "json",
        "STATBL_ID":         statbl_id,
        "DTACYCLE_CD":       "MM",
        "WRTTIME_IDTFR_ID":  ym,
        "pIndex":            1,
        "pSize":             400,   # 시군구 전체 (~234행) 여유
    }
    try:
        res = requests.get(REB_BASE_URL, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()

        body = data.get("SttsApiTblData")
        if not body:
            # 데이터 없는 응답: {"RESULT": {"CODE": ...}} 형태로 옴
            code = (data.get("RESULT") or {}).get("CODE", "?")
            if code == "INFO-200":      # 미공표 월 — 유효한 빈 결과
                return {}
            print(f"[reb] API 오류 ({ym}): {code}")
            return None

        head = body[0]["head"]
        result_code = next(
            (h["RESULT"]["CODE"] for h in head if isinstance(h, dict) and "RESULT" in h), ""
        )
        if result_code and result_code != "INFO-000":
            # INFO-200 = 데이터 없음 (미공표 월) — 유효한 빈 결과
            if result_code == "INFO-200":
                return {}
            print(f"[reb] API 오류 ({ym}): {result_code}")
            return None

        rows = body[1].get("row", []) if len(body) > 1 else []
        out: dict[str, float] = {}
        for r in rows:
            if "지수" not in str(r.get("ITM_NM", "")):
                continue
            full = str(r.get("CLS_FULLNM") or r.get("CLS_NM") or "")
            val  = r.get("DTA_VAL")
            if full and isinstance(val, (int, float)) and val > 0:
                out[full] = float(val)
        return out

    except Exception as e:
        print(f"[reb] 조회 실패 ({ym}): {e}")
        return None


def _get_month_rows_cached(statbl_id: str, ym: str) -> dict[str, float] | None:
    """월별 지수 테이블 — cache_db 경유 (완결 월 30일 / 최근 월 24시간 TTL)."""
    from cache_db import cache_get, cache_set

    cached = cache_get(namespace="reb_idx", statbl=statbl_id, ym=ym)
    if cached is not None:
        return cached

    rows = _fetch_month_rows(statbl_id, ym)
    if rows is None:
        return None    # 오류는 캐시하지 않음

    now = datetime.now()
    try:
        d = datetime.strptime(ym, "%Y%m")
        months_ago = (now.year - d.year) * 12 + (now.month - d.month)
    except ValueError:
        months_ago = 0
    ttl = _CACHE_TTL_OLD if months_ago >= 2 else _CACHE_TTL_RECENT

    # 빈 dict(미공표 월)도 캐시 — 단, 짧은 TTL로 재확인
    cache_set(rows, ttl=ttl if rows else _CACHE_TTL_RECENT,
              namespace="reb_idx", statbl=statbl_id, ym=ym)
    return rows


# ─────────────────────────────────────────
#  지역 매칭
# ─────────────────────────────────────────

def _match_region(rows: dict[str, float], region: str, sido: str = "") -> float | None:
    """
    {CLS_FULLNM: 지수} 에서 region(예: '서초구')에 해당하는 지수 선택.
    우선순위: ①시군구 정확 매칭(시도 일치 우선) ②시도 레벨 ③전국
    """
    if not rows:
        return None

    region = (region or "").strip()
    sido_short = (sido or "").replace("특별시", "").replace("광역시", "").replace("도", "").strip()

    # ① 시군구: FULLNM 마지막 세그먼트가 region과 일치
    candidates = []
    for full, val in rows.items():
        parts = full.split(">")
        if parts[-1].strip() == region:
            candidates.append((full, val))
    if candidates:
        if len(candidates) > 1 and sido_short:
            for full, val in candidates:
                if full.startswith(sido_short):
                    return val
        return candidates[0][1]

    # ② 시도 레벨 (예: "서울")
    if sido_short:
        for full, val in rows.items():
            if full.strip() == sido_short:
                return val

    # ③ 전국
    return rows.get("전국")


def _sido_of(region: str) -> str:
    """cache_db region_codes에서 시도명 조회 (없으면 빈 문자열)."""
    try:
        from cache_db import list_region_codes
        for r in list_region_codes():
            if r["region_name"] == region:
                return r.get("sido") or ""
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────
#  공개 API — 시점수정 계수
# ─────────────────────────────────────────

def get_index(category: str, region: str, ym: str) -> float | None:
    """특정 (유형, 지역, 월)의 지수값. 미지원 유형·키 없음·미공표 시 None."""
    if not REB_API_KEY:
        return None
    statbl_id = _CATEGORY_STATBL.get(category, "")
    if not statbl_id:
        return None
    rows = _get_month_rows_cached(statbl_id, ym)
    if not rows:
        return None
    return _match_region(rows, region, _sido_of(region))


def get_adj_factor(
    category: str,
    region: str,
    deal_ym: str,
    as_of_ym: str,
) -> tuple[float, str] | None:
    """
    지수 기반 시점수정 계수.

    반환:
      (계수, 적용설명) — 예: (1.0234, "부동산원 지수 202601→202605")
      None — 지수 미사용 (키 없음·유형 미지원·지수 미확보) → 호출측 폴백

    기준시점 월 지수가 미공표면 최근 공표월까지 소급 탐색해
    '거래월 → 최근 공표월' 구간만 지수로 보정한다.
    잔여 월수 보정은 호출측 책임 (반환된 설명의 도달 월로 판단).
    """
    if not REB_API_KEY or deal_ym == as_of_ym:
        return None
    statbl_id = _CATEGORY_STATBL.get(category, "")
    if not statbl_id:
        return None

    sido = _sido_of(region)

    rows_deal = _get_month_rows_cached(statbl_id, deal_ym)
    if not rows_deal:
        return None
    idx_deal = _match_region(rows_deal, region, sido)
    if not idx_deal:
        return None

    # 기준시점 월 → 미공표 시 최대 _MAX_LAG_MONTHS 소급
    target = _ym_dt(as_of_ym)
    deal   = _ym_dt(deal_ym)
    if target is None or deal is None or target <= deal:
        return None

    for lag in range(_MAX_LAG_MONTHS + 1):
        probe = _shift_ym(as_of_ym, -lag)
        if _ym_dt(probe) <= deal:
            break
        rows_target = _get_month_rows_cached(statbl_id, probe)
        if not rows_target:
            continue
        idx_target = _match_region(rows_target, region, sido)
        if idx_target:
            factor = round(idx_target / idx_deal, 6)
            return factor, f"부동산원 지수 {deal_ym}→{probe}"

    return None


def reached_ym(desc: str) -> str:
    """get_adj_factor 설명 문자열에서 지수 보정이 도달한 월(YYYYMM) 추출."""
    return desc.rsplit("→", 1)[-1] if "→" in desc else ""


def _ym_dt(ym: str):
    try:
        return datetime.strptime(ym, "%Y%m")
    except (ValueError, TypeError):
        return None


def _shift_ym(ym: str, months: int) -> str:
    d = _ym_dt(ym)
    if d is None:
        return ym
    total = d.year * 12 + (d.month - 1) + months
    return f"{total // 12}{total % 12 + 1:02d}"


# ─────────────────────────────────────────
#  진단 CLI — 키 등록 후 동작 확인용
# ─────────────────────────────────────────

if __name__ == "__main__":
    region = sys.argv[1] if len(sys.argv) > 1 else "서초구"
    now_ym = datetime.now().strftime("%Y%m")
    prev6  = _shift_ym(now_ym, -6)

    print(f"REB_API_KEY: {'설정됨 (' + REB_API_KEY[:6] + '...)' if REB_API_KEY else '❌ 미설정 — .env에 REB_API_KEY 추가 필요'}")
    print(f"주거용 통계표: {_CATEGORY_STATBL['주거용']}")

    if not REB_API_KEY:
        print("→ 키가 없으면 price_engine은 근사 변동률로 폴백합니다 (정상 동작).")
        sys.exit(0)

    print(f"\n[테스트] {region} 아파트 매매가격지수, {prev6} → {now_ym}")
    idx = get_index("주거용", region, prev6)
    print(f"  {prev6} 지수: {idx if idx else '조회 실패'}")

    r = get_adj_factor("주거용", region, prev6, now_ym)
    if r:
        factor, desc = r
        print(f"  시점수정 계수: ×{factor} ({desc})")
        print("✅ 부동산원 지수 시점수정 활성화 확인")
    else:
        print("  ❌ 계수 산출 실패 — 키 권한 또는 통계표 ID 확인 필요")
        print(f"     env REB_STATBL_RESIDENTIAL 로 통계표 ID 교체 가능")
