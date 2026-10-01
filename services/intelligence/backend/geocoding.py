"""
geocoding.py — 좌표 변환 + 건물명·부동산 유형 자동 판단 v2.4
--------------------------------------------------------------
흐름:
  1순위) 카카오 주소검색 API
         → road_address.building_name 으로 정확한 건물명 1:1 추출
         → 예) "서울시 서초구 반포대로 333" → "래미안원베일리"
         → 건물명으로 키워드검색 → category_name → 부동산 유형 판단

  2순위) 주소검색 실패 또는 building_name 없을 때
         → 입력값 그대로 키워드검색
         → place_name + category_name 한 번에 획득

  3순위) 사용자 선택·전유부·건축물대장·검증된 규칙으로 유형 확정
           (LLM category는 검색 후보로만 사용)
"""

from __future__ import annotations

import os
import re
import time
from math import asin, cos, radians, sin, sqrt
from typing import Optional

import requests
from dotenv import load_dotenv, find_dotenv
from pydantic import BaseModel, Field
from cache_db import cache_get, cache_set

load_dotenv(find_dotenv())

KAKAO_API_KEY  = os.getenv("KAKAO_REST_API_KEY", "")
VWORLD_API_KEY = os.getenv("VWORLD_API_KEY", "")

KAKAO_ADDR_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KWD_URL  = "https://dapi.kakao.com/v2/local/search/keyword.json"


# ─────────────────────────────────────────
#  1. 결과 데이터 모델
# ─────────────────────────────────────────

class CategoryResolution(BaseModel):
    """최종 유형과 그 근거, 사용자 선택과 공식 용도의 충돌 정보."""

    category: str = ""
    detail: str = ""
    source: str = "unknown"
    confidence: float = 0.0
    evidence: str = ""
    kakao_category: str = ""
    selected_category: str = ""
    selected_detail: str = ""
    official_category: str = ""
    official_detail: str = ""
    official_source: str = ""
    building_main_use: str = ""
    unit_use: str = ""
    conflict: bool = False
    conflict_message: str = ""


class GeocodingResult(BaseModel):
    lat: float = Field(description="위도 (WGS84)")
    lng: float = Field(description="경도 (WGS84)")

    address_name:  str = Field(default="", description="전체 주소 문자열")
    region_1depth: str = Field(default="", description="시·도")
    region_2depth: str = Field(default="", description="시·군·구")
    region_3depth: str = Field(default="", description="읍·면·동")

    method:     str   = Field(default="address")
    confidence: float = Field(default=1.0)

    # 건물 정보
    place_name:        str = Field(default="", description="건물·단지명")
    kakao_category:    str = Field(default="", description="카카오 원본 카테고리")
    property_category: str = Field(default="", description="주거용/상업용/업무용/산업용/토지")
    category_detail:   str = Field(default="", description="아파트/오피스텔/상가 등")
    category_source:   str = Field(
        default="",
        description="user | unit_register | building_register | building_name_rule | kakao_exact | unknown",
    )
    category_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    category_evidence: str = Field(default="")
    selected_category: str = Field(default="")
    official_category: str = Field(default="")
    official_detail: str = Field(default="")
    building_main_use: str = Field(default="")
    unit_use: str = Field(default="")
    category_conflict: bool = Field(default=False)
    category_conflict_message: str = Field(default="")

    # 토지 전용
    land_use_zone:       str   = Field(default="")
    land_area:           float = Field(default=0.0)
    official_land_price: int   = Field(default=0)
    land_info_status:     str   = Field(default="not_requested")

    # 건축물대장 조회용 지번 정보
    sigungu_cd: str = Field(default="", description="시군구코드 5자리")
    bjdong_cd:  str = Field(default="", description="법정동코드 10자리")
    bun:        str = Field(default="", description="지번 본번")
    ji:         str = Field(default="", description="지번 부번")


# ─────────────────────────────────────────
#  2. 카카오 category_name → 부동산 유형 매핑
# ─────────────────────────────────────────

KAKAO_CATEGORY_MAP: list[tuple[str, str, str]] = [
    ("아파트",       "주거용", "아파트"),
    ("오피스텔",     "주거용", "오피스텔"),
    ("빌라",         "주거용", "빌라"),
    ("연립",         "주거용", "연립다세대"),
    ("다세대",       "주거용", "연립다세대"),
    ("단독주택",     "주거용", "단독다가구"),
    ("다가구",       "주거용", "단독다가구"),
    ("주거시설",     "주거용", "아파트"),
    ("공장",         "산업용", "공장"),
    ("창고",         "산업용", "창고"),
    ("물류",         "산업용", "창고"),
    ("지식산업센터", "산업용", "공장"),
    ("산업단지",     "산업용", "공장"),
    ("사무",         "업무용", "사무실"),
    ("오피스",       "업무용", "사무실"),
    ("업무",         "업무용", "사무실"),
    ("상가",         "상업용", "상가"),
    ("마트",         "상업용", "상가"),
    ("백화점",       "상업용", "상가"),
    ("쇼핑",         "상업용", "상가"),
    ("판매",         "상업용", "상가"),
    ("숙박",         "상업용", "상가"),
    ("음식점",       "상업용", "상가"),
    ("토지",         "토지",   "토지"),
    ("농지",         "토지",   "토지"),
    ("임야",         "토지",   "토지"),
    ("대지",         "토지",   "토지"),
]

VALID_PROPERTY_CATEGORIES = {"주거용", "상업용", "업무용", "산업용", "토지"}

# 건축물대장의 주용도는 법적 분류이므로 장소 검색이나 LLM 추정보다 우선한다.
# 더 구체적인 용도를 먼저 검사해야 "공동주택"이 일반 "주택" 규칙에 먹히는 식의
# 되돌리기 어려운 오분류를 피할 수 있다.
BUILDING_USE_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("공동주택", "아파트"), "주거용", "아파트"),
    (("연립주택", "다세대주택", "다가구주택", "단독주택", "주택"), "주거용", "주택"),
    (("기숙사",), "주거용", "기숙사"),
    (("제1종근린생활시설", "제2종근린생활시설", "근린생활시설"), "상업용", "상가"),
    (("판매시설", "숙박시설", "위락시설"), "상업용", "상가"),
    (("업무시설",), "업무용", "사무실"),
    (("지식산업센터", "공장"), "산업용", "공장"),
    (("창고시설", "창고"), "산업용", "창고"),
    (("위험물저장및처리시설", "자원순환관련시설"), "산업용", "산업시설"),
]

BUILDING_NAME_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("아파트", "주상복합"), "주거용", "아파트"),
    (("오피스텔",), "주거용", "오피스텔"),
    (("빌라",), "주거용", "빌라"),
    (("공장", "지식산업센터", "산업단지"), "산업용", "공장"),
    (("창고", "물류센터"), "산업용", "창고"),
    (("오피스", "사옥", "업무빌딩", "파이낸스센터", "금융센터"), "업무용", "사무실"),
]


def _map_kakao_category(category_name: str) -> tuple[str, str]:
    for keyword, prop_cat, detail in KAKAO_CATEGORY_MAP:
        if keyword in category_name:
            return prop_cat, detail
    return "", ""


def _map_building_use(main_purps: str) -> tuple[str, str]:
    """건축물대장 주용도명을 서비스의 5개 유형으로 결정론적으로 변환한다."""
    compact = re.sub(r"\s+", "", main_purps or "")
    for keywords, category, detail in BUILDING_USE_RULES:
        if any(keyword in compact for keyword in keywords):
            return category, detail
    return "", ""


def _map_building_name(building_name: str) -> tuple[str, str]:
    """법적 용도를 조회할 수 없을 때 명시적인 건물명 접미사만 보조 근거로 쓴다."""
    compact = re.sub(r"\s+", "", building_name or "")
    for keywords, category, detail in BUILDING_NAME_RULES:
        if any(keyword in compact for keyword in keywords):
            return category, detail
    return "", ""


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """외부 지리 라이브러리 없이 두 WGS84 좌표의 대략적인 거리를 계산한다."""
    radius = 6_371_000
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * radius * asin(sqrt(a))


def _kakao_headers() -> dict:
    if not KAKAO_API_KEY:
        raise EnvironmentError("KAKAO_REST_API_KEY 환경변수가 없습니다.")
    return {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}


# ─────────────────────────────────────────
#  3. 카카오 좌표 → 지번 역지오코딩
# ─────────────────────────────────────────

def _coord2jibun(lat: float, lng: float) -> dict:
    """
    카카오 coord2address API — 좌표 → 지번 주소 변환.

    coord2address 가 address.b_code 를 정확히 못 줄 때
    regioncode API 로 법정동 코드를 보완한다.
    """
    try:
        # 1. coord2address — 지번 본번·부번 획득
        res = requests.get(
            "https://dapi.kakao.com/v2/local/geo/coord2address.json",
            headers=_kakao_headers(),
            params={"x": lng, "y": lat, "input_coord": "WGS84"},
            timeout=5,
        )
        res.raise_for_status()
        docs = res.json().get("documents", [])
        if not docs:
            return {}

        addr   = docs[0].get("address") or {}
        b_code = addr.get("b_code", "")
        bun    = addr.get("main_address_no", "")
        ji     = addr.get("sub_address_no",  "")

        # 2. b_code 뒤 5자리가 00000 이면 regioncode API 로 법정동 코드 보완
        bjdong_5 = b_code[5:] if len(b_code) == 10 else ""
        if not bjdong_5 or bjdong_5 == "00000":
            try:
                rc_res = requests.get(
                    "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json",
                    headers=_kakao_headers(),
                    params={"x": lng, "y": lat, "input_coord": "WGS84"},
                    timeout=5,
                )
                rc_res.raise_for_status()
                for region in rc_res.json().get("documents", []):
                    if region.get("region_type") == "B":   # 법정동
                        b_code = region.get("code", b_code)
                        break
            except Exception as e2:
                print(f"[geocode] regioncode 보완 오류: {e2}")

        print(f"[geocode] 역지오코딩 → b_code={b_code} bun={bun} ji={ji} "
              f"({addr.get('address_name','')})")
        return {
            "b_code":     b_code,
            "sigungu_cd": b_code[:5] if b_code else "",
            "bjdong_cd":  b_code,
            "bun":        bun,
            "ji":         ji,
        }
    except Exception as e:
        print(f"[geocode] 역지오코딩 오류: {e}")
        return {}


# ─────────────────────────────────────────
#  4. 카카오 주소검색 — building_name 포함 파싱
# ─────────────────────────────────────────

def _address_search(query: str) -> Optional[dict]:
    """
    카카오 주소검색 API 호출.
    road_address.building_name 포함하여 반환.

    반환:
        {
            "x", "y",
            "address_name",
            "road_address_name",
            "building_name",     ← 핵심: 래미안원베일리 등
            "region_1depth", "region_2depth", "region_3depth",
        }
    """
    try:
        res = requests.get(
            KAKAO_ADDR_URL,
            headers=_kakao_headers(),
            params={"query": query, "size": 1},
            timeout=5,
        )
        res.raise_for_status()
        docs = res.json().get("documents", [])
        if not docs:
            return None

        d    = docs[0]
        road = d.get("road_address") or {}
        addr = d.get("address") or {}

        # 법정동코드 (b_code: 10자리) → 시군구코드 앞 5자리
        b_code     = addr.get("b_code", "")
        sigungu_cd = b_code[:5] if b_code else ""
        bun_val    = addr.get("main_address_no", "")
        ji_val     = addr.get("sub_address_no",  "")

        # bun 없거나 b_code 뒤 5자리가 00000이면
        # 해당 좌표로 바로 역지오코딩 → 정확한 지번 보완
        bjdong_5 = b_code[5:] if len(b_code) == 10 else ""
        if not bun_val or not bjdong_5 or bjdong_5 == "00000":
            x_val = d.get("x", "")
            y_val = d.get("y", "")
            if x_val and y_val:
                jibun = _coord2jibun(float(y_val), float(x_val))
                if jibun.get("bun"):
                    b_code     = jibun["bjdong_cd"]
                    sigungu_cd = jibun["sigungu_cd"]
                    bun_val    = jibun["bun"]
                    ji_val     = jibun["ji"]
                    print(f"[address_search] 지번 보완: "
                          f"bun={bun_val} bjdong={b_code} "
                          f"({addr.get('address_name', '')})")

        return {
            "x":                 d.get("x", ""),
            "y":                 d.get("y", ""),
            "address_name":      d.get("address_name", ""),
            "road_address_name": road.get("address_name", ""),
            "building_name":     road.get("building_name", "").strip(),
            "region_1depth":     road.get("region_1depth_name") or addr.get("region_1depth_name", ""),
            "region_2depth":     road.get("region_2depth_name") or addr.get("region_2depth_name", ""),
            "region_3depth":     addr.get("region_3depth_name") or road.get("region_3depth_name", ""),
            # 건축물대장 조회용 지번 정보
            "sigungu_cd": sigungu_cd,
            "bjdong_cd":  b_code,
            "bun":        bun_val,
            "ji":         ji_val,
        }

    except Exception as e:
        print(f"[address_search] 오류: {e}")
        return None


# ─────────────────────────────────────────
#  5. 카카오 키워드검색 — place_name + category 파싱
# ─────────────────────────────────────────

def _keyword_search(query: str, size: int = 5) -> list[dict]:
    """
    카카오 키워드검색 API 호출.
    place_name + category_name 반환.
    """
    # 특수문자 제거 (주), (유), (주식회사) → 공백으로 대체
    clean_query = re.sub(r'\([주유]\)|\(주식회사\)', ' ', query).strip()
    # 나머지 특수문자도 공백으로
    clean_query = re.sub(r'[^\w\s가-힣A-Za-z0-9]', ' ', clean_query).strip()
    clean_query = re.sub(r'\s+', ' ', clean_query).strip()
    if clean_query != query:
        print(f"[keyword_search] 쿼리 정제: '{query}' → '{clean_query}'")
    try:
        res = requests.get(
            KAKAO_KWD_URL,
            headers=_kakao_headers(),
            params={"query": clean_query, "size": size},
            timeout=5,
        )
        res.raise_for_status()
        return res.json().get("documents", [])
    except Exception as e:
        print(f"[keyword_search] 오류: {e}")
        return []


def _get_category_from_exact_place(
    building_name: str,
    *,
    expected_address: str,
    lat: float,
    lng: float,
) -> tuple[str, str, str, int]:
    """주소와 건물명이 모두 맞는 카카오 장소만 유형 보조 근거로 사용한다.

    키워드 검색의 첫 결과는 건물 내부 상점이나 인근 중개업소일 수 있다. 따라서
    동일 시군구·건물명 유사·300m 이내 조건을 모두 통과하지 않으면 버린다.
    """
    if not building_name:
        return "", "", "", 0

    expected_region = expected_address.split()[:2]
    expected_name = re.sub(r"[^0-9A-Za-z가-힣]", "", building_name).lower()
    expected_address_compact = re.sub(r"\s+", "", expected_address)
    docs = _keyword_search(building_name, size=5)
    candidates: list[tuple[int, str, str, str]] = []
    for doc in docs:
        doc_address = doc.get("road_address_name") or doc.get("address_name", "")
        if expected_region and doc_address.split()[:2] != expected_region:
            continue

        place_name = re.sub(r"[^0-9A-Za-z가-힣]", "", doc.get("place_name", "")).lower()
        if not expected_name or not place_name or (
            expected_name not in place_name and place_name not in expected_name
        ):
            continue

        try:
            if _distance_m(lat, lng, float(doc["y"]), float(doc["x"])) > 300:
                continue
        except (KeyError, TypeError, ValueError):
            continue

        cat_name = doc.get("category_name", "")
        prop_cat, detail = _map_kakao_category(cat_name)
        if prop_cat:
            score = 20  # 시군구 일치
            score += 35 if expected_name == place_name else 20
            if expected_address_compact == re.sub(r"\s+", "", doc_address):
                score += 35
            distance = _distance_m(lat, lng, float(doc["y"]), float(doc["x"]))
            score += 20 if distance <= 50 else (10 if distance <= 150 else 5)
            if any(word in cat_name for word in ("중개업소", "음식점", "의류판매")):
                score -= 50
            candidates.append((score, cat_name, prop_cat, detail))

    if not candidates:
        return "", "", "", 0

    candidates.sort(key=lambda item: item[0], reverse=True)
    best = candidates[0]
    if best[0] < 55:
        return "", "", "", best[0]
    # 점수가 비슷한 후보가 서로 다른 부동산 유형이면 임의 선택하지 않는다.
    if len(candidates) > 1 and best[0] - candidates[1][0] < 10 and best[2] != candidates[1][2]:
        print(f"[category] 장소 후보 경합으로 자동 확정 보류: {candidates[:2]}")
        return "", "", "", best[0]

    print(
        f"[category] 정확한 장소 일치({best[0]}점): "
        f"'{building_name}' → {best[1]} → {best[2]}/{best[3]}"
    )
    return best[1], best[2], best[3], best[0]


def _resolve_property_category(
    addr_info: dict,
    *,
    confirmed_category: str = "",
    confirmed_detail: str = "",
    dong_no: str = "",
    ho_no: str = "",
) -> CategoryResolution:
    """사용자 확정값과 공식·결정론적 데이터만으로 최종 유형을 정한다."""
    resolution = CategoryResolution(
        selected_category=(
            confirmed_category if confirmed_category in VALID_PROPERTY_CATEGORIES else ""
        ),
        selected_detail=confirmed_detail,
    )

    sigungu_cd = addr_info.get("sigungu_cd", "")
    bjdong_cd = addr_info.get("bjdong_cd", "")
    bun = addr_info.get("bun", "")
    ji = addr_info.get("ji", "")
    if sigungu_cd and bjdong_cd and bun:
        try:
            from building_info import fetch_building_info, fetch_unit_info

            if dong_no or ho_no:
                unit = fetch_unit_info(
                    sigungu_cd, bjdong_cd, bun, ji, dong_no, ho_no
                )
                if unit:
                    resolution.unit_use = unit.get("main_purps", "") or ""
                    unit_category, unit_detail = _map_building_use(resolution.unit_use)
                    if unit_category:
                        resolution.official_category = unit_category
                        resolution.official_detail = unit_detail
                        resolution.official_source = "unit_register"

            building = fetch_building_info(sigungu_cd, bjdong_cd, bun, ji)
            if building:
                resolution.building_main_use = building.get("main_purps", "") or ""
                building_category, building_detail = _map_building_use(
                    resolution.building_main_use
                )
                if building_category and not resolution.official_category:
                    resolution.official_category = building_category
                    resolution.official_detail = building_detail
                    resolution.official_source = "building_register"
        except Exception as exc:
            print(f"[category] 건축물대장 유형 조회 오류: {exc}")

    if resolution.selected_category:
        resolution.category = resolution.selected_category
        resolution.detail = resolution.selected_detail
        resolution.source = "user"
        resolution.confidence = 1.0
        resolution.evidence = f"사용자 직접 선택: {resolution.category}/{resolution.detail}"
        if (
            resolution.official_category
            and resolution.official_category != resolution.selected_category
        ):
            resolution.conflict = True
            resolution.conflict_message = (
                f"선택한 유형({resolution.selected_category})과 "
                f"건축물대장 확인 유형({resolution.official_category})이 다릅니다. "
                "복합용도 건물 또는 개별 호실 용도를 확인해주세요."
            )
        return resolution

    if resolution.official_category:
        resolution.category = resolution.official_category
        resolution.detail = resolution.official_detail
        if resolution.official_source == "unit_register":
            resolution.source = "unit_register"
            resolution.confidence = 1.0
            resolution.evidence = f"건축물대장 전유부 용도: {resolution.unit_use}"
        else:
            resolution.source = "building_register"
            resolution.confidence = 0.95
            resolution.evidence = f"건축물대장 주용도: {resolution.building_main_use}"
        return resolution

    building_name = addr_info.get("building_name", "")
    category, detail = _map_building_name(building_name)
    if category:
        resolution.category = category
        resolution.detail = detail
        resolution.source = "building_name_rule"
        resolution.confidence = 0.8
        resolution.evidence = f"명확한 건물명 규칙: {building_name}"
        return resolution

    lat = float(addr_info.get("y") or 0)
    lng = float(addr_info.get("x") or 0)
    kakao_cat, category, detail, place_score = _get_category_from_exact_place(
        building_name,
        expected_address=addr_info.get("address_name", ""),
        lat=lat,
        lng=lng,
    )
    if category:
        resolution.category = category
        resolution.detail = detail
        resolution.source = "kakao_exact"
        resolution.confidence = 0.7
        resolution.evidence = f"검증된 카카오 장소 카테고리: {kakao_cat} ({place_score}점)"
        resolution.kakao_category = kakao_cat
    return resolution

def _parse_region(address_name: str) -> tuple[str, str, str]:
    """
    카카오 address_name 문자열 → (시도, 시군구, 읍면동) 구조화 파싱.

    공백 split 인덱스 대신 행정단위 접미사 기반으로 파싱하여
    "경기 수원시 팔달구 우만동" 같은 다단계 주소를 정확히 처리.
    """
    parts = address_name.split()
    r1 = parts[0] if parts else ""
    r2_parts: list[str] = []
    r3 = ""
    for p in parts[1:]:
        last = p[-1:] if p else ""
        if last in ("시", "군", "구"):
            r2_parts.append(p)
        elif last in ("읍", "면", "동", "가", "리"):
            r3 = p
            break
    return r1, " ".join(r2_parts), r3


def _print_geocoding_metric(result: GeocodingResult) -> None:
    """주소 원문 없이 운영 품질을 집계할 수 있는 구조화 로그를 남긴다."""
    print(
        "[geocode-metric] "
        f"method={result.method} source={result.category_source} "
        f"category={result.property_category or 'unknown'} "
        f"conflict={str(result.category_conflict).lower()} "
        f"land_status={result.land_info_status}"
    )


# ─────────────────────────────────────────
#  6. 통합 지오코딩 진입점
# ─────────────────────────────────────────

def geocode(
    location: str,
    category: str = "",
    building_hint: str = "",
    *,
    confirmed_category: str = "",
    confirmed_detail: str = "",
    dong_no: str = "",
    ho_no: str = "",
) -> Optional[GeocodingResult]:
    """
    주소 입력 → 좌표 + 건물명 + 부동산 유형 획득.

    building_hint: 사용자가 선택한 건물명 (예: 아모레퍼시픽 오산공장)
                   주소가 시·구 단위로 모호할 때 키워드검색으로 정확한 지번 획득

    category는 LLM이 만든 검색 힌트이며 최종 유형 결정에는 사용하지 않는다.
    confirmed_category는 UI/API에서 사용자가 직접 고른 값이라 최우선으로 사용한다.

    1순위: building_hint 키워드검색 → 정확한 좌표·지번 획득
    2순위: 주소검색 → building_name 추출
    3순위: 역지오코딩으로 지번 보완
    4순위: 사용자 확정값·건축물대장·검증된 장소 규칙으로 유형 확정
    """
    # 주소에 건물명이 혼합된 경우 분리
    # 예: "경기도 용인시 기흥구 보라동 57번길 10 삼성전자(주)기흥캠퍼스"
    #   → location = "경기도 용인시 기흥구 보라동 57번길 10"
    #   → building_hint = "삼성전자(주)기흥캠퍼스" (없을 때만)
    # 도로명 주소 패턴 뒤에 건물명이 붙은 경우 감지
    road_pattern = re.match(
        r'^(.+(?:로|길|대로)\s*\d+(?:-\d+)?)\s+([가-힣A-Za-z\(\)·\.\s]{2,})$',
        location.strip()
    )
    if road_pattern:
        addr_part  = road_pattern.group(1).strip()
        bldg_part  = road_pattern.group(2).strip()
        if not building_hint:
            building_hint = bldg_part
        location = addr_part
        print(f"[geocode] 주소/건물명 분리: '{addr_part}' / '{bldg_part}'")

    print(f"[geocode] 입력: '{location}'" + (f" / 건물힌트: '{building_hint}'" if building_hint else ""))

    # ── 0순위: building_hint 키워드검색 → 정확한 좌표·지번 ──────────────
    # 사용자가 건물명을 선택했을 때 해당 건물의 정확한 지번 확보
    # 단, 힌트의 시군구코드가 입력 주소와 다르면 무시 (엉뚱한 건물 방지)
    hint_jibun = {}
    if building_hint:
        hint_docs = _keyword_search(building_hint, size=1)
        if hint_docs:
            hint_addr_name = hint_docs[0].get("address_name", "")
            hint_addr_info = _address_search(hint_addr_name)
            if hint_addr_info and hint_addr_info.get("bun"):
                hint_sigungu = hint_addr_info.get("sigungu_cd", "")
                # 입력 주소도 주소검색해서 시군구 코드 비교
                loc_addr_info = _address_search(location)
                loc_sigungu   = loc_addr_info.get("sigungu_cd", "") if loc_addr_info else ""
                # 시군구가 일치하거나 입력 주소에서 코드를 못 가져온 경우만 힌트 사용
                if not loc_sigungu or hint_sigungu == loc_sigungu:
                    hint_jibun = {
                        "sigungu_cd": hint_sigungu,
                        "bjdong_cd":  hint_addr_info.get("bjdong_cd", ""),
                        "bun":        hint_addr_info.get("bun",       ""),
                        "ji":         hint_addr_info.get("ji",        ""),
                    }
                    print(f"[geocode] 건물힌트 지번: {hint_addr_name} "
                          f"→ bun={hint_jibun['bun']} bjdong={hint_jibun['bjdong_cd']}")
                else:
                    print(f"[geocode] 건물힌트 지역 불일치 무시 "
                          f"(힌트:{hint_sigungu} ≠ 입력:{loc_sigungu})")
            else:
                hint_lat = float(hint_docs[0].get("y", 0))
                hint_lng = float(hint_docs[0].get("x", 0))
                if hint_lat and hint_lng:
                    hint_jibun = _coord2jibun(hint_lat, hint_lng)
                    print(f"[geocode] 건물힌트 역지오코딩: bun={hint_jibun.get('bun')} "
                          f"bjdong={hint_jibun.get('bjdong_cd')}")

    # ── 1순위: 주소검색 → building_name ──────────────────────────────────
    addr_info = _address_search(location)

    if addr_info:
        lat = float(addr_info["y"])
        lng = float(addr_info["x"])
        building_name = addr_info["building_name"]

        print(f"[geocode] 주소검색 성공 → {lat:.4f}, {lng:.4f}")
        if building_name:
            print(f"[geocode] building_name: '{building_name}'")

        # 지번 보완 우선순위: hint_jibun > addr_info (addr_info는 이미 역지오코딩 포함)
        if hint_jibun:
            final_sigungu = hint_jibun.get("sigungu_cd", "")
            final_bjdong  = hint_jibun.get("bjdong_cd",  "")
            final_bun     = hint_jibun.get("bun",        "")
            final_ji      = hint_jibun.get("ji",         "")
            print(f"[geocode] 힌트 지번 적용: bun={final_bun} bjdong={final_bjdong}")
        else:
            final_sigungu = addr_info.get("sigungu_cd", "")
            final_bjdong  = addr_info.get("bjdong_cd",  "")
            final_bun     = addr_info.get("bun",        "")
            final_ji      = addr_info.get("ji",         "")

        # LLM category는 후보일 뿐이다. 사용자 선택·전유부·건물대장·검증된
        # 장소 규칙만 최종 부동산 유형의 근거로 사용한다.
        category_addr_info = {
            **addr_info,
            "sigungu_cd": final_sigungu,
            "bjdong_cd": final_bjdong,
            "bun": final_bun,
            "ji": final_ji,
        }
        resolution = _resolve_property_category(
            category_addr_info,
            confirmed_category=confirmed_category,
            confirmed_detail=confirmed_detail,
            dong_no=dong_no,
            ho_no=ho_no,
        )

        result = GeocodingResult(
            lat=lat,
            lng=lng,
            address_name=addr_info["address_name"],
            region_1depth=addr_info["region_1depth"],
            region_2depth=addr_info["region_2depth"],
            region_3depth=addr_info["region_3depth"],
            method="address",
            confidence=1.0,
            place_name=building_name,
            kakao_category=resolution.kakao_category,
            property_category=resolution.category,
            category_detail=resolution.detail,
            category_source=resolution.source,
            category_confidence=resolution.confidence,
            category_evidence=resolution.evidence,
            selected_category=resolution.selected_category,
            official_category=resolution.official_category,
            official_detail=resolution.official_detail,
            building_main_use=resolution.building_main_use,
            unit_use=resolution.unit_use,
            category_conflict=resolution.conflict,
            category_conflict_message=resolution.conflict_message,
            sigungu_cd=final_sigungu,
            bjdong_cd =final_bjdong,
            bun       =final_bun,
            ji        =final_ji,
        )

        # 토지·산업용·업무용·상업용 → Vworld 공시지가 조회
        if result.property_category in ("토지", "산업용", "업무용", "상업용"):
            _attach_land_info(result)

        print(f"[geocode] ✅ 완료: '{result.place_name}' / "
              f"{result.property_category}/{result.category_detail} "
              f"({result.category_source})")
        _print_geocoding_metric(result)
        return result

    # ── 2순위: 키워드검색 폴백 ───────────────────────────────────────────
    print(f"[geocode] 주소검색 실패 → 키워드검색 폴백")
    # 주소검색 실패 시 building_hint로 키워드검색 시도 (더 정확)
    docs = []
    if building_hint:
        docs = _keyword_search(building_hint, size=3)
        if docs:
            print(f"[geocode] 건물힌트 키워드검색 성공: '{building_hint}'")
    if not docs:
        docs = _keyword_search(location, size=5)

    for doc in docs:
        cat_name = doc.get("category_name", "")
        if confirmed_category in VALID_PROPERTY_CATEGORIES:
            prop_cat, detail, category_source = (
                confirmed_category,
                confirmed_detail,
                "user",
            )
            category_confidence = 1.0
            category_evidence = f"사용자 직접 선택: {prop_cat}/{detail}"
        else:
            prop_cat, detail = _map_building_name(doc.get("place_name", ""))
            category_source = "building_name_rule" if prop_cat else "unknown"
            category_confidence = 0.8 if prop_cat else 0.0
            category_evidence = (
                f"명확한 건물명 규칙: {doc.get('place_name', '')}" if prop_cat else ""
            )
            # 건물명을 직접 검색한 경우에만 카카오 장소 유형을 허용한다.
            if not prop_cat and building_hint:
                expected = re.sub(r"[^0-9A-Za-z가-힣]", "", building_hint).lower()
                actual = re.sub(r"[^0-9A-Za-z가-힣]", "", doc.get("place_name", "")).lower()
                if expected and actual and (expected in actual or actual in expected):
                    prop_cat, detail = _map_kakao_category(cat_name)
                    category_source = "kakao_exact" if prop_cat else "unknown"
                    category_confidence = 0.7 if prop_cat else 0.0
                    category_evidence = (
                        f"검증된 카카오 장소 카테고리: {cat_name}" if prop_cat else ""
                    )

        r1, r2, r3 = _parse_region(doc.get("address_name", ""))
        result = GeocodingResult(
            lat=float(doc["y"]),
            lng=float(doc["x"]),
            address_name=doc.get("address_name", ""),
            region_1depth=r1,
            region_2depth=r2,
            region_3depth=r3,
            method="keyword",
            confidence=0.85,
            place_name=doc.get("place_name", ""),
            kakao_category=cat_name,
            property_category=prop_cat,
            category_detail=detail,
            category_source=category_source,
            category_confidence=category_confidence,
            category_evidence=category_evidence,
            selected_category=(
                confirmed_category if confirmed_category in VALID_PROPERTY_CATEGORIES else ""
            ),
        )

        # 토지·산업용·업무용·상업용 → Vworld 공시지가 조회
        if result.property_category in ("토지", "산업용", "업무용", "상업용"):
            _attach_land_info(result)

        print(f"[geocode] ✅ 키워드 완료: '{result.place_name}' / "
              f"{result.property_category}/{result.category_detail}")
        _print_geocoding_metric(result)
        return result

    # ── 3순위: 전부 실패 ─────────────────────────────────────────────────
    print(f"[geocode] ❌ 변환 실패: '{location}'")
    return None


# ─────────────────────────────────────────
#  7. Vworld — 토지 법적 정보
# ─────────────────────────────────────────

VWORLD_LAND_URL = "https://api.vworld.kr/req/data"


def _attach_land_info(result: GeocodingResult):
    info, status = _fetch_land_info_vworld(result.lat, result.lng)
    result.land_info_status = status
    if info:
        result.land_use_zone        = info.get("land_use_zone", "")
        result.land_area            = info.get("land_area", 0.0)
        result.official_land_price  = info.get("official_land_price", 0)
        print(f"[vworld] 용도지역: {result.land_use_zone}")


def _fetch_land_info_vworld(lat: float, lng: float) -> tuple[Optional[dict], str]:
    if not VWORLD_API_KEY:
        return None, "not_configured"
    params = {
        "service": "data", "request": "GetFeature",
        "data": "LT_C_LHBLPN", "key": VWORLD_API_KEY,
        "format": "json", "size": "1", "page": "1",
        "geometry": "true", "attribute": "true",
        "crs": "EPSG:4326", "geomFilter": f"POINT({lng} {lat})",
    }
    try:
        res = requests.get(VWORLD_LAND_URL, params=params, timeout=8)
        res.raise_for_status()
        response = res.json().get("response", {})
        api_status = response.get("status", "")
        features = (
            response
               .get("result", {})
               .get("featureCollection", {})
               .get("features", [])
        )
        if not features:
            return None, "not_found" if api_status == "NOT_FOUND" else "api_error"
        props = features[0].get("properties", {})
        return {
            "land_use_zone":       props.get("prpos_area1_nm", ""),
            "land_area":           float(props.get("lndpcp_ar", 0)),
            "official_land_price": int(props.get("pblntf_pric", 0)),
        }, "found"
    except Exception as e:
        print(f"[vworld] 오류: {e}")
        return None, "request_error"


def get_land_info_vworld(lat: float, lng: float) -> Optional[dict]:
    """기존 호출부를 유지하면서 상세 상태는 GeocodingResult에 기록한다."""
    info, _ = _fetch_land_info_vworld(lat, lng)
    return info


# ─────────────────────────────────────────
#  8. LangGraph 노드
# ─────────────────────────────────────────

def geocoding_node(state):
    def _g(s, key, default=None):
        if isinstance(s, dict): return s.get(key, default)
        return getattr(s, key, default)

    def _s(s, key, value):
        if isinstance(s, dict): s[key] = value
        else: object.__setattr__(s, key, value)
        return s

    intent = _g(state, "intent")
    if not intent:
        return _s(state, "error", "geocoding_node: intent 없음")

    # 위치 우선순위:
    # 1. raw_inputs["address"] — 사용자가 입력한 원본 주소 (가장 정확)
    # 2. location_normalized   — LLM이 파싱한 위치 (축약 가능성 있음)
    # 3. location_raw          — 원본 쿼리
    raw_inputs = _g(state, "raw_inputs") or {}
    raw_address = raw_inputs.get("address", "") if isinstance(raw_inputs, dict) else ""
    confirmed_category = raw_inputs.get("property_category", "") if isinstance(raw_inputs, dict) else ""
    confirmed_detail = raw_inputs.get("property_detail", "") if isinstance(raw_inputs, dict) else ""
    confirmed_area = raw_inputs.get("area_sqm") if isinstance(raw_inputs, dict) else None
    if isinstance(confirmed_area, (int, float)) and confirmed_area > 0:
        # 사용자가 확인한 면적을 LLM의 재해석으로 바꾸지 않는다.
        intent.area_min = intent.area_max = confirmed_area
        intent.area_raw = f"{confirmed_area}㎡"

    location = (raw_address
                or getattr(intent, "location_normalized", "")
                or getattr(intent, "location_raw", ""))
    if not location:
        return _s(state, "error", "geocoding_node: 위치 정보 없음")

    if raw_address and raw_address != getattr(intent, "location_normalized", ""):
        print(f"[geocoding_node] 원본 주소 사용: '{raw_address}' "
              f"(LLM 파싱: '{getattr(intent, 'location_normalized', '')}')")

    llm_category  = getattr(intent, "category", "")
    dong_no = getattr(intent, "dong_no", "") or ""
    ho_no = getattr(intent, "ho_no", "") or ""
    building_hint = _g(state, "building_name", "") or ""
    result = geocode(
        location,
        category=llm_category,
        building_hint=building_hint,
        confirmed_category=confirmed_category,
        confirmed_detail=confirmed_detail,
        dong_no=dong_no,
        ho_no=ho_no,
    )

    if not result:
        return _s(state, "error", f"좌표 변환 실패: '{location}'")

    # 최종 라우팅에는 LLM 후보가 아니라 검증된 유형만 사용한다.
    if result.property_category and result.category_source != "unknown":
        try:
            old = intent.category
            intent.category = result.property_category
            if result.category_detail:
                intent.category_detail = result.category_detail
            print(
                f"[geocoding_node] category: {old} → {result.property_category} "
                f"({result.category_source})"
            )
        except Exception:
            pass
    else:
        return _s(
            state,
            "error",
            "공식 데이터로 부동산 유형을 확인하지 못했습니다. 물건 종류를 직접 선택해주세요.",
        )

    # place_name → building_name 자동 설정 (사용자 미입력 시)
    if result.place_name and not _g(state, "building_name", ""):
        _s(state, "building_name", result.place_name)
        print(f"[geocoding_node] building_name 자동 설정: '{result.place_name}'")

    # 전국 확대: 성공한 지오코딩의 시군구코드를 지역코드 테이블에 자동 등록
    # (배치 수집 CLI·백테스트 등 지역명 기반 도구가 새 지역을 바로 쓸 수 있게)
    if result.region_2depth and result.sigungu_cd:
        try:
            from cache_db import add_region_code
            add_region_code(result.region_2depth, result.sigungu_cd[:5],
                            sido=result.region_1depth, sigungu=result.region_2depth,
                            overwrite=False)
        except Exception:
            pass

    _s(state, "geocoding_result", result.model_dump())
    _s(state, "error", "")
    return state


# ─────────────────────────────────────────
#  9. 캐싱
# ─────────────────────────────────────────

_GEOCODE_TTL = 60 * 60 * 24 * 7  # 7일
_GEOCODE_ALGORITHM_VERSION = "v4"


def geocode_cached(
    location: str,
    category: str = "",
    building_hint: str = "",
    *,
    confirmed_category: str = "",
    confirmed_detail: str = "",
    dong_no: str = "",
    ho_no: str = "",
) -> Optional[GeocodingResult]:
    cached = cache_get(
        "geocode",
        location=location,
        category=category,
        building_hint=building_hint,
        confirmed_category=confirmed_category,
        confirmed_detail=confirmed_detail,
        dong_no=dong_no,
        ho_no=ho_no,
        algorithm_version=_GEOCODE_ALGORITHM_VERSION,
    )
    if cached is not None:
        print(f"[cache] geocode 히트: '{location}'")
        return GeocodingResult(**cached)
    result = geocode(
        location,
        category,
        building_hint,
        confirmed_category=confirmed_category,
        confirmed_detail=confirmed_detail,
        dong_no=dong_no,
        ho_no=ho_no,
    )
    if result:
        cache_set(result.model_dump(), ttl=_GEOCODE_TTL, namespace="geocode",
                  location=location, category=category, building_hint=building_hint,
                  confirmed_category=confirmed_category, confirmed_detail=confirmed_detail,
                  dong_no=dong_no, ho_no=ho_no,
                  algorithm_version=_GEOCODE_ALGORITHM_VERSION)
    return result


# ─────────────────────────────────────────
#  10. CLI 테스트
# ─────────────────────────────────────────

if __name__ == "__main__":
    if not KAKAO_API_KEY:
        print("⚠️  KAKAO_REST_API_KEY 없음")
    else:
        tests = [
            "서울시 서초구 반포대로 333",       # 래미안원베일리 (아파트)
            "서울시 마포구 백범로 192",          # 마포래미안푸르지오 (아파트)
            "서울시 강남구 테헤란로 152",        # 강남파이낸스센터 (업무용)
            "서울시 영등포구 여의대로 108",      # 파크원 (업무용)
            "경기도 성남시 분당구 판교역로 235", # 판교테크노밸리 (산업용)
            "부산시 해운대구 해운대해변로 264",  # (상업용)
        ]
        print("=" * 60)
        for addr in tests:
            print(f"\n📍 입력: {addr}")
            r = geocode_cached(addr)
            if r:
                print(f"   building_name : {r.place_name or '(없음)'}")
                print(f"   카카오 카테고리: {r.kakao_category or '(없음)'}")
                print(f"   부동산 유형   : {r.property_category or '(미판단)'} / {r.category_detail}")
                print(f"   판단 근거     : {r.category_source}")
                print(f"   행정구역      : {r.region_2depth} {r.region_3depth}")
            else:
                print("   ❌ 실패")
            time.sleep(0.3)
