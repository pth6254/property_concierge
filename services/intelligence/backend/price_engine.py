"""
price_engine.py — 가격 분석 엔진 v1.0

analysis_tools.py에서 분리된 순수 가격 데이터 계산 모듈.
외부 의존: MOLIT API, R-ONE API, Vworld (공시지가), 건축원가법 상수.

공개 인터페이스:
  fetch_real_transaction_prices() — 국토부 실거래가 조회
  calc_estimated_value()          — 추정 시장가치 산출
  calc_investment_return()        — 수익률 계산
  calc_cost_approach()            — 건축원가법
  _fetch_by_income_approach()     — 수익환원법 (상업·업무용)
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import requests
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

MOLIT_API_KEY = os.getenv("MOLIT_API_KEY", "")
RBONE_API_KEY = os.getenv("RBONE_API_KEY", "")

if not MOLIT_API_KEY:
    print("[price_engine] ⚠️  MOLIT_API_KEY 없음 → 실거래가 조회 불가")


# ─────────────────────────────────────────
#  빈 결과 헬퍼
# ─────────────────────────────────────────

def _empty_price_data(reason: str = "") -> dict:
    if reason:
        print(f"[molit] ❌ 실거래가 조회 실패 — {reason}")
    return {
        "avg":              0,
        "min":              0,
        "max":              0,
        "count":            0,
        "per_sqm_avg":      0,
        "samples":          [],
        "apt_name_matched": "",
        "error":            reason,
    }


# ─────────────────────────────────────────
#  시점수정 (Time Adjustment)
# ─────────────────────────────────────────

# 부동산 유형별 월간 평균 가격변동률 (한국부동산원 장기 평균 근사치)
# REB_API_KEY 설정 시 부동산원 월간지수(reb_index.py)를 우선 사용하고,
# 키 미설정·지수 미공표 시 아래 근사치로 폴백한다.
_TIME_ADJ_MONTHLY_RATE: dict[str, float] = {
    "주거용": 0.003,   # 0.30%/월
    "상업용": 0.001,   # 0.10%/월
    "업무용": 0.0015,  # 0.15%/월
    "산업용": 0.001,   # 0.10%/월
    "토지":   0.002,   # 0.20%/월
}
_TIME_ADJ_DEFAULT_RATE = 0.002  # 0.20%/월 (기본값)


def _months_between(deal_ym: str, as_of_ymd: str) -> int:
    """
    deal_ym  : 거래연월 YYYYMM 문자열
    as_of_ymd: 기준시점 YYYYMMDD (빈 문자열이면 현재 날짜)
    반환     : 거래일(해당월 15일 기준) ~ 기준시점 월수 (0 이상)
    """
    try:
        target = datetime.strptime(as_of_ymd[:8], "%Y%m%d") if as_of_ymd else datetime.now()
        deal   = datetime.strptime(deal_ym + "15", "%Y%m%d")
        diff   = (target.year - deal.year) * 12 + (target.month - deal.month)
        return max(0, diff)
    except (ValueError, TypeError):
        return 0


def _time_adj_factor(months: int, monthly_rate: float) -> float:
    """시점수정 계수 = (1 + r)^n. 수정 불필요 시 1.0 반환."""
    if months <= 0 or monthly_rate == 0.0:
        return 1.0
    return round((1 + monthly_rate) ** months, 6)


def _apply_time_adjustment(
    samples: list[dict],
    category: str,
    as_of: str,
    region: str = "",
) -> tuple[list[dict], float]:
    """
    실거래 samples 각각에 시점수정 계수를 적용해 price를 보정.

    계수 산출 우선순위:
      1) 부동산원 월간지수 (REB_API_KEY 설정 시, reb_index.py)
         — 지수 미공표 잔여 월수는 근사 변동률로 이어서 보정
      2) 유형별 근사 월간 변동률 (폴백)

    반환:
      samples  : price가 보정된 사본 (original_price / time_adj_source 필드 추가)
      monthly_rate: 폴백에 사용된 월간 변동률
    """
    rate = _TIME_ADJ_MONTHLY_RATE.get(category, _TIME_ADJ_DEFAULT_RATE)

    # 부동산원 지수 사용 가능 여부
    try:
        import reb_index
        use_reb = reb_index.is_enabled()
    except Exception:
        use_reb = False

    as_of_ym = as_of[:6] if as_of and len(as_of) >= 6 else datetime.now().strftime("%Y%m")

    adjusted = []
    reb_hits = 0
    # 같은 요청의 유형·지역·기준월은 고정이다. 월별 계수를 거래마다 재조회하면
    # 수천 건의 단지 집계에서 DB 왕복이 폭증해 프록시 응답 시간이 초과된다.
    # 요청 안에서만 재사용하므로 다음 요청의 지수 갱신·실패 재시도는 유지된다.
    monthly_adjustments = {}
    for d in samples:
        s = dict(d)
        deal_ym = ""
        if s.get("deal_year") and s.get("deal_month"):
            try:
                deal_ym = f"{s['deal_year']}{int(s['deal_month']):02d}"
            except (ValueError, TypeError):
                deal_ym = ""

        months = _months_between(deal_ym, as_of) if deal_ym else 0

        factor = None
        source = "approx"
        if use_reb and deal_ym and months > 0:
            if deal_ym not in monthly_adjustments:
                monthly_adjustments[deal_ym] = reb_index.get_adj_factor(category, region, deal_ym, as_of_ym)
            r = monthly_adjustments[deal_ym]
            if r:
                factor, desc = r
                # 지수 공표 시차로 기준시점까지 못 미친 구간은 근사율로 이어서 보정
                reached = reb_index.reached_ym(desc)
                remain  = _months_between(reached, as_of) if reached else 0
                if remain > 0:
                    factor = round(factor * _time_adj_factor(remain, rate), 6)
                source = "reb_index"
                reb_hits += 1

        if factor is None:
            factor = _time_adj_factor(months, rate)

        s["original_price"]   = s["price"]
        s["time_adj_months"]  = months
        s["time_adj_factor"]  = factor
        s["time_adj_source"]  = source
        if factor != 1.0 and s["price"] > 0:
            s["price"] = round(s["price"] * factor)
        adjusted.append(s)

    if reb_hits:
        print(f"[molit] 시점수정: 부동산원 지수 적용 {reb_hits}/{len(adjusted)}건 (기준 지역: {region or '전국'})")
    return adjusted, rate


# ─────────────────────────────────────────
#  조회 월 목록
# ─────────────────────────────────────────

def _get_recent_deal_ymds(months: int = 3, as_of: str = "") -> list[str]:
    """
    기준시점(as_of) 이전 months개월의 YYYYMM 목록 반환.
    as_of: YYYYMMDD 문자열, 빈 문자열이면 현재 날짜 사용.
    """
    if as_of:
        try:
            now = datetime.strptime(as_of[:8], "%Y%m%d")
        except ValueError:
            now = datetime.now()
    else:
        now = datetime.now()

    result = []
    for i in range(months - 1, -1, -1):
        year  = now.year
        month = now.month - i
        while month <= 0:
            month += 12
            year  -= 1
        result.append(f"{year}{month:02d}")
    return result


# ─────────────────────────────────────────
#  공동주택 공시가격 API (실거래가 폴백)
# ─────────────────────────────────────────

OFFICIAL_PRICE_URL = (
    "https://apis.data.go.kr/1613000"
    "/PblntfPublicWrtPrcInfo/getPblntfPublicWrtPrcInfo"
)

REALIZATION_RATE = {
    "아파트":     0.69,
    "오피스텔":   0.69,
    "연립다세대": 0.654,
    "단독다가구": 0.536,
}


def _fetch_by_official_price(
    lawd_code: str,
    apt_name: str,
    category_detail: str = "",
    area_sqm: float = 0.0,
) -> dict:
    if not MOLIT_API_KEY:
        return _empty_price_data("MOLIT_API_KEY 없음 (공시가격 조회 불가)")

    safe_key  = MOLIT_API_KEY.replace("+", "%2B").replace("=", "%3D")
    this_year = datetime.now().year

    for year in [this_year, this_year - 1]:
        query = (
            f"serviceKey={safe_key}"
            f"&LAWD_CD={lawd_code}"
            f"&STDR_YEAR={year}"
            f"&numOfRows=100"
            f"&pageNo=1"
        )
        if apt_name:
            query += f"&BLDG_NM={apt_name}"

        try:
            res = requests.get(f"{OFFICIAL_PRICE_URL}?{query}", timeout=10)
            res.raise_for_status()
            root  = ET.fromstring(res.text)

            result_code = root.findtext(".//resultCode", "")
            if result_code.lstrip("0") not in ("", "0"):
                print(f"[official] API 오류: {result_code} - {root.findtext('.//resultMsg','')}")
                continue

            items = root.findall(".//item")
            print(f"[official] {year}년 공시가격: {len(items)}건")

            if not items:
                continue

            if area_sqm > 0:
                items = [
                    it for it in items
                    if abs(float(it.findtext("excluUseAr", "0") or 0) - area_sqm) <= 10
                ] or items

            prices = []
            for it in items:
                prc_text = it.findtext("pblntfPrc", "") or ""
                try:
                    prc = int(prc_text.replace(",", "").strip())
                    if prc > 0:
                        prices.append(prc)
                except ValueError:
                    pass

            if not prices:
                continue

            avg_official = sum(prices) // len(prices)
            rate         = REALIZATION_RATE.get(category_detail, 0.69)
            avg_est      = round(avg_official / rate)
            per_sqm_est  = round(avg_est / area_sqm) if area_sqm > 0 else 0

            print(f"[official] ✅ 공시가격 평균 {avg_official:,}만원 "
                  f"/ 현실화율 {rate:.1%} "
                  f"/ 추정 시세 {avg_est:,}만원")

            return {
                "avg":              avg_est,
                "min":              round(avg_est * 0.90),
                "max":              round(avg_est * 1.10),
                "count":            len(prices),
                "per_sqm_avg":      per_sqm_est,
                "samples":          [],
                "apt_name_matched": apt_name,
                "used_months":      0,
                "used_region":      "",
                "source":           f"공시가격 역산 ({year}년 기준, 현실화율 {rate:.1%})",
                "error":            "",
            }

        except requests.Timeout:
            print(f"[official] {year}년 타임아웃")
        except Exception as e:
            print(f"[official] {year}년 오류: {e}")

    return _empty_price_data("공시가격 조회 실패 (실거래·공시가격 모두 없음)")


# ─────────────────────────────────────────
#  국토부 실거래가 API
# ─────────────────────────────────────────

MOLIT_BASE_URL = "https://apis.data.go.kr/1613000"

MOLIT_ENDPOINTS = {
    ("주거용", "아파트"):    "/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
    ("주거용", "연립다세대"): "/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
    ("주거용", "단독다가구"): "/RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade",
    ("주거용", "오피스텔"):  "/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade",
    ("상업용", "상가"):      "/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",
    ("업무용", "사무실"):    "/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",
    ("산업용", "공장"):      "/RTMSDataSvcInduTrade/getRTMSDataSvcInduTrade",
    ("산업용", "창고"):      "/RTMSDataSvcInduTrade/getRTMSDataSvcInduTrade",
    ("토지",   "토지"):      "/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade",
}

PRICE_FIELD_MAP = {
    "주거용": ["dealAmount"],
    "상업용": ["dealAmount"],
    "업무용": ["dealAmount"],
    "산업용": ["dealAmount"],
    "토지":   ["dealAmount"],
}

AREA_FIELD_MAP = {
    "주거용": ["excluUseAr", "buildingAr"],
    "상업용": ["buildingAr", "excluUseAr", "plottageAr"],
    "업무용": ["buildingAr", "excluUseAr"],
    "산업용": ["buildingAr", "plottageAr"],
    "토지":   ["plottageAr", "jimokAr"],
}


def _select_endpoint(category: str, category_detail: str) -> str:
    detail = category_detail.strip()
    if category == "주거용":
        if "오피스텔" in detail:          key = ("주거용", "오피스텔")
        elif any(k in detail for k in ["빌라", "연립", "다세대"]): key = ("주거용", "연립다세대")
        elif any(k in detail for k in ["단독", "다가구", "주택"]): key = ("주거용", "단독다가구")
        else:                             key = ("주거용", "아파트")
    elif category == "상업용": key = ("상업용", "상가")
    elif category == "업무용": key = ("업무용", "사무실")
    elif category == "산업용": key = ("산업용", "창고") if "창고" in detail else ("산업용", "공장")
    elif category == "토지":   key = ("토지", "토지")
    else:                      key = ("주거용", "아파트")
    return MOLIT_ENDPOINTS.get(key, MOLIT_ENDPOINTS[("주거용", "아파트")])


def get_lawd_code(region_2depth: str) -> str:
    from cache_db import get_lawd_code as _get
    return _get(region_2depth)


def _parse_items(items, category: str, property_detail: str = "", lawd_code: str = "") -> list[dict]:
    price_fields = PRICE_FIELD_MAP.get(category, ["거래금액"])
    area_fields  = AREA_FIELD_MAP.get(category, ["전용면적"])
    result = []
    for item in items:
        price_val = 0
        for f in price_fields:
            el = item.find(f)
            if el is not None and el.text:
                try:
                    price_val = int(el.text.replace(",", "").strip())
                    break
                except ValueError:
                    pass
        area_val = 0.0
        for f in area_fields:
            el = item.find(f)
            if el is not None and el.text:
                try:
                    area_val = float(el.text.strip())
                    break
                except ValueError:
                    pass
        if price_val <= 0:
            continue

        if isinstance(price_val, str):
            price_val = int(price_val.replace(",", "").strip())

        apt_nm = (item.findtext("aptNm", "")
                  or item.findtext("mhouseNm", "")
                  or item.findtext("buildNm", ""))
        if not apt_nm:
            bldg_use = item.findtext("buildingUse", "")
            umd_nm   = item.findtext("umdNm", "")
            apt_nm   = f"{umd_nm} {bldg_use}".strip() if bldg_use else umd_nm

        sgg_cd = item.findtext("sggCd", "").strip()
        umd_cd = item.findtext("umdCd", "").strip()
        region_prefix = sgg_cd if len(sgg_cd) == 5 else lawd_code
        bjdong_code = f"{region_prefix}{umd_cd}00" if len(region_prefix) == 5 and len(umd_cd) == 3 else ""
        cancellation_date = item.findtext("cdealDay", "").strip()

        def _float(field: str) -> float | None:
            value = item.findtext(field, "").strip()
            try:
                return float(value) if value else None
            except ValueError:
                return None

        result.append({
            "price":       price_val,
            "area_sqm":    area_val,
            "area_pyeong": round(area_val / 3.3058, 1) if area_val else 0,
            "per_sqm":     round(price_val / area_val) if area_val > 0 else 0,
            "floor":       item.findtext("floor", ""),
            "year_built":  item.findtext("buildYear", ""),
            "dong":        item.findtext("umdNm", ""),
            "apt_name":    apt_nm,
            "jibun":       item.findtext("jibun", "").strip(),
            "deal_year":   item.findtext("dealYear", ""),
            "deal_month":  item.findtext("dealMonth", ""),
            "deal_day":    item.findtext("dealDay", ""),
            "bjdong_code": bjdong_code,
            "property_detail": property_detail,
            "building_area_sqm": _float("buildingAr"),
            "land_area_sqm": _float("plottageAr"),
            "building_use": item.findtext("buildingUse", ""),
            "jimok": item.findtext("jimok", ""),
            "transaction_type": item.findtext("dealingGbn", ""),
            "cancellation_date": cancellation_date,
            "is_cancelled": bool(cancellation_date),
        })
    return result


def _endpoint_name(url: str) -> str:
    """엔드포인트 URL → 스토어 키용 짧은 이름 (예: RTMSDataSvcAptTrade)."""
    parts = url.rstrip("/").split("/")
    return parts[-2] if len(parts) >= 2 else url


def _fetch_one_month_api(url: str, safe_key: str, lawd_code: str,
                         deal_ymd: str, category: str) -> list | None:
    """
    MOLIT API 원시 호출.
    반환: 성공 시 파싱된 샘플 리스트 (거래 0건이면 빈 리스트),
          API 오류·타임아웃 시 None — 호출측이 스토어 적재를 건너뛰도록 구분.
    """
    endpoint = _endpoint_name(url)
    detail_by_endpoint = {
        "RTMSDataSvcAptTrade": "아파트",
        "RTMSDataSvcRHTrade": "연립다세대",
        "RTMSDataSvcSHTrade": "단독다가구",
        "RTMSDataSvcOffiTrade": "오피스텔",
        "RTMSDataSvcNrgTrade": "비주거용",
        "RTMSDataSvcInduTrade": "공장창고",
        "RTMSDataSvcLandTrade": "토지",
    }
    try:
        parsed: list[dict] = []
        page_no = 1
        while True:
            query_string = (
                f"serviceKey={safe_key}&LAWD_CD={lawd_code}&DEAL_YMD={deal_ymd}"
                f"&numOfRows=1000&pageNo={page_no}"
            )
            res = requests.get(f"{url}?{query_string}", timeout=20)
            res.raise_for_status()
            root = ET.fromstring(res.text)
            result_code = root.findtext(".//resultCode", "")
            if result_code and result_code.lstrip("0") not in ("", "0"):
                result_msg = root.findtext(".//resultMsg", "")
                print(f"[molit] API 오류 ({deal_ymd}): {result_code} - {result_msg}")
                return None
            items = root.findall(".//item")
            parsed.extend(_parse_items(items, category, detail_by_endpoint.get(endpoint, ""), lawd_code))
            total_count = int(root.findtext(".//totalCount", "0") or 0)
            if page_no * 1000 >= total_count or not items:
                break
            page_no += 1
        print(f"[molit] {deal_ymd}: {len(parsed)}건 (API)")
        return parsed

    except requests.Timeout:
        print(f"[molit] {deal_ymd} 타임아웃")
        return None
    except Exception as e:
        # requests 예외에는 serviceKey가 포함된 URL이 들어갈 수 있다.
        print(f"[molit] {deal_ymd} 오류: {type(e).__name__}")
        return None


def _fetch_one_month(args: tuple) -> list:
    """
    월 단위 실거래 조회 — 로컬 스토어 우선, 미스 시 API 호출 후 write-through 적재.
    """
    url, safe_key, lawd_code, deal_ymd, category = args
    endpoint = _endpoint_name(url)

    # 1) 로컬 스토어 조회 (적재됨 + TTL 유효 → API 생략)
    import transaction_store
    cached = transaction_store.get_month(endpoint, category, lawd_code, deal_ymd)
    if cached is not None:
        print(f"[molit] {deal_ymd}: {len(cached)}건 (로컬 DB)")
        return cached

    # 2) API 호출
    parsed = _fetch_one_month_api(url, safe_key, lawd_code, deal_ymd, category)
    if parsed is None:          # 오류 — 적재하지 않음 (빈 결과 고착 방지)
        return []

    # 3) write-through 적재 (0건도 유효한 결과로 기록)
    transaction_store.put_month(endpoint, category, lawd_code, deal_ymd, parsed)
    from transaction_evidence import attach_transaction_evidence
    import time
    attach_transaction_evidence(parsed, endpoint, lawd_code, deal_ymd, time.time())
    return parsed


def _fetch_by_ymds(url: str, safe_key: str, lawd_code: str,
                   deal_ymds: list, category: str) -> list:
    args_list  = [(url, safe_key, lawd_code, ymd, category) for ymd in deal_ymds]
    all_parsed = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = executor.map(_fetch_one_month, args_list)
        for parsed in results:
            all_parsed.extend(parsed)

    return all_parsed


def fetch_real_transaction_prices(
    category: str,
    region_2depth: str,
    category_detail: str = "",
    apt_name: str = "",
    region_3depth: str = "",
    floor: int = 0,
    area_sqm_exact: float = 0.0,
    as_of: str = "",
    lawd_code: str = "",
) -> dict:
    """
    국토부 실거래가 API.

    조회 전략:
      1) 단지명 매칭 (3 → 6 → 12개월)
      2) 동 필터링 (3 → 6개월)
      3) 구 전체 (3 → 6개월)
      4) 주거용 한정: 공시가격 역산 폴백

    lawd_code: 법정동코드 5자리. 지오코딩(sigungu_cd)에서 넘어오면 그대로 사용
               (전국 어디든 동작) — 없을 때만 지역명 테이블 조회 폴백.
    """
    if not MOLIT_API_KEY:
        return _empty_price_data("MOLIT_API_KEY 미설정 — .env 파일을 확인하세요")

    lawd_code = (lawd_code or "").strip() or get_lawd_code(region_2depth)
    if not lawd_code:
        return _empty_price_data(f"'{region_2depth}' 지역코드 없음 — 주소를 더 정확히 입력하세요")

    endpoint = _select_endpoint(category, category_detail)
    url      = MOLIT_BASE_URL + endpoint
    safe_key = MOLIT_API_KEY.replace("+", "%2B").replace("=", "%3D")

    all_parsed  = []
    used_months = 0
    used_region = region_2depth
    dong_filter = region_3depth.replace("동", "").replace("읍", "").replace("면", "").strip()
    apt_clean   = apt_name.strip() if apt_name else ""
    matched_complex = False

    _SUFFIXES = ["아파트", "빌라", "오피스텔", "주상복합", "타운", "빌딩", "타워"]
    def _strip_suffix(name: str) -> str:
        for s in _SUFFIXES:
            if name.endswith(s):
                return name[:-len(s)].strip()
        return name

    apt_clean_stripped = _strip_suffix(apt_clean)
    apt_no_space       = apt_clean_stripped.replace(" ", "")

    # ── 1단계: 단지명 매칭 (3 → 6 → 12개월) ───────────────────────────────
    if apt_clean:
        for months in [3, 6, 12]:
            deal_ymds  = _get_recent_deal_ymds(months=months, as_of=as_of)
            print(f"[molit] 단지 조회: '{apt_clean_stripped}' / {months}개월")
            raw_parsed = _fetch_by_ymds(url, safe_key, lawd_code, deal_ymds, category)
            if not raw_parsed:
                print(f"[molit] '{apt_clean_stripped}' {months}개월 없음 → 기간 확장")
                continue

            # 같은 이름의 다른 동 단지를 섞지 않는다. 구 전체 폴백 자료는 별도로 조회한다.
            if region_3depth:
                from comparable_matching import normalized_name
                raw_parsed = [d for d in raw_parsed if normalized_name(d.get("dong")) == normalized_name(region_3depth)]
            actual_names = list(set(d["apt_name"] for d in raw_parsed))
            candidates   = [n for n in actual_names
                            if apt_no_space[:4] in n.replace(" ", "")]
            if candidates:
                print(f"[molit] 후보 단지명: {candidates[:5]}")

            exact = [d for d in raw_parsed
                     if _strip_suffix(d["apt_name"]) == apt_clean_stripped]
            if exact:
                all_parsed  = exact
                matched_complex = True
                used_months = months
                print(f"[molit] ✅ 단지 정확 매칭: '{apt_clean_stripped}' {len(exact)}건 / {months}개월")
                break

            no_space = [d for d in raw_parsed
                        if _strip_suffix(d["apt_name"]).replace(" ", "") == apt_no_space]
            if no_space:
                top_name    = Counter(d["apt_name"] for d in no_space).most_common(1)[0][0]
                all_parsed  = no_space
                matched_complex = True
                used_months = months
                print(f"[molit] ✅ 단지 공백제거 매칭: '{apt_clean_stripped}' → '{top_name}' {len(no_space)}건 / {months}개월")
                break

            partial = [d for d in raw_parsed
                       if (apt_no_space in _strip_suffix(d["apt_name"]).replace(" ", "")
                           or _strip_suffix(d["apt_name"]).replace(" ", "") in apt_no_space)
                       and len(_strip_suffix(d["apt_name"]).replace(" ", "")) >= 3]
            if partial and len({d["apt_name"] for d in partial}) == 1:
                top_name    = Counter(d["apt_name"] for d in partial).most_common(1)[0][0]
                matched     = [d for d in partial if d["apt_name"] == top_name]
                all_parsed  = matched
                matched_complex = True
                used_months = months
                print(f"[molit] ✅ 단지 부분 매칭: '{apt_clean_stripped}' → '{top_name}' {len(matched)}건 / {months}개월")
                break

            if raw_parsed:
                actual_names = list(set(d["apt_name"] for d in raw_parsed[:20]))
                candidates = [n for n in actual_names
                              if any(c in n.replace(" ","") for c in apt_no_space[:4])]
                if candidates:
                    print(f"[molit] 후보 단지명: {candidates[:5]}")
            print(f"[molit] '{apt_clean_stripped}' {months}개월 없음 → 기간 확장")

    # ── 2단계: 동 필터링 (3 → 6개월) ───────────────────────────────────────
    if not all_parsed and dong_filter:
        for months in [3, 6]:
            deal_ymds  = _get_recent_deal_ymds(months=months, as_of=as_of)
            print(f"[molit] 동 조회: '{dong_filter}동' / {months}개월")
            raw_parsed = _fetch_by_ymds(url, safe_key, lawd_code, deal_ymds, category)
            if raw_parsed:
                from comparable_matching import normalized_name
                dong_filtered = [d for d in raw_parsed if normalized_name(region_3depth) == normalized_name(d.get("dong"))]
                if dong_filtered:
                    all_parsed  = dong_filtered
                    used_months = months
                    print(f"[molit] ✅ 동 필터링: '{dong_filter}동' {len(dong_filtered)}건 / {months}개월")
                    break
            print(f"[molit] '{dong_filter}동' {months}개월 없음 → 기간 확장")

    # ── 3단계: 구 전체 (3 → 6개월) ─────────────────────────────────────────
    if not all_parsed:
        for months in [3, 6]:
            deal_ymds  = _get_recent_deal_ymds(months=months, as_of=as_of)
            print(f"[molit] 구 전체 조회: {region_2depth} / {months}개월")
            raw_parsed = _fetch_by_ymds(url, safe_key, lawd_code, deal_ymds, category)
            if raw_parsed:
                all_parsed  = raw_parsed
                used_months = months
                print(f"[molit] ✅ 구 전체: {len(raw_parsed)}건 / {months}개월")
                break
            print(f"[molit] {months}개월 데이터 없음 → 기간 확장")

    # ── 실거래 없음 → 공시가격 폴백 (주거용만) ──────────────────────────────
    if not all_parsed:
        if category == "주거용":
            print("[molit] 실거래 없음 → 공시가격 폴백 시도")
            return _fetch_by_official_price(
                lawd_code       = lawd_code,
                apt_name        = apt_clean,
                category_detail = category_detail,
                area_sqm        = 0.0,
            )
        return _empty_price_data("최근 6개월 실거래 데이터 없음")

    # ── 결과 집계 ─────────────────────────────────────────────────────────
    # ── 정밀 필터 (호수 정보 있을 때만, 주거용 단지 매칭 후 적용) ─────────────────
    precision_label = ""
    if category in ("주거용", "상업용", "업무용") and apt_name and all_parsed:
        filtered = all_parsed

        # 면적 필터 (±3㎡, 부족하면 ±6㎡) — 모든 집합건물 유형 적용
        if area_sqm_exact > 0:
            area_tight = [d for d in filtered
                          if d["area_sqm"] > 0 and abs(d["area_sqm"] - area_sqm_exact) <= 3.0]
            area_loose = [d for d in filtered
                          if d["area_sqm"] > 0 and abs(d["area_sqm"] - area_sqm_exact) <= 6.0]
            if len(area_tight) >= 3:
                filtered = area_tight
                precision_label += f"면적±3㎡({area_sqm_exact}㎡) "
            elif len(area_loose) >= 2:
                filtered = area_loose
                precision_label += f"면적±6㎡({area_sqm_exact}㎡) "

        # 층수 필터 — 주거용 아파트·오피스텔만 적용 (상업용·업무용은 층수 데이터 신뢰도 낮음)
        if floor > 0 and category == "주거용" and category_detail not in ("연립다세대", "단독다가구"):
            def _to_floor(s):
                try: return int(str(s).strip())
                except: return 0
            floor_tight = [d for d in filtered
                           if _to_floor(d.get("floor")) > 0
                           and abs(_to_floor(d.get("floor")) - floor) <= 2]
            floor_loose = [d for d in filtered
                           if _to_floor(d.get("floor")) > 0
                           and abs(_to_floor(d.get("floor")) - floor) <= 4]
            if len(floor_tight) >= 2:
                filtered = floor_tight
                precision_label += f"층수±2({floor}층) "
            elif len(floor_loose) >= 2:
                filtered = floor_loose
                precision_label += f"층수±4({floor}층) "

        if precision_label and filtered:
            print(f"[molit] 정밀 필터 적용: {precision_label.strip()} → {len(filtered)}건")
            all_parsed = filtered

    apt_name_matched = all_parsed[0].get("apt_name", "") if matched_complex else ""

    # ── 시점수정 적용 (부동산원 지수 우선, 근사율 폴백) ──────────────────
    all_parsed, time_adj_rate = _apply_time_adjustment(all_parsed, category, as_of, region_2depth)

    prices = [d["price"] for d in all_parsed if d["price"] > 0]
    areas  = [d["area_sqm"] for d in all_parsed if d["area_sqm"] > 0]

    if not prices:
        return _empty_price_data("필터링 후 유효한 가격 데이터 없음")

    avg_price = sum(prices) // len(prices)
    per_sqm   = round(sum(p / a for p, a in zip(prices, areas)) / len(areas)) if areas else 0
    samples   = all_parsed[:10]

    for s in samples:
        s["apt_name_matched"] = apt_name_matched
        s["target_dong"] = region_3depth
        s["target_sigungu_code"] = lawd_code
        s["query_sigungu_code"] = lawd_code
        s["target_area_sqm"] = area_sqm_exact
        s["selection_filter"] = precision_label.strip()

    adj_months_avg = round(sum(s.get("time_adj_months", 0) for s in samples) / len(samples)) if samples else 0
    if adj_months_avg > 0:
        print(f"[molit] ✅ {len(prices)}건 / 평균 {avg_price:,}만원 (시점수정 {adj_months_avg}개월 평균, {time_adj_rate*100:.2f}%/월) / ㎡당 {per_sqm:,}만원")
    else:
        print(f"[molit] ✅ {len(prices)}건 / 평균 {avg_price:,}만원 / ㎡당 {per_sqm:,}만원 / {used_months}개월 기준")

    return {
        "avg":              avg_price,
        "min":              min(prices),
        "max":              max(prices),
        "count":            len(prices),
        "per_sqm_avg":      per_sqm,
        "samples":          samples,
        "apt_name_matched": apt_name_matched,
        "target_dong": region_3depth,
        "target_sigungu_code": lawd_code,
        "used_months":      used_months,
        "used_region":      used_region,
        "error":            "",
        "precision_filter": precision_label.strip(),
        "time_adj_rate":    time_adj_rate,
        "time_adj_applied": adj_months_avg > 0,
    }


# ─────────────────────────────────────────
#  감정평가 계산
# ─────────────────────────────────────────

AREA_BANDS = [
    (0,   40,  "초소형 (40㎡ 미만)"),
    (40,  60,  "소형 (40~60㎡)"),
    (60,  85,  "중소형 (60~85㎡)"),
    (85,  115, "중형 (85~115㎡)"),
    (115, 135, "중대형 (115~135㎡)"),
    (135, 999, "대형 (135㎡ 이상)"),
]


def _calc_area_band_ranges(samples: list[dict], per_sqm: int) -> list[dict]:
    band_result = []
    for lo, hi, label in AREA_BANDS:
        band_samples = [
            s for s in samples
            if lo <= s.get("area_sqm", 0) < hi and s.get("price", 0) > 0
        ]
        if band_samples:
            prices   = [s["price"] for s in band_samples]
            mid_area = (lo + hi) / 2 if hi < 999 else lo + 20
            est      = round(per_sqm * mid_area) if per_sqm else sum(prices) // len(prices)
            band_result.append({
                "label":     label,
                "area_lo":   lo,
                "area_hi":   hi,
                "estimated": est,
                "price_min": min(prices),
                "price_max": max(prices),
                "count":     len(prices),
            })
    return band_result


def calc_estimated_value(price_data: dict, area_sqm: float, category: str) -> dict:
    avg         = price_data.get("avg", 0)
    per_sqm     = price_data.get("per_sqm_avg", 0)
    samples     = price_data.get("samples", [])
    area_pyeong = round(area_sqm / 3.3058, 1) if area_sqm else 0

    if area_sqm > 0:
        estimated        = round(per_sqm * area_sqm) if per_sqm else (avg or 0)
        value_min        = round(estimated * 0.90)
        value_max        = round(estimated * 1.10)
        area_band_ranges = []
    else:
        estimated        = avg or 0
        value_min        = price_data.get("min", 0)
        value_max        = price_data.get("max", 0)
        area_band_ranges = _calc_area_band_ranges(samples, per_sqm)
        if not area_band_ranges and per_sqm:
            for lo, hi, label in AREA_BANDS:
                mid = (lo + hi) / 2 if hi < 999 else lo + 20
                area_band_ranges.append({
                    "label":     label,
                    "area_lo":   lo,
                    "area_hi":   hi,
                    "estimated": round(per_sqm * mid),
                    "price_min": round(per_sqm * lo) if lo > 0 else 0,
                    "price_max": round(per_sqm * hi) if hi < 999 else round(per_sqm * (lo + 50)),
                    "count":     0,
                })

    price_per_pyeong = round(per_sqm * 3.3058) if per_sqm else 0

    regional_ppyeong = 0
    if samples:
        ppyeongs = [round(s["per_sqm"] * 3.3058) for s in samples if s.get("per_sqm", 0) > 0]
        if ppyeongs:
            regional_ppyeong = sum(ppyeongs) // len(ppyeongs)

    return {
        "estimated_value":         estimated,
        "value_min":               value_min,
        "value_max":               value_max,
        "price_per_pyeong":        price_per_pyeong,
        "area_pyeong":             area_pyeong,
        "regional_avg_per_pyeong": regional_ppyeong,
        "price_per_sqm":           per_sqm,
        "area_band_ranges":        area_band_ranges,
        "has_area_input":          area_sqm > 0,
    }


# ─────────────────────────────────────────
#  수익환원법 — 상업용·업무용
# ─────────────────────────────────────────

RBONE_BASE_URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"

RBONE_BLDG_TYPE = {
    "상업용": "A01",
    "업무용": "B01",
}

RBONE_RENT_FALLBACK = {
    "상업용": {
        "서울": {"서초구": 12.0, "강남구": 14.0, "마포구": 8.0,
                 "영등포구": 9.0, "송파구": 10.0, "default": 7.0},
        "경기": {"default": 4.5},
        "부산": {"해운대구": 6.0, "default": 4.0},
        "default": 4.0,
    },
    "업무용": {
        "서울": {"서초구": 3.5, "강남구": 4.0, "중구": 3.8,
                 "영등포구": 3.2, "마포구": 2.8, "default": 2.5},
        "경기": {"성남시": 2.0, "default": 1.5},
        "부산": {"default": 1.5},
        "default": 1.5,
    },
}

RBONE_VACANCY_FALLBACK = {
    "상업용": {
        "서울": {"서초구": 7.0, "강남구": 6.0, "default": 10.0},
        "default": 12.0,
    },
    "업무용": {
        "서울": {"서초구": 8.0, "강남구": 7.0, "여의도": 9.0, "default": 12.0},
        "경기": {"default": 15.0},
        "default": 14.0,
    },
}

CAP_RATE_TABLE = {
    "상업용": {"서울": 4.5, "경기": 5.5, "default": 5.5},
    "업무용": {"서울": 4.0, "경기": 5.0, "default": 5.0},
}


def _get_rbone_rent(category: str, region_1depth: str, region_2depth: str) -> tuple[float, float]:
    if RBONE_API_KEY:
        try:
            bldg_type = RBONE_BLDG_TYPE.get(category, "A01")
            now       = datetime.now()
            quarter   = (now.month - 1) // 3 + 1
            if quarter == 1:
                stdr_de = f"{now.year - 1}Q4"
            else:
                stdr_de = f"{now.year}Q{quarter - 1}"

            params = (
                f"serviceKey={RBONE_API_KEY}"
                f"&statbl_id=A_2024_00006"
                f"&stdr_de={stdr_de}"
                f"&numOfRows=100"
                f"&pageNo=1"
            )
            res = requests.get(f"{RBONE_BASE_URL}?{params}", timeout=8)
            res.raise_for_status()
            root  = ET.fromstring(res.text)
            items = root.findall(".//row")

            for item in items:
                area    = item.findtext("AREA_NM", "")
                type_nm = item.findtext("BLDG_TYPE_NM", "")
                if region_2depth in area and bldg_type in type_nm:
                    rent    = float(item.findtext("RENT_AMT", "0") or 0)
                    vacancy = float(item.findtext("VCNC_RATE", "0") or 0)
                    if rent > 0:
                        print(f"[rbone] {region_2depth} {category} 임대료: {rent}만원/㎡, 공실: {vacancy}%")
                        return rent, vacancy

        except Exception as e:
            print(f"[rbone] API 오류: {e} → 기준값 사용")

    rent_table    = RBONE_RENT_FALLBACK.get(category, {})
    vacancy_table = RBONE_VACANCY_FALLBACK.get(category, {})

    r1 = region_1depth.replace("특별시", "").replace("광역시", "").replace("특별자치시", "").replace("도", "").strip()

    rent_region    = rent_table.get(r1, rent_table.get("default", {}))
    vacancy_region = vacancy_table.get(r1, vacancy_table.get("default", {}))

    if isinstance(rent_region, dict):
        rent    = rent_region.get(region_2depth, rent_region.get("default", 4.0))
        vacancy = vacancy_region.get(region_2depth, vacancy_region.get("default", 12.0)) if isinstance(vacancy_region, dict) else vacancy_region
    else:
        rent    = rent_region
        vacancy = vacancy_region if isinstance(vacancy_region, (int, float)) else 12.0

    print(f"[rbone] 기준값 사용: {region_2depth} {category} 임대료 {rent}만원/㎡, 공실 {vacancy}%")
    return float(rent), float(vacancy)


def _fetch_by_income_approach(
    category: str,
    region_1depth: str,
    region_2depth: str,
    area_sqm: float,
    cap_rate_override: float = 0.0,
) -> dict:
    """수익환원법: NOI / Cap Rate = 추정 시세 (상업용·업무용 실거래 없을 때 폴백)"""
    if area_sqm <= 0:
        return _empty_price_data("수익환원법: 면적 정보 없음")

    rent_per_sqm, vacancy_rate = _get_rbone_rent(category, region_1depth, region_2depth)

    annual_rent    = rent_per_sqm * area_sqm * 12
    vacancy_loss   = annual_rent * (vacancy_rate / 100)
    operating_cost = annual_rent * 0.15
    noi            = annual_rent - vacancy_loss - operating_cost

    r1        = region_1depth.replace("특별시","").replace("광역시","").replace("도","").strip()
    cap_table = CAP_RATE_TABLE.get(category, {})
    cap_rate  = cap_rate_override or cap_table.get(r1, cap_table.get("default", 5.0))
    cap_rate  = cap_rate / 100

    estimated = round(noi / cap_rate) if cap_rate > 0 else 0
    per_sqm   = round(estimated / area_sqm) if area_sqm > 0 else 0

    print(f"[수익환원법] 월임대료 {rent_per_sqm}만원/㎡ × {area_sqm}㎡ "
          f"→ 연임대 {annual_rent:,.0f}만원 / NOI {noi:,.0f}만원 "
          f"/ Cap {cap_rate:.1%} → 추정가 {estimated:,}만원")

    return {
        "avg":              estimated,
        "min":              round(estimated * 0.85),
        "max":              round(estimated * 1.15),
        "count":            0,
        "per_sqm_avg":      per_sqm,
        "samples":          [],
        "apt_name_matched": "",
        "used_months":      0,
        "used_region":      region_2depth,
        "noi":              round(noi),
        "annual_rent":      round(annual_rent),
        "vacancy_rate":     vacancy_rate,
        "cap_rate_used":    cap_rate * 100,
        "source":           (f"수익환원법 (월임대료 {rent_per_sqm}만원/㎡, "
                             f"공실률 {vacancy_rate}%, Cap Rate {cap_rate:.1%})"),
        "error":            "",
    }


# ─────────────────────────────────────────
#  건축원가법 — 산업용 (공장·창고)
# ─────────────────────────────────────────

STANDARD_CONSTRUCTION_COST = {
    "공장": {
        "철근콘크리트": 95, "철골철근콘크리트": 100,
        "철골조": 80, "조적조": 60, "default": 80,
    },
    "창고": {
        "철근콘크리트": 65, "철골철근콘크리트": 70,
        "철골조": 50, "조적조": 40, "default": 50,
    },
    "물류창고": {
        "철근콘크리트": 75, "철골조": 60, "default": 60,
    },
}

USEFUL_LIFE = {
    "공장": {
        "철근콘크리트": 40, "철골철근콘크리트": 40,
        "철골조": 30, "조적조": 20, "default": 35,
    },
    "창고": {
        "철근콘크리트": 30, "철골철근콘크리트": 30,
        "철골조": 25, "조적조": 20, "default": 25,
    },
    "물류창고": {
        "철근콘크리트": 35, "철골조": 25, "default": 30,
    },
}

RESIDUAL_VALUE_RATE = {
    "철근콘크리트": 0.10, "철골철근콘크리트": 0.10,
    "철골조": 0.05, "조적조": 0.05, "default": 0.10,
}


def _get_strct_key(strct_nm: str) -> str:
    for key in ["철골철근콘크리트", "철근콘크리트", "철골조", "조적조"]:
        if key in strct_nm:
            return key
    return "default"


def _calc_residual_rate(age: int, useful_life: int, residual: float,
                        method: str = "declining") -> float:
    if age <= 0:
        return 1.0
    if method == "declining":
        r    = 1 - (residual ** (1 / useful_life))
        rate = (1 - r) ** age
    else:
        rate = 1 - (1 - residual) * (age / useful_life)
    return round(max(residual, rate), 4)


def calc_cost_approach(
    land_area_sqm: float,
    official_land_price: int,
    build_area_sqm: float,
    build_year: int,
    category_detail: str,
    strct_nm: str = "",
    depreciation: str = "declining",
) -> dict:
    """건축원가법: 토지가격 + 건물가격(감가상각 적용)"""
    now_year   = datetime.now().year
    detail_key = next((k for k in STANDARD_CONSTRUCTION_COST if k in category_detail), "창고")
    strct_key  = _get_strct_key(strct_nm)

    cost_table = STANDARD_CONSTRUCTION_COST[detail_key]
    life_table = USEFUL_LIFE[detail_key]

    std_cost    = cost_table.get(strct_key, cost_table["default"])
    useful_life = life_table.get(strct_key, life_table["default"])
    residual    = RESIDUAL_VALUE_RATE.get(strct_key, RESIDUAL_VALUE_RATE["default"])

    age   = max(0, now_year - int(build_year)) if build_year else 10
    잔가율 = _calc_residual_rate(age, useful_life, residual, method=depreciation)

    land_value  = round(official_land_price * land_area_sqm) if official_land_price and land_area_sqm else 0
    재조달원가  = round(std_cost * build_area_sqm) if build_area_sqm else 0
    build_value = round(재조달원가 * 잔가율)
    감가액       = 재조달원가 - build_value
    total       = land_value + build_value

    if total <= 0:
        return _empty_price_data("건축원가법: 토지가격·건물가격 모두 0 (면적 및 공시지가 필요)")

    per_sqm     = round(total / build_area_sqm) if build_area_sqm > 0 else 0
    source_note = "공시지가 + 표준건축비" if land_value > 0 else "표준건축비만 (토지가격 미산정)"
    strct_label = strct_key if strct_key != "default" else "기본"

    print(
        f"[원가법] 구조:{strct_label} / 재조달원가 {재조달원가:,}만원 "
        f"→ 감가 {감가액:,}만원 (잔가율 {잔가율:.1%}, {depreciation}, 경과 {age}년) "
        f"/ 토지 {land_value:,}만원 + 건물 {build_value:,}만원 = {total:,}만원 [{source_note}]"
    )

    return {
        "avg":              total,
        "min":              round(total * 0.85),
        "max":              round(total * 1.15),
        "count":            0,
        "per_sqm_avg":      per_sqm,
        "samples":          [],
        "apt_name_matched": "",
        "used_months":      0,
        "used_region":      "",
        "land_value":       land_value,
        "build_value":      build_value,
        "재조달원가":        재조달원가,
        "감가액":            감가액,
        "잔가율":            잔가율,
        "build_age":        age,
        "strct_nm":         strct_label,
        "depreciation":     depreciation,
        "source":           (
            f"건축원가법 ({source_note}, {strct_label}구조, "
            f"잔가율 {잔가율:.1%}, {depreciation}법, 경과 {age}년)"
        ),
        "error":            "",
    }


def calc_investment_return(estimated_value: int, category: str, area_sqm: float) -> dict:
    cap_rates     = {"주거용": 3.5, "상업용": 5.0, "업무용": 4.5, "산업용": 6.0, "토지": 2.5}
    cap_rate      = cap_rates.get(category, 4.0)
    annual_income = round(estimated_value * cap_rate / 100) if estimated_value else 0
    roi_5yr       = round(cap_rate * 5, 1)

    if cap_rate >= 6.0:   grade = "A"
    elif cap_rate >= 4.5: grade = "B"
    elif cap_rate >= 3.0: grade = "C"
    else:                 grade = "D"

    return {"cap_rate": cap_rate, "annual_income": annual_income,
            "roi_5yr": roi_5yr, "investment_grade": grade}


# ─────────────────────────────────────────
#  CLI 테스트
# ─────────────────────────────────────────

if __name__ == "__main__":
    ymds = _get_recent_deal_ymds(3)
    print(f"현재 날짜  : {datetime.now().strftime('%Y-%m-%d')}")
    print(f"조회 대상월: {ymds}")

    if MOLIT_API_KEY:
        data = fetch_real_transaction_prices("주거용", "서초구", "아파트", apt_name="래미안원베일리")
        print(f"\n래미안원베일리 실거래가:")
        print(f"  건수  : {data['count']}건")
        print(f"  평균  : {data['avg']:,}만원")
        print(f"  오류  : {data.get('error') or '없음'}")
    else:
        print("\n⚠️  MOLIT_API_KEY 없음 — .env 파일을 확인하세요")
