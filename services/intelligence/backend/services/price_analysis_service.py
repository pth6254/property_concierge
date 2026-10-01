"""
price_analysis_service.py — 가격 분석 서비스 v1.1

기존 price_engine 함수들을 재사용해 PropertyQuery → AppraisalResult 흐름을 제공.
LangGraph 파이프라인(NLP→지오코딩→에이전트)을 거치지 않는 직접 호출 경로.

단위 주의:
  price_engine 내부 — 만원 (int)
  schemas (PropertyQuery / AppraisalResult) — 원 (int)
  변환은 이 파일의 _to_won() / _to_manwon() 에서만 수행한다.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime as _dt

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schemas.appraisal_result import (
    AppraisalResult,
    ComparableTransaction,
    ValuationMethodResult,
)
from schemas.property_query import PropertyQuery
from price_engine import (
    calc_estimated_value,
    fetch_real_transaction_prices,
)


# ─────────────────────────────────────────
#  단위 변환
# ─────────────────────────────────────────

def _to_won(manwon: int | None) -> int | None:
    if manwon is None or manwon == 0:
        return None
    return manwon * 10_000


def _to_manwon(won: int | None) -> int | None:
    if won is None or won == 0:
        return None
    return won // 10_000


# ─────────────────────────────────────────
#  지역요인 보정치 (match_level 기반 근사)
# ─────────────────────────────────────────

_REGION_FACTOR: dict[str, float] = {
    "same_complex": 1.00,
    "same_dong":    0.98,
    "same_gu":      0.95,
    "nearby":       0.92,
    "fallback":     1.00,
}


# ─────────────────────────────────────────
#  ComparableTransaction 변환
# ─────────────────────────────────────────

def _to_comparables(
    price_data: dict,
    apt_name_matched: str,
) -> list[ComparableTransaction]:
    samples = price_data.get("samples", [])
    if not samples:
        return []

    result = []
    for s in samples:
        # match_level 결정
        if apt_name_matched and s.get("apt_name") == apt_name_matched:
            match_level = "same_complex"
        elif s.get("dong"):
            match_level = "same_dong"
        else:
            match_level = "same_gu"

        # 거래일 조합 (YYYY-MM)
        deal_date = None
        if s.get("deal_year") and s.get("deal_month"):
            deal_date = f"{s['deal_year']}-{int(s['deal_month']):02d}"

        # 요인 보정치
        region_factor    = _REGION_FACTOR.get(match_level, 1.0)
        individual_factor = 1.0   # 개별요인: 기본 1.0 (데이터 한계로 현재 미분화)
        circumstance_adj  = 1.0   # 사정보정: 공개 실거래 → 정상거래로 간주

        # 비준단가 = 원단가 × 사정보정 × 시점수정 × 지역요인 × 개별요인
        raw_per_m2 = s.get("per_sqm", 0)
        time_factor = s.get("time_adj_factor", 1.0)
        adj_price_per_m2 = None
        if raw_per_m2 and raw_per_m2 > 0:
            adj = raw_per_m2 * circumstance_adj * time_factor * region_factor * individual_factor
            adj_price_per_m2 = round(adj * 10_000)  # 만원/m² → 원/m²

        result.append(ComparableTransaction(
            complex_name     = s.get("apt_name") or None,
            address          = s.get("dong") or None,
            area_m2          = s.get("area_sqm") or None,
            floor            = str(s["floor"]) if s.get("floor") else None,
            year_built       = str(s["year_built"]) if s.get("year_built") else None,
            deal_price       = _to_won(s.get("price")),
            original_price   = _to_won(s.get("original_price")),
            deal_date        = deal_date,
            price_per_m2     = round(raw_per_m2 * 10_000) if raw_per_m2 else None,
            source           = "국토부 실거래가",
            match_level      = match_level,
            time_adj_months  = s.get("time_adj_months", 0),
            time_adj_factor  = s.get("time_adj_factor", 1.0),
            circumstance_adj = circumstance_adj,
            region_factor    = region_factor,
            individual_factor = individual_factor,
            adjusted_price_per_m2 = adj_price_per_m2,
        ))
    return result


# ─────────────────────────────────────────
#  신뢰도 계산
# ─────────────────────────────────────────

def _calc_confidence(price_data: dict) -> float:
    """
    신뢰도 산출 — confidence.compute_confidence 위임.

    다요인 모델: 매칭 수준(동일단지~폴백) 기반점 + 표본 수·산포(CV)·
    신선도·시점수정 방식 가감. 백테스트 보정테이블
    (data/avm_calibration.json)이 있으면 버킷별 실측 적중률과 블렌딩.
    폴백 출처(공시가격·수익환원법·원가법)는 최대 0.40으로 제한.
    """
    from confidence import compute_confidence

    if price_data.get("error") or price_data.get("avg", 0) == 0:
        return 0.10

    r = compute_confidence(
        count       = price_data.get("count", 0),
        samples     = price_data.get("samples") or None,
        used_months = price_data.get("used_months", 0) or 0,
        source      = price_data.get("source", "") or "",
    )
    return r["score"]


# ─────────────────────────────────────────
#  경고 메시지 수집
# ─────────────────────────────────────────

def _collect_warnings(
    price_data: dict,
    area_m2: float | None,
    complex_name: str = "",
    apt_name_matched: str = "",
) -> list[str]:
    p0, p1, p2 = [], [], []

    count  = price_data.get("count", 0)
    source = price_data.get("source", "")
    months = price_data.get("used_months", 0) or 0

    if price_data.get("error"):
        p0.append("실거래가 조회 오류 — 추정가 신뢰 불가")
    elif count == 0:
        p0.append("실거래 데이터 없음 — 추정가 신뢰도 낮음")

    if "공시가격" in source:
        p1.append("공시가격 역산 사용 (실거래 없음)")
    elif "수익환원법" in source:
        p1.append("수익환원법 사용 (실거래 없음)")
    elif "원가법" in source:
        p1.append("건축원가법 사용 (실거래 없음)")

    if 0 < count < 5:
        p1.append(f"실거래 {count}건 — 표본 부족으로 추정가 편차 클 수 있음")

    if complex_name and not apt_name_matched:
        p1.append(f"'{complex_name}' 단지 미매칭 — 동/구 단위 평균가 사용")

    if months > 12:
        p2.append(f"최근 {months}개월 데이터 사용 — 시세 변동 미반영 가능성")
    elif months > 3:
        p2.append(f"최근 {months}개월 데이터 사용 (3개월 이내 실거래 없음)")

    if not area_m2:
        p2.append("면적 미입력 — 추정가는 지역 평균 기준")

    return p0 + p1 + p2


def _collect_sources(price_data: dict) -> list[str]:
    source = price_data.get("source", "")
    if source:
        return [source]
    if price_data.get("count", 0) > 0:
        return ["국토부 실거래가"]
    return []


# ─────────────────────────────────────────
#  기준시점 문자열 변환
# ─────────────────────────────────────────

def _format_appraisal_date(as_of: str) -> str:
    if as_of and len(as_of) >= 8:
        try:
            d = _dt.strptime(as_of[:8], "%Y%m%d")
            return d.strftime("%Y년 %m월 %d일")
        except ValueError:
            pass
    return _dt.now().strftime("%Y년 %m월 %d일") + " (현재)"


# ─────────────────────────────────────────
#  공개 인터페이스
# ─────────────────────────────────────────

def analyze_price(query: PropertyQuery, as_of: str = "") -> AppraisalResult:
    """
    PropertyQuery를 받아 가격 분석 결과(AppraisalResult)를 반환.

    LangGraph 파이프라인을 거치지 않는 직접 호출 경로.
    query.region과 query.property_type이 있어야 실거래가를 조회할 수 있다.
    """
    region        = query.region or ""
    property_type = query.property_type or "주거용"
    area_m2       = query.area_m2
    complex_name  = query.complex_name or ""
    as_of_str     = as_of or query.appraisal_date or ""

    asking_manwon = _to_manwon(query.asking_price)

    if not region:
        return AppraisalResult(
            confidence    = 0.0,
            appraisal_date = _format_appraisal_date(as_of_str),
            warnings      = ["region(지역) 정보 없음 — 실거래가 조회 불가"],
        )

    # ── 1. 실거래가 조회 ─────────────────────────────────────────────────
    price_data = fetch_real_transaction_prices(
        category        = property_type,
        region_2depth   = region,
        category_detail = property_type,
        apt_name        = complex_name,
        as_of           = as_of_str,
    )

    apt_name_matched = price_data.get("apt_name_matched", "")

    # ── 2. 추정가 계산 ──────────────────────────────────────────────────
    val = calc_estimated_value(price_data, area_m2 or 0.0, property_type)

    # ── 3. 시산가액 조정 (단일 방법) ───────────────────────────────────
    sources    = _collect_sources(price_data)
    method_nm  = sources[0] if sources else "비교사례법"
    comp_count = price_data.get("count", 0)
    breakdown  = []
    if val.get("estimated_value"):
        breakdown.append(ValuationMethodResult(
            method          = method_nm,
            estimated_value = _to_won(val["estimated_value"]),
            weight          = 1.0,
            note            = f"실거래 {comp_count}건 기반" if comp_count > 0 else "폴백 데이터 기반",
        ))

    # ── 4. 조립 및 반환 ──────────────────────────────────────────────────
    return AppraisalResult(
        estimated_price    = _to_won(val["estimated_value"]),
        low_price          = _to_won(val["value_min"]),
        high_price         = _to_won(val["value_max"]),
        asking_price       = query.asking_price,
        confidence         = _calc_confidence(price_data),
        appraisal_date     = _format_appraisal_date(as_of_str),
        appraisal_purpose  = getattr(query, "appraisal_purpose", None),
        exclusive_area_m2  = area_m2,
        valuation_breakdown = breakdown,
        comparables        = _to_comparables(price_data, apt_name_matched),
        warnings           = _collect_warnings(price_data, area_m2, complex_name, apt_name_matched),
        data_source        = sources,
        raw                = {**val, "price_data_count": price_data.get("count", 0)},
    )
