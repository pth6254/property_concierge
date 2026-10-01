"""
comparison_service.py — 매물 비교·최종 판단 서비스 (Phase 5)

공개 함수:
  compare_listings(listings, recommendation_results, simulation_results) → ComparisonResult
  generate_decision_report(result)                                       → str
"""

from __future__ import annotations

import os
import sys
from typing import Optional

_SVC_DIR      = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_SVC_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schemas.comparison import ComparisonInput, ComparisonResult, PropertyComparisonRow
from schemas.property_listing import PropertyListing
from schemas.recommendation_result import RecommendationResult
from schemas.simulation import SimulationResult


# ─────────────────────────────────────────
#  포맷 헬퍼
# ─────────────────────────────────────────

def _fmt_won(won: int | None) -> str:
    if won is None:
        return "—"
    sign = "-" if won < 0 else ""
    return f"{sign}{abs(won):,}원"


def _fmt_pct(pct: float | None, decimals: int = 2) -> str:
    if pct is None:
        return "—"
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.{decimals}f}%"


# ─────────────────────────────────────────
#  점수 계산
# ─────────────────────────────────────────

def _score_listing(
    listing: PropertyListing,
    recommendation: RecommendationResult | None,
    simulation: SimulationResult | None,
    all_prices: list[int],
) -> tuple[float, float, float, float, float, list[str], list[str]]:
    """
    매물 1건 종합·세부 점수(0~10) 및 강점/주의사항 산출.

    반환: (total, price_score, location_score, investment_score, risk_score, highlights, warnings)
    - recommendation 있으면 세부 점수를 그대로 사용
    - 없으면 가격 상대순위로 0~10 간이 계산 (세부 점수는 0.0)
    """
    highlights: list[str] = []
    warnings: list[str]   = []
    price_score = location_score = investment_score = risk_score = 0.0

    if recommendation is not None:
        score            = float(recommendation.total_score)
        price_score      = float(recommendation.price_score)
        location_score   = float(recommendation.location_score)
        investment_score = float(recommendation.investment_score)
        risk_score       = float(recommendation.risk_score)
        highlights.extend(recommendation.reasons[:3])
        warnings.extend(recommendation.risks[:2])
    else:
        sorted_prices = sorted(all_prices)
        idx      = sorted_prices.index(listing.asking_price) if listing.asking_price in sorted_prices else 0
        rank_pct = idx / max(len(all_prices) - 1, 1)
        score    = round((1.0 - rank_pct) * 10.0, 2)  # 0~10 전 구간 사용

    # 시뮬레이션 결과 반영
    if simulation is not None:
        aroi = simulation.scenario_base.annual_equity_roi
        if aroi is not None:
            if aroi >= 10.0:
                score = min(10.0, score + 1.0)
                highlights.append(f"연 수익률 {aroi:.1f}% (우수)")
            elif aroi >= 5.0:
                highlights.append(f"연 수익률 {aroi:.1f}% (양호)")
            elif aroi < 0.0:
                score = max(0.0, score - 1.0)
                warnings.append(f"연 수익률 {aroi:.1f}% (주의)")

    return round(score, 2), price_score, location_score, investment_score, risk_score, highlights, warnings


# ─────────────────────────────────────────
#  공개 인터페이스
# ─────────────────────────────────────────

def compare_listings(
    listings: list[PropertyListing],
    recommendation_results: list[RecommendationResult] | None = None,
    simulation_results: list[SimulationResult] | None = None,
) -> ComparisonResult:
    """
    매물 목록 비교 분석 → ComparisonResult.

    recommendation_results, simulation_results의 순서는 listings와 동일해야 한다.
    길이가 짧으면 None으로 패딩된다.
    """
    if not listings:
        raise ValueError("비교할 매물이 없습니다.")
    if len(listings) < 2:
        raise ValueError("비교는 2개 이상의 매물이 필요합니다.")

    n    = len(listings)
    recs = list(recommendation_results or [None] * n)
    sims = list(simulation_results     or [None] * n)

    # 길이 부족 시 None 패딩
    recs = (recs + [None] * n)[:n]
    sims = (sims + [None] * n)[:n]

    all_prices = [l.asking_price for l in listings]

    rows: list[PropertyComparisonRow] = []
    for i, (listing, rec, sim) in enumerate(zip(listings, recs, sims)):
        score, p_score, l_score, i_score, r_score, highlights, warnings = (
            _score_listing(listing, rec, sim, all_prices)
        )

        price_per_m2 = None
        if listing.area_m2 and listing.area_m2 > 0:
            price_per_m2 = int(listing.asking_price / listing.area_m2)

        jeonse_ratio = None
        if listing.deposit_price and listing.asking_price > 0:
            jeonse_ratio = round(listing.deposit_price / listing.asking_price * 100, 1)

        monthly_net       = None
        annual_equity_roi = None
        if sim is not None:
            monthly_net       = sim.cash_flow.monthly_net
            annual_equity_roi = sim.scenario_base.annual_equity_roi

        rows.append(PropertyComparisonRow(
            rank              = i + 1,
            listing           = listing,
            recommendation    = rec,
            simulation        = sim,
            total_score       = score,
            price_score       = p_score,
            location_score    = l_score,
            investment_score  = i_score,
            risk_score        = r_score,
            price_per_m2      = price_per_m2,
            jeonse_ratio      = jeonse_ratio,
            monthly_net       = monthly_net,
            annual_equity_roi = annual_equity_roi,
            highlights        = highlights,
            warnings          = warnings,
        ))

    # 점수 내림차순 재정렬
    rows.sort(key=lambda r: r.total_score, reverse=True)
    for i, row in enumerate(rows):
        row.rank = i + 1

    rows[0].is_winner = True

    result = ComparisonResult(rows=rows, winner_idx=0)
    result.decision_report = generate_decision_report(result)
    return result


def generate_decision_report(result: ComparisonResult) -> str:
    """ComparisonResult → 마크다운 결정 리포트"""
    lines: list[str] = []
    rows = result.rows
    n    = len(rows)

    lines.append("# 매물 비교 최종 판단 리포트")
    lines.append("")
    lines.append("> ⚠️ 이 리포트는 간이 분석 결과입니다. 실제 투자 판단 전 전문가 상담을 받으시기 바랍니다.")
    lines.append("")

    # 요약 표
    lines.append(f"## 비교 대상 {n}건 요약")
    lines.append("")
    lines.append("| 순위 | 매물 | 호가 | 점수 | 전세가율 | 월 순현금흐름 | 연 수익률 |")
    lines.append("|------|------|------|------|---------|-------------|---------|")
    for row in rows:
        l           = row.listing
        name        = (l.complex_name or l.address[:15]).strip()
        winner_mark = " 🏆" if row.is_winner else ""
        jeonse_str  = f"{row.jeonse_ratio:.0f}%" if row.jeonse_ratio is not None else "—"
        net_str     = _fmt_won(row.monthly_net)   if row.monthly_net  is not None else "—"
        roi_str     = _fmt_pct(row.annual_equity_roi) if row.annual_equity_roi is not None else "—"
        lines.append(
            f"| {row.rank}{winner_mark} | {name} | {_fmt_won(l.asking_price)} "
            f"| {row.total_score:.1f} | {jeonse_str} | {net_str} | {roi_str} |"
        )
    lines.append("")

    # 최종 추천 매물
    winner = rows[0]
    w      = winner.listing
    wname  = (w.complex_name or w.address).strip()
    lines.append("## 최종 추천 매물")
    lines.append("")
    lines.append(f"### 🏆 {wname}")
    lines.append("")
    lines.append(f"- **주소**: {w.address}")
    lines.append(f"- **호가**: {_fmt_won(w.asking_price)}")
    if winner.price_per_m2:
        lines.append(f"- **㎡당 가격**: {_fmt_won(winner.price_per_m2)}")
    if winner.jeonse_ratio is not None:
        lines.append(f"- **전세가율**: {winner.jeonse_ratio:.0f}%")
    lines.append(f"- **종합 점수**: {winner.total_score:.1f} / 10")
    if winner.highlights:
        lines.append("")
        lines.append("**강점**:")
        for h in winner.highlights:
            lines.append(f"- ✅ {h}")
    if winner.warnings:
        lines.append("")
        lines.append("**주의사항**:")
        for w_ in winner.warnings:
            lines.append(f"- ⚠️ {w_}")
    lines.append("")

    # 매물별 상세 비교
    lines.append("## 매물별 상세 비교")
    lines.append("")
    for row in rows:
        l        = row.listing
        name     = (l.complex_name or l.address).strip()
        rank_str = f"{row.rank}위" + (" 🏆" if row.is_winner else "")
        lines.append(f"### {rank_str} — {name}")
        lines.append("")
        lines.append("| 항목 | 내용 |")
        lines.append("|------|------|")
        lines.append(f"| 주소 | {l.address} |")
        lines.append(f"| 매물 유형 | {l.property_type} |")
        lines.append(f"| 호가 | {_fmt_won(l.asking_price)} |")
        if l.area_m2:
            lines.append(f"| 면적 | {l.area_m2:.0f}㎡ |")
        if row.price_per_m2:
            lines.append(f"| ㎡당 가격 | {_fmt_won(row.price_per_m2)} |")
        if l.floor:
            lines.append(f"| 층수 | {l.floor}층 |")
        if l.built_year:
            lines.append(f"| 준공연도 | {l.built_year}년 |")
        if l.station_distance_m:
            lines.append(f"| 역까지 거리 | {l.station_distance_m:,}m |")
        if l.deposit_price:
            lines.append(f"| 전세가 | {_fmt_won(l.deposit_price)} |")
        if row.jeonse_ratio is not None:
            lines.append(f"| 전세가율 | {row.jeonse_ratio:.0f}% |")
        if row.monthly_net is not None:
            lines.append(f"| 월 순현금흐름 | {_fmt_won(row.monthly_net)} |")
        if row.annual_equity_roi is not None:
            lines.append(f"| 연 자기자본수익률 | {_fmt_pct(row.annual_equity_roi)} |")
        lines.append(f"| 종합 점수 | {row.total_score:.1f} / 10 |")
        if any([row.price_score, row.location_score, row.investment_score, row.risk_score]):
            lines.append(
                f"| 세부 점수 | "
                f"가격 {row.price_score:.1f} / "
                f"입지 {row.location_score:.1f} / "
                f"투자 {row.investment_score:.1f} / "
                f"리스크 {row.risk_score:.1f} |"
            )
        lines.append("")
        if row.highlights:
            lines.append("**강점**: " + " / ".join(row.highlights))
            lines.append("")
        if row.warnings:
            lines.append("**주의**: " + " / ".join(row.warnings))
            lines.append("")

    return "\n".join(lines)
