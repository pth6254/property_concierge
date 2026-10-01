"""
agents.py — 5개 전문 에이전트 v2.2
개선:
  - 감정평가서 필수 항목 추가:
    land_use_zone, official_land_price, build_year, exclusive_area_m2
    legal_restrictions, development_plans, comparable_avg/count 버그 수정
"""

from __future__ import annotations
from datetime import datetime
from building_info import get_building_area

import re

from models import ValuationResult, _intent_summary
from price_engine import (
    calc_estimated_value,
    calc_investment_return,
    fetch_real_transaction_prices,
    calc_cost_approach,
    _fetch_by_income_approach,
)
from llm_utils import (
    generate_appraisal_opinion,
    search_nearby_facilities,
    search_web_tavily,
)


# ─────────────────────────────────────────
#  공공 제한·개발계획 키워드
# ─────────────────────────────────────────

_LEGAL_KEYWORDS = [
    "토지거래허가구역", "투기과열지구", "조정대상지역", "분양가상한제",
    "재개발구역", "재건축구역", "정비구역", "개발제한구역",
    "군사시설보호구역", "문화재보호구역",
]

_DEV_KEYWORDS = [
    "GTX", "재건축", "재개발", "신도시", "지하철", "역세권 개발",
    "산업단지", "뉴타운", "개발호재", "도시개발", "복합환승센터",
]


def _parse_web_info(web: str) -> tuple[list[str], list[str]]:
    """web_summary에서 공법제한·개발계획 키워드를 추출한다."""
    restrictions = [kw for kw in _LEGAL_KEYWORDS if kw in web]
    developments = [kw for kw in _DEV_KEYWORDS if kw in web]
    return restrictions, developments


# ─────────────────────────────────────────
#  공통 헬퍼
# ─────────────────────────────────────────

def _extract_context(state: dict):
    intent   = state.get("intent")
    geo      = state.get("geocoding_result") or {}
    region   = geo.get("region_2depth", "") if isinstance(geo, dict) else getattr(geo, "region_2depth", "")
    region3  = geo.get("region_3depth", "") if isinstance(geo, dict) else getattr(geo, "region_3depth", "")
    return intent, geo, region, region3


def _get_appraisal_date(intent) -> str:
    return getattr(intent, "appraisal_date", "") or ""


def _geo_coords(geo) -> tuple[float, float]:
    if isinstance(geo, dict):
        return geo.get("lat", 0.0), geo.get("lng", 0.0)
    return getattr(geo, "lat", 0.0), getattr(geo, "lng", 0.0)


def _geo_val(geo, key: str, default=None):
    if isinstance(geo, dict):
        return geo.get(key, default)
    return getattr(geo, key, default)


def _save_result(state: dict, result: ValuationResult) -> dict:
    return {**state, "analysis_result": result.model_dump()}


_VAGUE_AREA_KEYWORDS = ["평대", "이상", "이하", "이내", "정도", "내외", "쯤", "약"]

def _get_area_sqm(intent) -> float:
    area_raw = getattr(intent, "area_raw", "") or ""
    if any(kw in area_raw for kw in _VAGUE_AREA_KEYWORDS):
        print(f"[면적] '{area_raw}' 애매한 표현 → 건축물대장 우선 조회")
        return 0.0
    area_min = getattr(intent, "area_min", None) or 0.0
    area_max = getattr(intent, "area_max", None) or 0.0
    if area_min and area_max:
        return (area_min + area_max) / 2
    return area_min or area_max or 0.0


def _get_asking_price(intent) -> int:
    return getattr(intent, "price_max", None) or getattr(intent, "price_min", None) or 0


_BUILDING_SUFFIXES = ["아파트", "빌라", "오피스텔", "주상복합", "타운", "빌딩", "타워"]

def _get_building_name(state: dict) -> str:
    name = state.get("building_name", "").strip()
    for suffix in _BUILDING_SUFFIXES:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
            break
    return name


def _print_result(result: ValuationResult):
    print(f"\n  ┌─ 감정평가 결과 ({result.agent_name}) ─────────────────")
    print(f"  │ 추정 시장가치 : {result.estimated_value:>10,}만원")
    print(f"  │ 가치 범위     : {result.value_min:,} ~ {result.value_max:,}만원")
    print(f"  │ 평당가        : {result.price_per_pyeong:,}만원/평  (지역평균: {result.regional_avg_per_pyeong:,}만원/평)")
    print(f"  │ 비교사례      : {result.comparable_count}건 평균 {result.comparable_avg:,}만원")
    print(f"  │ Cap Rate      : {result.cap_rate}%  |  연 수입 추정: {result.annual_income:,}만원")
    print(f"  │ 투자등급      : {result.investment_grade}")
    print(f"  │ 추천          : {result.recommendation}")
    print(f"  └─────────────────────────────────────────────────")


def _empty_result(agent_name: str, error_msg: str) -> ValuationResult:
    return ValuationResult(
        agent_name=agent_name,
        appraisal_opinion=f"감정평가 중 오류가 발생했습니다: {error_msg}",
        recommendation="재시도 필요",
    )


def _auto_fill_area(state: dict, area_sqm: float, prefer: str = "tot") -> tuple[float, int, str]:
    """
    면적 미입력 시 자동 조회 (우선순위):
    1. 건축물대장 API
    2. Vworld 토지면적
    3. RAG 유사 매물 면적 평균
    """
    if area_sqm > 0:
        return area_sqm, 0, ""

    geo_dict   = state.get("geocoding_result") or {}
    sigungu_cd = geo_dict.get("sigungu_cd", "") if isinstance(geo_dict, dict) else getattr(geo_dict, "sigungu_cd", "")
    bjdong_cd  = geo_dict.get("bjdong_cd",  "") if isinstance(geo_dict, dict) else getattr(geo_dict, "bjdong_cd",  "")
    bun        = geo_dict.get("bun",        "") if isinstance(geo_dict, dict) else getattr(geo_dict, "bun",        "")
    ji         = geo_dict.get("ji",         "") if isinstance(geo_dict, dict) else getattr(geo_dict, "ji",         "")

    if sigungu_cd and bun:
        from building_info import fetch_building_info
        info = fetch_building_info(sigungu_cd, bjdong_cd, bun, ji)
        if info:
            area_map  = {"tot": info["tot_area"], "arch": info["arch_area"], "plat": info["plat_area"]}
            auto_area = area_map.get(prefer, info["tot_area"])
            build_year = info["build_year"]
            strct_nm   = info.get("strct_cd_nm", "")
            if auto_area > 0:
                print(f"[건축물대장] 면적:{auto_area}㎡ / 건축연도:{build_year} / 구조:{strct_nm}")
                return auto_area, build_year, strct_nm

    land_area = geo_dict.get("land_area", 0.0) if isinstance(geo_dict, dict) else getattr(geo_dict, "land_area", 0.0)
    if land_area > 0:
        print(f"[면적 폴백] Vworld 토지면적 사용: {land_area}㎡")
        return float(land_area), 0, ""

    rag_matches = state.get("rag_top_matches", [])
    if rag_matches:
        areas = [
            m.get("metadata", {}).get("area", 0)
            for m in rag_matches
            if m.get("metadata", {}).get("area", 0) > 0
        ]
        if areas:
            avg_area = sum(areas) / len(areas)
            print(f"[면적 폴백] RAG 유사 매물 면적 평균 사용: {avg_area:.1f}㎡ ({len(areas)}건)")
            return float(avg_area), 0, ""

    return 0.0, 0, ""


def _fetch_build_year(state: dict) -> tuple[int, str]:
    """건축물대장에서 건축연도·구조만 조회 (면적과 무관)."""
    geo_dict   = state.get("geocoding_result") or {}
    sigungu_cd = geo_dict.get("sigungu_cd", "") if isinstance(geo_dict, dict) else getattr(geo_dict, "sigungu_cd", "")
    bjdong_cd  = geo_dict.get("bjdong_cd",  "") if isinstance(geo_dict, dict) else getattr(geo_dict, "bjdong_cd",  "")
    bun        = geo_dict.get("bun",        "") if isinstance(geo_dict, dict) else getattr(geo_dict, "bun",        "")
    ji         = geo_dict.get("ji",         "") if isinstance(geo_dict, dict) else getattr(geo_dict, "ji",         "")

    if sigungu_cd and bun:
        try:
            from building_info import fetch_building_info
            info = fetch_building_info(sigungu_cd, bjdong_cd, bun, ji)
            if info:
                return info.get("build_year", 0) or 0, info.get("strct_cd_nm", "") or ""
        except Exception:
            pass
    return 0, ""


# ═══════════════════════════════════════════════════════════════
#  1. 주거용 에이전트 (아파트·빌라·오피스텔)
# ═══════════════════════════════════════════════════════════════

def residential_agent(state: dict) -> dict:
    try:
        intent, geo, region, region3 = _extract_context(state)
        lat, lng       = _geo_coords(geo)
        location       = getattr(intent, "location_normalized", region)
        detail         = getattr(intent, "category_detail", "아파트")
        area_sqm       = _get_area_sqm(intent)
        asking         = _get_asking_price(intent)
        dong_no        = getattr(intent, "dong_no", "") or ""
        ho_no          = getattr(intent, "ho_no", "") or ""
        floor_inferred = getattr(intent, "floor_inferred", None)
        as_of          = _get_appraisal_date(intent)

        # 용도지역·공시지가 (geo에서 추출)
        land_use_zone   = _geo_val(geo, "land_use_zone", "") or ""
        official_price  = _geo_val(geo, "official_land_price", 0) or 0

        print(f"\n[주거용 에이전트] {location} / {detail} / {area_sqm}㎡")

        building_name = _get_building_name(state)

        # 건축연도 조회 (면적과 무관하게 건축물대장 API 호출)
        build_year_auto, strct_nm_auto = _fetch_build_year(state)

        # 호수 정보가 있으면 건축물대장 전유부로 정확한 면적 조회
        geo_dict   = state.get("geocoding_result") or {}
        sigungu_cd = _geo_val(geo_dict, "sigungu_cd", "")
        bjdong_cd  = _geo_val(geo_dict, "bjdong_cd",  "")
        bun        = _geo_val(geo_dict, "bun",        "")
        ji         = _geo_val(geo_dict, "ji",         "")

        if (dong_no or ho_no) and area_sqm == 0:
            from building_info import fetch_unit_area
            unit_area = fetch_unit_area(sigungu_cd, bjdong_cd, bun, ji, dong_no, ho_no)
            if unit_area and unit_area > 0:
                area_sqm = unit_area
                print(f"  → 전유부 면적 조회 성공: {area_sqm}㎡ ({dong_no} {ho_no})")

        price_data    = fetch_real_transaction_prices(
            "주거용", region, detail,
            apt_name=building_name, region_3depth=region3,
            floor=floor_inferred or 0,
            area_sqm_exact=area_sqm,
            as_of=as_of,
            lawd_code=sigungu_cd,   # 지오코딩 시군구코드 — 전국 어디든 동작
        )
        if building_name and price_data.get("apt_name_matched"):
            label = price_data.get("precision_filter", "")
            suffix = f" [{label}]" if label else ""
            print(f"  → 단지 감정평가: {price_data['apt_name_matched']} ({price_data['count']}건){suffix}")
        elif building_name:
            print(f"  → 단지명 '{building_name}' 미발견 — 지역 평균으로 대체")

        val  = calc_estimated_value(price_data, area_sqm, "주거용")
        roi  = calc_investment_return(val["estimated_value"], "주거용", area_sqm)

        nearby = search_nearby_facilities(lat, lng,
            ["지하철역", "학교", "편의점", "마트", "병원"], radius=1000)

        subway_m = nearby.get("지하철역", {}).get("nearest_m", 9999)
        if subway_m <= 300:
            val["estimated_value"] = round(val["estimated_value"] * 1.05)
            val["value_max"]       = round(val["value_max"] * 1.05)
        elif subway_m > 1000:
            val["estimated_value"] = round(val["estimated_value"] * 0.97)

        web     = search_web_tavily(f"{location} 아파트 시세 매매 실거래가")
        llm_out = generate_appraisal_opinion("주거용", location, {**val, **roi}, nearby, web)

        legal_restrictions, development_plans = _parse_web_info(web)

        result = ValuationResult(
            agent_name="주거용",
            valuation_method=(
                f"비교사례법 ({dong_no}{ho_no} 기준 동일타입 실거래)"
                if price_data.get("precision_filter")
                else "비교사례법 (인근 실거래 평균)"
            ),
            price_avg=price_data["avg"], price_min=price_data["min"],
            price_max=price_data["max"], price_sample_count=price_data["count"],
            comparable_avg=price_data["avg"], comparable_count=price_data["count"],
            comparables=price_data.get("samples", []),
            used_months=price_data.get("used_months", 0) or 0,
            nearby_facilities=nearby, web_summary=web,
            land_use_zone=land_use_zone,
            official_land_price=official_price,
            build_year=build_year_auto,
            exclusive_area_m2=area_sqm,
            legal_restrictions=legal_restrictions,
            development_plans=development_plans,
            **val, **roi,
            appraisal_opinion=llm_out.get("appraisal_opinion", ""),
            strengths=llm_out.get("strengths", []),
            risk_factors=llm_out.get("risk_factors", []),
            recommendation=llm_out.get("recommendation", ""),
        )
        _print_result(result)
        return _save_result(state, result)

    except Exception as e:
        print(f"[주거용 에이전트] 오류: {e}")
        return _save_result(state, _empty_result("주거용", str(e)))


# ═══════════════════════════════════════════════════════════════
#  2. 상업용 에이전트 (상가)
# ═══════════════════════════════════════════════════════════════

def commercial_agent(state: dict) -> dict:
    try:
        intent, geo, region, region3 = _extract_context(state)
        lat, lng       = _geo_coords(geo)
        location       = getattr(intent, "location_normalized", region)
        area_sqm       = _get_area_sqm(intent)
        asking         = _get_asking_price(intent)
        dong_no        = getattr(intent, "dong_no", "") or ""
        ho_no          = getattr(intent, "ho_no", "") or ""
        floor_inferred = getattr(intent, "floor_inferred", None)
        as_of          = _get_appraisal_date(intent)

        land_use_zone  = _geo_val(geo, "land_use_zone", "") or ""
        official_price = _geo_val(geo, "official_land_price", 0) or 0

        print(f"\n[상업용 에이전트] {location} / 상가 / {area_sqm}㎡")

        # 호수 정보로 전유부 전용면적 조회
        geo_dict   = state.get("geocoding_result") or {}
        sigungu_cd = _geo_val(geo_dict, "sigungu_cd", "")
        bjdong_cd  = _geo_val(geo_dict, "bjdong_cd",  "")
        bun        = _geo_val(geo_dict, "bun",        "")
        ji         = _geo_val(geo_dict, "ji",         "")

        if (dong_no or ho_no) and area_sqm == 0:
            from building_info import fetch_unit_area
            unit_area = fetch_unit_area(sigungu_cd, bjdong_cd, bun, ji, dong_no, ho_no)
            if unit_area and unit_area > 0:
                area_sqm = unit_area
                print(f"  → 전유부 면적 조회 성공: {area_sqm}㎡ ({dong_no or ''}{ho_no})")

        area_sqm, build_year_auto, strct_nm_auto = _auto_fill_area(state, area_sqm, prefer="tot")

        building_name = _get_building_name(state)
        price_data    = fetch_real_transaction_prices(
            "상업용", region, "상가",
            apt_name=building_name, region_3depth=region3,
            floor=floor_inferred or 0,
            area_sqm_exact=area_sqm,
            as_of=as_of,
        )

        precision_label  = price_data.get("precision_filter", "")
        valuation_method = (
            f"비교사례법 ({ho_no} 기준 동일타입 실거래)"
            if precision_label else "비교사례법 + 수익환원법"
        )
        if price_data.get("count", 0) == 0 and price_data.get("avg", 0) == 0:
            region1    = _geo_val(geo, "region_1depth", "") or ""
            land_area  = _geo_val(geo, "land_area", 0.0) or 0.0
            land_price = _geo_val(geo, "official_land_price", 0) or 0

            if area_sqm > 0:
                print(f"[상업용 에이전트] 실거래 없음 → 수익환원법 적용")
                price_data       = _fetch_by_income_approach("상업용", region1, region, area_sqm)
                valuation_method = price_data.get("source", "수익환원법")

            elif land_price > 0 and land_area > 0:
                print(f"[상업용 에이전트] 실거래·면적 없음 → 공시지가 기반 토지가격 추정")
                land_value  = round(land_price * land_area)
                build_value = round(land_value * 0.3)
                total_est   = land_value + build_value
                price_data  = {
                    "avg": total_est, "min": round(total_est * 0.80),
                    "max": round(total_est * 1.20), "count": 0,
                    "per_sqm_avg": 0, "samples": [], "apt_name_matched": "",
                    "used_months": 0, "used_region": region,
                    "land_value": land_value, "build_value": build_value,
                    "source": f"공시지가 기반 추정 (토지 {land_price:,}만원/㎡ × {land_area:,.0f}㎡ + 건물 30%)",
                    "error": "",
                }
                valuation_method = price_data["source"]

            else:
                print(f"[상업용 에이전트] 실거래·면적·공시지가 모두 없음 → 데이터 부족")

        val  = calc_estimated_value(price_data, area_sqm, "상업용")
        roi  = calc_investment_return(val["estimated_value"], "상업용", area_sqm)

        nearby = search_nearby_facilities(lat, lng,
            ["음식점", "카페", "지하철역", "주차장", "은행"], radius=500)

        food_count = (nearby.get("음식점", {}).get("count", 0) +
                      nearby.get("카페", {}).get("count", 0))
        cap_adj = price_data.get("cap_rate_used", roi.get("cap_rate", 5.0))
        if food_count >= 15:
            cap_adj = min(cap_adj + 0.5, 8.0)
        elif food_count <= 3:
            cap_adj = max(cap_adj - 0.5, 2.0)
        roi["cap_rate"] = cap_adj

        web     = search_web_tavily(f"{location} 상가 매매 실거래 시세 공실률")
        llm_out = generate_appraisal_opinion("상업용", location, {**val, **roi}, nearby, web)

        legal_restrictions, development_plans = _parse_web_info(web)

        result = ValuationResult(
            agent_name="상업용",
            valuation_method=valuation_method,
            price_avg=price_data["avg"], price_min=price_data["min"],
            price_max=price_data["max"], price_sample_count=price_data["count"],
            comparable_avg=price_data["avg"], comparable_count=price_data["count"],
            comparables=price_data.get("samples", []),
            used_months=price_data.get("used_months", 0) or 0,
            nearby_facilities=nearby, web_summary=web,
            land_use_zone=land_use_zone,
            official_land_price=official_price,
            build_year=build_year_auto,
            exclusive_area_m2=area_sqm,
            legal_restrictions=legal_restrictions,
            development_plans=development_plans,
            **val, **roi,
            appraisal_opinion=llm_out.get("appraisal_opinion", ""),
            strengths=llm_out.get("strengths", []),
            risk_factors=llm_out.get("risk_factors", []),
            recommendation=llm_out.get("recommendation", ""),
        )
        _print_result(result)
        return _save_result(state, result)

    except Exception as e:
        print(f"[상업용 에이전트] 오류: {e}")
        return _save_result(state, _empty_result("상업용", str(e)))


# ═══════════════════════════════════════════════════════════════
#  3. 업무용 에이전트 (오피스)
# ═══════════════════════════════════════════════════════════════

def office_agent(state: dict) -> dict:
    try:
        intent, geo, region, region3 = _extract_context(state)
        lat, lng       = _geo_coords(geo)
        location       = getattr(intent, "location_normalized", region)
        area_sqm       = _get_area_sqm(intent)
        asking         = _get_asking_price(intent)
        dong_no        = getattr(intent, "dong_no", "") or ""
        ho_no          = getattr(intent, "ho_no", "") or ""
        floor_inferred = getattr(intent, "floor_inferred", None)
        as_of          = _get_appraisal_date(intent)

        land_use_zone  = _geo_val(geo, "land_use_zone", "") or ""
        official_price = _geo_val(geo, "official_land_price", 0) or 0

        print(f"\n[업무용 에이전트] {location} / 사무실 / {area_sqm}㎡")

        geo_dict   = state.get("geocoding_result") or {}
        sigungu_cd = _geo_val(geo_dict, "sigungu_cd", "")
        bjdong_cd  = _geo_val(geo_dict, "bjdong_cd",  "")
        bun        = _geo_val(geo_dict, "bun",        "")
        ji         = _geo_val(geo_dict, "ji",         "")

        if (dong_no or ho_no) and area_sqm == 0:
            from building_info import fetch_unit_area
            unit_area = fetch_unit_area(sigungu_cd, bjdong_cd, bun, ji, dong_no, ho_no)
            if unit_area and unit_area > 0:
                area_sqm = unit_area
                print(f"  → 전유부 면적 조회 성공: {area_sqm}㎡ ({dong_no or ''}{ho_no})")

        area_sqm, build_year_auto, strct_nm_auto = _auto_fill_area(state, area_sqm, prefer="tot")

        building_name = _get_building_name(state)
        price_data    = fetch_real_transaction_prices(
            "업무용", region, "사무실",
            apt_name=building_name, region_3depth=region3,
            floor=floor_inferred or 0,
            area_sqm_exact=area_sqm,
            as_of=as_of,
        )

        precision_label  = price_data.get("precision_filter", "")
        valuation_method = (
            f"비교사례법 ({ho_no} 기준 동일타입 실거래)"
            if precision_label else "비교사례법 + 오피스등급 보정"
        )
        if price_data.get("count", 0) == 0 and price_data.get("avg", 0) == 0:
            region1    = _geo_val(geo, "region_1depth", "") or ""
            land_area  = _geo_val(geo, "land_area", 0.0) or 0.0
            land_price = _geo_val(geo, "official_land_price", 0) or 0

            if area_sqm > 0:
                print(f"[업무용 에이전트] 실거래 없음 → 수익환원법 적용")
                price_data       = _fetch_by_income_approach("업무용", region1, region, area_sqm)
                valuation_method = price_data.get("source", "수익환원법")

            elif land_price > 0 and land_area > 0:
                print(f"[업무용 에이전트] 실거래·면적 없음 → 공시지가 기반 토지가격 추정")
                land_value  = round(land_price * land_area)
                build_value = round(land_value * 0.4)
                total_est   = land_value + build_value
                price_data  = {
                    "avg": total_est, "min": round(total_est * 0.80),
                    "max": round(total_est * 1.20), "count": 0,
                    "per_sqm_avg": 0, "samples": [], "apt_name_matched": "",
                    "used_months": 0, "used_region": region,
                    "land_value": land_value, "build_value": build_value,
                    "source": f"공시지가 기반 추정 (토지 {land_price:,}만원/㎡ × {land_area:,.0f}㎡ + 건물 40%)",
                    "error": "",
                }
                valuation_method = price_data["source"]
            else:
                print(f"[업무용 에이전트] 실거래·면적·공시지가 모두 없음 → 데이터 부족")

        val  = calc_estimated_value(price_data, area_sqm, "업무용")
        roi  = calc_investment_return(val["estimated_value"], "업무용", area_sqm)

        avg = price_data.get("avg", 0)
        if avg >= 50000:
            val["estimated_value"] = round(val["estimated_value"] * 1.08)
        elif avg > 0 and avg < 20000:
            val["estimated_value"] = round(val["estimated_value"] * 0.95)

        nearby = search_nearby_facilities(lat, lng,
            ["지하철역", "주차장", "은행", "카페", "음식점"], radius=800)

        web     = search_web_tavily(f"{location} 오피스 사무실 매매 시세")
        llm_out = generate_appraisal_opinion("업무용", location, {**val, **roi}, nearby, web)

        legal_restrictions, development_plans = _parse_web_info(web)

        result = ValuationResult(
            agent_name="업무용",
            valuation_method=valuation_method,
            price_avg=price_data["avg"], price_min=price_data["min"],
            price_max=price_data["max"], price_sample_count=price_data["count"],
            comparable_avg=price_data["avg"], comparable_count=price_data["count"],
            comparables=price_data.get("samples", []),
            used_months=price_data.get("used_months", 0) or 0,
            nearby_facilities=nearby, web_summary=web,
            land_use_zone=land_use_zone,
            official_land_price=official_price,
            build_year=build_year_auto,
            exclusive_area_m2=area_sqm,
            legal_restrictions=legal_restrictions,
            development_plans=development_plans,
            **val, **roi,
            appraisal_opinion=llm_out.get("appraisal_opinion", ""),
            strengths=llm_out.get("strengths", []),
            risk_factors=llm_out.get("risk_factors", []),
            recommendation=llm_out.get("recommendation", ""),
        )
        _print_result(result)
        return _save_result(state, result)

    except Exception as e:
        print(f"[업무용 에이전트] 오류: {e}")
        return _save_result(state, _empty_result("업무용", str(e)))


# ═══════════════════════════════════════════════════════════════
#  4. 산업용 에이전트 (공장·창고)
# ═══════════════════════════════════════════════════════════════

def industrial_agent(state: dict) -> dict:
    try:
        intent, geo, region, region3 = _extract_context(state)
        lat, lng   = _geo_coords(geo)
        location   = getattr(intent, "location_normalized", region)
        detail     = getattr(intent, "category_detail", "창고")
        area_sqm   = _get_area_sqm(intent)
        asking     = _get_asking_price(intent)
        special    = getattr(intent, "special_conditions", [])
        as_of      = _get_appraisal_date(intent)

        land_use_zone  = _geo_val(geo, "land_use_zone", "") or ""
        official_price = _geo_val(geo, "official_land_price", 0) or 0

        print(f"\n[산업용 에이전트] {location} / {detail} / {area_sqm}㎡")

        area_sqm, build_year_auto, strct_nm_auto = _auto_fill_area(state, area_sqm, prefer="tot")

        geo_dict = state.get("geocoding_result") or {}
        land_area  = _geo_val(geo_dict, "land_area", 0.0) or 0.0
        land_price = _geo_val(geo_dict, "official_land_price", 0) or 0

        build_year = build_year_auto or (datetime.now().year - 10)
        build_area = area_sqm or (land_area * 0.6 if land_area > 0 else 0)

        if land_price > 0 and build_area > 0:
            eff_land_area = land_area if land_area > 0 else build_area / 0.6
            print(f"[산업용 에이전트] 건축원가법 적용 (공시지가 {land_price:,}만원/㎡, 면적 {build_area}㎡)")
            price_data       = calc_cost_approach(
                land_area_sqm       = eff_land_area,
                official_land_price = land_price,
                build_area_sqm      = build_area,
                build_year          = build_year,
                category_detail     = detail,
                strct_nm            = strct_nm_auto,
            )
            valuation_method = price_data.get("source", "건축원가법")

        elif build_area > 0:
            print(f"[산업용 에이전트] 건축원가법 적용 (표준건축비 기준, 공시지가 없음)")
            price_data       = calc_cost_approach(
                land_area_sqm       = 0,
                official_land_price = 0,
                build_area_sqm      = build_area,
                build_year          = build_year,
                category_detail     = detail,
                strct_nm            = strct_nm_auto,
            )
            valuation_method = price_data.get("source", "건축원가법 (건물만)")

        else:
            print(f"[산업용 에이전트] 면적 없음 → 실거래가 비교사례법 폴백")
            building_name = _get_building_name(state)
            price_data    = fetch_real_transaction_prices(
                "산업용", region, detail,
                apt_name=building_name, region_3depth=region3,
                as_of=as_of,
            )
            valuation_method = "비교사례법 (면적 미확인)"

        val  = calc_estimated_value(price_data, area_sqm, "산업용")
        roi  = calc_investment_return(val["estimated_value"], "산업용", area_sqm)

        cond_str     = " ".join(special)
        height_match = re.search(r"층고\s*(\d+)", cond_str)
        if height_match:
            height = int(height_match.group(1))
            if height >= 10:
                val["estimated_value"] = round(val["estimated_value"] * 1.12)
            elif height >= 6:
                val["estimated_value"] = round(val["estimated_value"] * 1.06)

        nearby = search_nearby_facilities(lat, lng,
            ["주차장", "편의점", "음식점"], radius=2000)

        web     = search_web_tavily(f"{location} 공장 창고 매매 시세 물류")
        llm_out = generate_appraisal_opinion("산업용", location, {**val, **roi}, nearby, web)

        legal_restrictions, development_plans = _parse_web_info(web)

        result = ValuationResult(
            agent_name="산업용",
            valuation_method=valuation_method,
            price_avg=price_data["avg"], price_min=price_data["min"],
            price_max=price_data["max"], price_sample_count=price_data["count"],
            comparable_avg=price_data["avg"], comparable_count=price_data["count"],
            comparables=price_data.get("samples", []),
            used_months=price_data.get("used_months", 0) or 0,
            nearby_facilities=nearby, web_summary=web,
            land_use_zone=land_use_zone,
            official_land_price=official_price,
            build_year=build_year_auto,
            exclusive_area_m2=area_sqm,
            legal_restrictions=legal_restrictions,
            development_plans=development_plans,
            **val, **roi,
            appraisal_opinion=llm_out.get("appraisal_opinion", ""),
            strengths=llm_out.get("strengths", []),
            risk_factors=llm_out.get("risk_factors", []),
            recommendation=llm_out.get("recommendation", ""),
        )
        _print_result(result)
        return _save_result(state, result)

    except Exception as e:
        print(f"[산업용 에이전트] 오류: {e}")
        return _save_result(state, _empty_result("산업용", str(e)))


# ═══════════════════════════════════════════════════════════════
#  5. 토지 에이전트
# ═══════════════════════════════════════════════════════════════

LAND_USE_ZONE_TABLE = {
    "제1종전용주거지역":  {"건폐율": 50, "용적률": 100,  "보정계수": 1.0},
    "제2종전용주거지역":  {"건폐율": 50, "용적률": 150,  "보정계수": 1.1},
    "제1종일반주거지역":  {"건폐율": 60, "용적률": 200,  "보정계수": 1.2},
    "제2종일반주거지역":  {"건폐율": 60, "용적률": 250,  "보정계수": 1.3},
    "제3종일반주거지역":  {"건폐율": 50, "용적률": 300,  "보정계수": 1.4},
    "준주거지역":         {"건폐율": 70, "용적률": 500,  "보정계수": 1.6},
    "근린상업지역":       {"건폐율": 70, "용적률": 900,  "보정계수": 2.0},
    "일반상업지역":       {"건폐율": 80, "용적률": 1300, "보정계수": 2.5},
    "중심상업지역":       {"건폐율": 90, "용적률": 1500, "보정계수": 3.0},
    "준공업지역":         {"건폐율": 70, "용적률": 400,  "보정계수": 1.5},
    "일반공업지역":       {"건폐율": 70, "용적률": 350,  "보정계수": 1.3},
    "자연녹지지역":       {"건폐율": 20, "용적률": 100,  "보정계수": 0.7},
    "생산녹지지역":       {"건폐율": 20, "용적률": 100,  "보정계수": 0.6},
    "보전녹지지역":       {"건폐율": 20, "용적률": 80,   "보정계수": 0.5},
}


def land_agent(state: dict) -> dict:
    try:
        intent, geo, region, region3 = _extract_context(state)
        lat, lng   = _geo_coords(geo)
        location   = getattr(intent, "location_normalized", region)
        area_sqm   = _get_area_sqm(intent)
        asking     = _get_asking_price(intent)
        as_of      = _get_appraisal_date(intent)

        if isinstance(geo, dict):
            geo_dict = geo
        else:
            geo_dict = geo.model_dump() if hasattr(geo, "model_dump") else vars(geo)

        land_use_zone  = geo_dict.get("land_use_zone", "")
        official_price = geo_dict.get("official_land_price", 0) or 0
        land_area_geo  = geo_dict.get("land_area", 0.0) or 0.0
        zone_info      = LAND_USE_ZONE_TABLE.get(land_use_zone, {})
        correction     = zone_info.get("보정계수", 1.0)

        if area_sqm <= 0:
            area_sqm, _, _ = _auto_fill_area(state, area_sqm, prefer="plat")
        if area_sqm <= 0 and land_area_geo > 0:
            area_sqm = land_area_geo
            print(f"[토지 에이전트] Vworld 토지면적 사용: {area_sqm}㎡")

        print(f"\n[토지 에이전트] {location} / {land_use_zone or '용도지역 미확인'} / {area_sqm}㎡")

        building_name = _get_building_name(state)
        price_data    = fetch_real_transaction_prices("토지", region, "토지", apt_name=building_name, region_3depth=region3, as_of=as_of)

        val = calc_estimated_value(price_data, area_sqm, "토지")

        if official_price > 0 and area_sqm > 0:
            official_total = round(official_price * area_sqm)
            if official_total > 100000:
                official_total = round(official_total / 10000)
            corrected = round(official_total * correction)
            print(f"[토지 에이전트] 공시지가 {official_price:,}원/㎡ × {area_sqm:,.0f}㎡ "
                  f"× 보정계수 {correction} = {corrected:,}만원")

            if val["estimated_value"] == 0 or corrected > val["estimated_value"]:
                val["estimated_value"] = corrected
            val["value_min"] = round(val["estimated_value"] * 0.88)
            val["value_max"] = round(val["estimated_value"] * 1.12)

        roi  = calc_investment_return(val["estimated_value"], "토지", area_sqm)

        web          = search_web_tavily(f"{location} 토지 개발 호재 지가 상승 GTX 재개발")
        dev_keywords = ["GTX", "재개발", "재건축", "신도시", "도시개발", "산업단지"]
        dev_count    = sum(1 for k in dev_keywords if k in web)
        if dev_count >= 2:
            val["estimated_value"] = round(val["estimated_value"] * 1.10)
            print(f"  → 개발호재 {dev_count}개 감지 → 추정가 +10%")

        nearby  = search_nearby_facilities(lat, lng, ["지하철역", "편의점", "병원"], radius=3000)
        llm_out = generate_appraisal_opinion(
            "토지", location,
            {**val, **roi,
             "용도지역": land_use_zone,
             "건폐율": zone_info.get("건폐율", 0),
             "용적률": zone_info.get("용적률", 0),
             "공시지가(원/㎡)": official_price},
            nearby, web,
        )

        legal_restrictions, development_plans = _parse_web_info(web)

        result = ValuationResult(
            agent_name="토지",
            valuation_method="공시지가×보정계수 + 개발호재 프리미엄",
            price_avg=price_data["avg"], price_min=price_data["min"],
            price_max=price_data["max"], price_sample_count=price_data["count"],
            comparable_avg=price_data["avg"], comparable_count=price_data["count"],
            comparables=price_data.get("samples", []),
            used_months=price_data.get("used_months", 0) or 0,
            nearby_facilities=nearby, web_summary=web,
            land_use_zone=land_use_zone,
            official_land_price=official_price,
            build_year=0,
            exclusive_area_m2=area_sqm,
            legal_restrictions=legal_restrictions,
            development_plans=development_plans,
            **val, **roi,
            appraisal_opinion=llm_out.get("appraisal_opinion", ""),
            strengths=llm_out.get("strengths", []),
            risk_factors=llm_out.get("risk_factors", []),
            recommendation=llm_out.get("recommendation", ""),
        )
        _print_result(result)
        return _save_result(state, result)

    except Exception as e:
        print(f"[토지 에이전트] 오류: {e}")
        return _save_result(state, _empty_result("토지", str(e)))
