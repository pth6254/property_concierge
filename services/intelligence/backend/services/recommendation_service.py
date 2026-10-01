"""
recommendation_service.py — 매물 추천 서비스 (Phase 3-3)

PropertyQuery → 후보 매물 필터링 → 개별 감정평가(선택) → 점수 산출 → TOP N 반환.

흐름:
  recommend_listings(query, limit)
    → search_listings()         후보 매물 풀 조회 (listing_tool)
    → _appraise_listing()       매물별 감정평가 (price_analysis_service, 실패 무시)
    → calculate_listing_score() 4축 점수 산출 (scoring_tool)
    → 점수 내림차순 정렬 → TOP limit

마크다운 리포트:
  format_recommendation_report(results, query) → str
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

_SVC_DIR      = os.path.dirname(os.path.abspath(__file__))   # backend/services/
_BACKEND_DIR  = os.path.dirname(_SVC_DIR)                     # backend/
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)                 # 프로젝트 루트

for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schemas.appraisal_result import AppraisalResult
from schemas.property_listing import PropertyListing
from schemas.property_query import PropertyQuery
from schemas.recommendation_result import RecommendationResult
from tools.listing_tool import search_listings
from tools.scoring_tool import calculate_listing_score

logger = logging.getLogger(__name__)

# 후보 매물 배수: top-N을 뽑기 위해 내부적으로 더 넓게 검색
_CANDIDATE_MULTIPLIER = 3


# ─────────────────────────────────────────
#  내부 헬퍼
# ─────────────────────────────────────────

def _appraise_listing(
    listing: PropertyListing,
    base_query: PropertyQuery,
) -> Optional[AppraisalResult]:
    """
    매물 1건에 대해 감정평가를 시도한다.
    API 미설정·네트워크 오류 등 어떤 이유로든 실패하면 None을 반환해
    호출자가 appraisal=None으로 점수 계산을 이어갈 수 있게 한다.
    """
    try:
        from services.price_analysis_service import analyze_price  # 지연 임포트 (순환 방지)

        listing_query = PropertyQuery(
            intent        = base_query.intent,
            property_type = listing.property_type,
            region        = listing.region or base_query.region,
            complex_name  = listing.complex_name or base_query.complex_name,
            area_m2       = listing.area_m2 or base_query.area_m2,
            asking_price  = listing.asking_price,
            purpose       = base_query.purpose,
        )
        return analyze_price(listing_query, as_of=base_query.appraisal_date)
    except Exception as exc:
        logger.debug("감정평가 실패 (%s): %s", listing.listing_id, exc)
        return None


def _build_result(
    listing: PropertyListing,
    query: PropertyQuery,
    appraisal: Optional[AppraisalResult],
) -> RecommendationResult:
    score = calculate_listing_score(listing, query, appraisal)
    return RecommendationResult(
        listing              = listing,
        appraisal            = appraisal,
        total_score          = score["total_score"],
        price_score          = score["price_score"],
        location_score       = score["location_score"],
        investment_score     = score["investment_score"],
        risk_score           = score["risk_score"],
        recommendation_label = score["recommendation_label"],
        reasons              = score["reasons"],
        risks                = score["risks"],
    )


# ─────────────────────────────────────────
#  공개 인터페이스
# ─────────────────────────────────────────

def recommend_listings(
    query: PropertyQuery,
    limit: int = 5,
    run_appraisal: bool = True,
) -> list[RecommendationResult]:
    """
    PropertyQuery 조건에 맞는 매물을 점수 내림차순으로 최대 limit건 반환.

    Args:
        query:         필터·예산·면적 조건이 담긴 쿼리.
        limit:         반환할 최대 건수 (기본 5).
        run_appraisal: True면 매물별 감정평가 시도 (실패해도 추천은 계속 진행).
                       False면 appraisal=None으로 점수만 계산 (빠른 모드).

    Returns:
        RecommendationResult 리스트, total_score 내림차순.
    """
    candidate_limit = limit * _CANDIDATE_MULTIPLIER
    candidates = search_listings(query, limit=candidate_limit)

    if not candidates:
        return []

    results: list[RecommendationResult] = []
    for listing in candidates:
        appraisal = _appraise_listing(listing, query) if run_appraisal else None
        results.append(_build_result(listing, query, appraisal))

    results.sort(key=lambda r: r.total_score, reverse=True)
    return results[:limit]


# ─────────────────────────────────────────
#  마크다운 리포트
# ─────────────────────────────────────────

def _fmt_price(won: Optional[int]) -> str:
    if won is None:
        return "—"
    return f"{won:,}원"


def _score_bar(score: float, width: int = 10) -> str:
    """점수 0-10을 막대 그래프 문자열로 변환"""
    filled = round(score / 10 * width)
    return "█" * filled + "░" * (width - filled)


def format_recommendation_report(
    results: list[RecommendationResult],
    query: PropertyQuery,
) -> str:
    """
    추천 결과 리스트를 마크다운 리포트 문자열로 변환.

    Args:
        results: recommend_listings()의 반환값.
        query:   원본 쿼리 (헤더에 조건 표시용).

    Returns:
        마크다운 str.
    """
    lines: list[str] = []

    # ── 헤더 ──────────────────────────────────────────────────────────────
    lines.append("# 매물 추천 리포트")
    lines.append("")

    cond_parts = []
    if query.region:
        cond_parts.append(f"지역: **{query.region}**")
    if query.property_type:
        cond_parts.append(f"유형: **{query.property_type}**")
    if query.area_m2:
        cond_parts.append(f"면적: **{query.area_m2:.0f}㎡**")
    if query.budget_max:
        cond_parts.append(f"최대 예산: **{_fmt_price(query.budget_max)}**")

    if cond_parts:
        lines.append("## 검색 조건")
        lines.append("")
        for c in cond_parts:
            lines.append(f"- {c}")
        lines.append("")

    # ── 요약 테이블 ────────────────────────────────────────────────────────
    if not results:
        lines.append("> 조건에 맞는 추천 매물이 없습니다.")
        return "\n".join(lines)

    lines.append(f"## 추천 결과 (TOP {len(results)})")
    lines.append("")
    lines.append("| 순위 | 단지명 | 호가 | 종합 점수 | 추천 |")
    lines.append("|------|--------|------|-----------|------|")
    for rank, r in enumerate(results, 1):
        name  = r.listing.complex_name or r.listing.address[:12]
        price = _fmt_price(r.listing.asking_price)
        bar   = _score_bar(r.total_score, width=8)
        lines.append(
            f"| {rank} | {name} | {price} "
            f"| {bar} {r.total_score:.1f} | {r.recommendation_label} |"
        )
    lines.append("")

    # ── 개별 상세 ──────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("")
    for rank, r in enumerate(results, 1):
        l = r.listing
        name = l.complex_name or l.address

        lines.append(f"### {rank}위 {name}")
        lines.append("")

        # 기본 정보
        info_parts = []
        if l.address:
            info_parts.append(f"주소: {l.address}")
        if l.area_m2:
            info_parts.append(f"면적: {l.area_m2:.2f}㎡")
        if l.floor:
            info_parts.append(f"층수: {l.floor}층")
        if l.built_year:
            info_parts.append(f"준공: {l.built_year}년")
        if l.station_distance_m:
            info_parts.append(f"지하철: {l.station_distance_m}m")
        for part in info_parts:
            lines.append(f"- {part}")
        lines.append("")

        # 가격 정보
        lines.append(f"**호가** {_fmt_price(l.asking_price)}")
        if l.deposit_price:
            ratio = l.deposit_price / l.asking_price * 100
            lines.append(f"**전세가** {_fmt_price(l.deposit_price)} (전세가율 {ratio:.0f}%)")
        lines.append("")

        # 감정평가
        if r.appraisal and r.appraisal.estimated_price:
            a = r.appraisal
            lines.append(
                f"**감정평가** 추정가 {_fmt_price(a.estimated_price)}"
                f"  |  신뢰도: {a.confidence:.0%}"
            )
            lines.append("")

        # 세부 점수
        lines.append("**세부 점수**")
        lines.append("")
        lines.append("| 항목 | 점수 | 그래프 |")
        lines.append("|------|------|--------|")
        score_rows = [
            ("가격 적정성", r.price_score),
            ("입지",        r.location_score),
            ("투자 가치",   r.investment_score),
            ("위험도",      r.risk_score),
        ]
        for label, sc in score_rows:
            lines.append(f"| {label} | {sc:.1f} | {_score_bar(sc, 8)} |")
        lines.append(f"| **종합** | **{r.total_score:.1f}** | {_score_bar(r.total_score, 8)} |")
        lines.append("")

        # 추천 근거
        if r.reasons:
            lines.append("**추천 근거**")
            lines.append("")
            for reason in r.reasons:
                lines.append(f"- ✅ {reason}")
            lines.append("")

        # 위험 요인
        if r.risks:
            lines.append("**주의사항**")
            lines.append("")
            for risk in r.risks:
                lines.append(f"- ⚠️ {risk}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)
