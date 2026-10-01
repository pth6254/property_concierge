"""
scoring_tool.py — 매물 종합 점수 산출 도구

calculate_listing_score(listing, query, appraisal) 를 호출하면
price / location / investment / risk 4개 축 점수(0-10)와
total_score, recommendation_label, reasons, risks 를 담은 dict 를 반환한다.

가중치는 property_type에 따라 자동 선택:
  주거용:  price*0.35 + location*0.30 + investment*0.20 + (10-risk)*0.15
  상업용:  price*0.25 + location*0.30 + investment*0.35 + (10-risk)*0.10
  업무용:  price*0.25 + location*0.30 + investment*0.35 + (10-risk)*0.10
  산업용:  price*0.20 + location*0.20 + investment*0.45 + (10-risk)*0.15
  토지:    price*0.30 + location*0.40 + investment*0.15 + (10-risk)*0.15
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Optional

_TOOLS_DIR    = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_TOOLS_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)

for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schemas.appraisal_result import AppraisalResult
from schemas.property_listing import PropertyListing
from schemas.property_query import PropertyQuery

_CURRENT_YEAR = datetime.now().year

# (price, location, investment, risk) 가중치 합계 = 1.0
_WEIGHTS: dict[str, tuple[float, float, float, float]] = {
    "주거용": (0.35, 0.30, 0.20, 0.15),
    "상업용": (0.25, 0.30, 0.35, 0.10),
    "업무용": (0.25, 0.30, 0.35, 0.10),
    "산업용": (0.20, 0.20, 0.45, 0.15),
    "토지":   (0.30, 0.40, 0.15, 0.15),
}
_DEFAULT_WEIGHTS: tuple[float, float, float, float] = (0.35, 0.30, 0.20, 0.15)

# ─────────────────────────────────────────
#  price_score  (0-10)
# ─────────────────────────────────────────

def _score_price(
    listing: PropertyListing,
    query: PropertyQuery,
    appraisal: Optional[AppraisalResult],
) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    risks:   list[str] = []

    score = 5.0  # 고/저평가 판단 미사용 — 예산 적합도 기준으로만 조정

    # 예산 범위 적합도 보정
    price = listing.asking_price
    if query.budget_max is not None and price > query.budget_max:
        over_pct = (price - query.budget_max) / query.budget_max * 100
        score -= 1.5
        risks.append(f"호가가 최대 예산 초과 ({over_pct:.0f}%)")
    elif query.budget_min is not None and query.budget_max is not None:
        if query.budget_min <= price <= query.budget_max:
            score += 0.5
            reasons.append("호가가 희망 예산 범위 내")
    elif query.budget_max is not None and price <= query.budget_max:
        score += 0.3
        reasons.append("호가가 최대 예산 이내")

    return max(0.0, min(10.0, score)), reasons, risks


# ─────────────────────────────────────────
#  location_score  (0-10)
# ─────────────────────────────────────────

def _score_location(
    listing: PropertyListing,
    query: PropertyQuery,
) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    risks:   list[str] = []

    is_residential = listing.property_type == "주거용"

    # 역세권 (0-5점) — 모든 유형 공통
    sd = listing.station_distance_m
    if sd is None:
        station_pts = 0.5
    elif sd <= 200:
        station_pts = 5.0
        reasons.append(f"초역세권 (지하철 {sd}m)")
    elif sd <= 400:
        station_pts = 4.0
        reasons.append(f"역세권 (지하철 {sd}m)")
    elif sd <= 600:
        station_pts = 3.0
        reasons.append(f"역 도보권 (지하철 {sd}m)")
    elif sd <= 800:
        station_pts = 2.0
    elif sd <= 1200:
        station_pts = 1.0
        risks.append(f"지하철 원거리 ({sd}m)")
    else:
        station_pts = 0.5
        risks.append(f"지하철 매우 원거리 ({sd}m)")

    # 학교 접근성 (0-2점) — 주거용만 반영, 비주거용은 0
    if is_residential:
        sc = listing.school_distance_m
        if sc is None:
            school_pts = 0.5
        elif sc <= 300:
            school_pts = 2.0
            reasons.append(f"학교 인접 ({sc}m)")
        elif sc <= 600:
            school_pts = 1.5
        elif sc <= 1000:
            school_pts = 1.0
        else:
            school_pts = 0.5
            risks.append(f"학교 원거리 ({sc}m)")
    else:
        school_pts = 0.0

    # 건축연도 신축성 (0-2점)
    by = listing.built_year
    if by is None:
        year_pts = 0.3
    elif by >= 2020:
        year_pts = 2.0
        reasons.append(f"{by}년 신축")
    elif by >= 2015:
        year_pts = 1.5
        reasons.append(f"{by}년 준공 (비교적 신축)")
    elif by >= 2010:
        year_pts = 1.2
    elif by >= 2005:
        year_pts = 1.0
    elif by >= 2000:
        year_pts = 0.7
    elif by >= 1990:
        year_pts = 0.5
        risks.append(f"{by}년 준공 구축")
    else:
        year_pts = 0.3
        risks.append(f"{by}년 준공 노후 건물")

    # 층수 (0-1점)
    fl = listing.floor
    if fl is None:
        floor_pts = 0.5
    elif fl >= 10:
        floor_pts = 1.0
        reasons.append(f"{fl}층 (조망·일조 양호)")
    elif fl >= 5:
        floor_pts = 0.7
    else:
        floor_pts = 0.5

    score = station_pts + school_pts + year_pts + floor_pts
    return max(0.0, min(10.0, score)), reasons, risks


# ─────────────────────────────────────────
#  investment_score  (0-10)
# ─────────────────────────────────────────

def _score_investment(
    listing: PropertyListing,
    appraisal: Optional[AppraisalResult],
) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    risks:   list[str] = []
    ap = listing.asking_price

    # 주거용: 전세가율 기반
    if listing.property_type == "주거용":
        jp = listing.deposit_price
        if jp and ap and ap > 0:
            ratio = jp / ap
            if ratio >= 0.75:
                base = 8.5
                reasons.append(f"전세가율 {ratio:.0%} — 갭투자 메리트 높음")
            elif ratio >= 0.65:
                base = 7.5
                reasons.append(f"전세가율 {ratio:.0%} — 투자 양호")
            elif ratio >= 0.55:
                base = 6.0
            elif ratio >= 0.45:
                base = 5.0
            elif ratio >= 0.35:
                base = 4.0
                risks.append(f"전세가율 {ratio:.0%} — 갭 부담")
            else:
                base = 2.5
                risks.append(f"전세가율 {ratio:.0%} — 갭 매우 큼")
        else:
            base = 5.0

    # 상업용/업무용/산업용: 연 임대수익률 기반
    elif listing.property_type in ("상업용", "업무용", "산업용"):
        rent = listing.monthly_rent_income
        if rent and ap and ap > 0:
            annual_yield = rent * 12 / ap
            if annual_yield >= 0.06:
                base = 8.5
                reasons.append(f"연 임대수익률 {annual_yield:.1%} — 수익성 우수")
            elif annual_yield >= 0.05:
                base = 7.0
                reasons.append(f"연 임대수익률 {annual_yield:.1%} — 수익성 양호")
            elif annual_yield >= 0.04:
                base = 5.5
                reasons.append(f"연 임대수익률 {annual_yield:.1%}")
            elif annual_yield >= 0.03:
                base = 4.0
                risks.append(f"연 임대수익률 {annual_yield:.1%} — 수익성 낮음")
            else:
                base = 2.5
                risks.append(f"연 임대수익률 {annual_yield:.1%} — 수익성 매우 낮음")
        else:
            base = 5.0
            risks.append("임대수입 정보 없음 — 수익성 산정 불가")

    # 토지 / 기타
    else:
        base = 5.0

    score = base
    return max(0.0, min(10.0, score)), reasons, risks


# ─────────────────────────────────────────
#  risk_score  (0-10, 높을수록 위험)
# ─────────────────────────────────────────

def _score_risk(
    listing: PropertyListing,
    appraisal: Optional[AppraisalResult],
) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    risks:   list[str] = []

    # 건물 노후화 위험
    by = listing.built_year
    if by is None:
        age_risk = 2.0
    else:
        age = _CURRENT_YEAR - by
        if age <= 3:
            age_risk = 0.0
            reasons.append(f"준공 {age}년 이내 신축 — 구조 리스크 낮음")
        elif age <= 8:
            age_risk = 0.5
        elif age <= 15:
            age_risk = 1.0
        elif age <= 25:
            age_risk = 2.0
        elif age <= 35:
            age_risk = 3.5
            risks.append(f"준공 {age}년 노후 건물 — 수선·하자 위험")
        else:
            age_risk = 5.0
            risks.append(f"준공 {age}년 초노후 건물 — 재건축 여부 확인 필요")

    # 감정평가 신뢰도 위험
    if appraisal is None:
        conf_risk = 1.5
        risks.append("감정평가 데이터 미제공 — 가격 신뢰도 불명")
    else:
        conf = appraisal.confidence
        if conf < 0.3:
            conf_risk = 3.0
            risks.append(f"감정평가 신뢰도 낮음 ({conf:.0%}) — 비교 사례 부족")
        elif conf < 0.5:
            conf_risk = 1.5
            risks.append(f"감정평가 신뢰도 보통 ({conf:.0%})")
        elif conf < 0.7:
            conf_risk = 0.5
        else:
            conf_risk = 0.0

    # 경고 메시지 페널티
    warning_count = len(appraisal.warnings) if appraisal else 0
    warn_risk = min(warning_count * 0.5, 2.0)
    if warning_count >= 2:
        risks.append(f"감정평가 주의사항 {warning_count}건")

    score = age_risk + conf_risk + warn_risk
    return max(0.0, min(10.0, score)), reasons, risks


# ─────────────────────────────────────────
#  합산 및 레이블
# ─────────────────────────────────────────

def _calc_total_score(
    price: float,
    location: float,
    investment: float,
    risk: float,
    property_type: Optional[str] = None,
) -> float:
    wp, wl, wi, wr = _WEIGHTS.get(property_type, _DEFAULT_WEIGHTS)
    raw = price * wp + location * wl + investment * wi + (10.0 - risk) * wr
    return round(max(0.0, min(10.0, raw)), 2)


def _recommendation_label(total: float) -> str:
    if total >= 8.0:
        return "적극 추천"
    if total >= 6.5:
        return "추천"
    if total >= 5.0:
        return "검토 필요"
    return "비추천"


# ─────────────────────────────────────────
#  공개 인터페이스
# ─────────────────────────────────────────

def calculate_listing_score(
    listing: PropertyListing,
    query: PropertyQuery,
    appraisal: Optional[AppraisalResult] = None,
) -> dict:
    """
    매물 종합 점수 산출.

    반환 dict:
      total_score         float 0-10
      price_score         float 0-10
      location_score      float 0-10
      investment_score    float 0-10
      risk_score          float 0-10  (높을수록 위험)
      recommendation_label str
      reasons             list[str]
      risks               list[str]
    """
    price_score,      p_reasons, p_risks = _score_price(listing, query, appraisal)
    location_score,   l_reasons, l_risks = _score_location(listing, query)
    investment_score, i_reasons, i_risks = _score_investment(listing, appraisal)
    risk_score,       r_reasons, r_risks = _score_risk(listing, appraisal)

    total_score = _calc_total_score(
        price_score, location_score, investment_score, risk_score,
        property_type=listing.property_type,
    )

    reasons = p_reasons + l_reasons + i_reasons + r_reasons
    risks   = p_risks   + l_risks   + i_risks   + r_risks

    return {
        "total_score":          round(total_score, 2),
        "price_score":          round(price_score, 2),
        "location_score":       round(location_score, 2),
        "investment_score":     round(investment_score, 2),
        "risk_score":           round(risk_score, 2),
        "recommendation_label": _recommendation_label(total_score),
        "reasons":              reasons,
        "risks":                risks,
    }
