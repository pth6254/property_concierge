"""
complex_recommend_service.py — 실거래 기반 단지 추천 (전국)

샘플 CSV 매물이 아닌 국토부 실거래 데이터로 지역 내 아파트 단지를
집계·점수화해 추천한다. 로컬 스토어(transaction_store) 우선 조회라
같은 지역 재요청은 API 호출 없이 즉시 응답한다.

점수 모델 (0~10):
  예산 적합  30% — 예산 중앙값에 가까울수록 (예산 미입력 시 타 축에 재배분)
  가격 매력  30% — 지역 평균 평단가 대비 낮을수록
  거래 유동성 25% — 최근 거래 건수 (환금성·데이터 신뢰)
  연식       15% — 신축일수록

한계 (호가 아님):
  추천 대상은 '단지'이며 가격은 최근 실거래 기반 추정 시세다.
  실제 매물 존재 여부·호가는 별도 확인 필요.
"""

from __future__ import annotations

import sys
import os
from collections import Counter
from datetime import datetime
from statistics import mean

_SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_SERVICES_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from cache_db import get_lawd_code
from services.complex_address_service import enrich_complex_addresses
from price_engine import (
    MOLIT_API_KEY,
    MOLIT_BASE_URL,
    MOLIT_ENDPOINTS,
    _apply_time_adjustment,
    _fetch_one_month,
    _get_recent_deal_ymds,
)

MIN_DEALS_PER_COMPLEX = 2     # 최소 거래 건수 (1건짜리 노이즈 제외)

_WEIGHTS = {"budget": 0.30, "value": 0.30, "liquidity": 0.25, "age": 0.15}


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


# ─────────────────────────────────────────
#  데이터 적재 (스토어 우선 → API 폴백)
# ─────────────────────────────────────────

def _load_samples(lawd_code: str, months: int) -> list[dict]:
    url      = MOLIT_BASE_URL + MOLIT_ENDPOINTS[("주거용", "아파트")]
    safe_key = MOLIT_API_KEY.replace("+", "%2B").replace("=", "%3D")
    samples: list[dict] = []
    for ym in _get_recent_deal_ymds(months=months):
        samples.extend(_fetch_one_month((url, safe_key, lawd_code, ym, "주거용")))
    return samples


# ─────────────────────────────────────────
#  단지 집계
# ─────────────────────────────────────────

def _aggregate_complexes(samples: list[dict]) -> list[dict]:
    """시점수정된 샘플 → 단지별 통계."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for s in samples:
        name = (s.get("apt_name") or "").strip()
        if name and (s.get("price") or 0) > 0 and (s.get("area_sqm") or 0) > 0:
            groups.setdefault(((s.get("dong") or "").strip(), name), []).append(s)

    complexes = []
    for (_, name), deals in groups.items():
        if len(deals) < MIN_DEALS_PER_COMPLEX:
            continue
        per_sqms = [d["per_sqm"] for d in deals if (d.get("per_sqm") or 0) > 0]
        if not per_sqms:
            continue
        years = [int(d["year_built"]) for d in deals
                 if str(d.get("year_built") or "").isdigit()]
        complexes.append({
            "complex_name":  name,
            "dong":          Counter(d.get("dong") or "" for d in deals).most_common(1)[0][0],
            "deal_count":    len(deals),
            "avg_price":     round(mean(d["price"] for d in deals)),          # 만원 (시점수정)
            "avg_per_sqm":   round(mean(per_sqms)),                            # 만원/㎡
            "avg_area_m2":   round(mean(d["area_sqm"] for d in deals), 1),
            "build_year":    max(years) if years else 0,
            "last_deal_ym":  max(f"{d.get('deal_year','')}{int(d.get('deal_month') or 0):02d}"
                                 for d in deals),
        })
    return complexes


# ─────────────────────────────────────────
#  점수화
# ─────────────────────────────────────────

def _score_complex(c: dict, region_avg_per_sqm: float,
                   budget_min: int, budget_max: int, priority: str | None = None) -> tuple[float, list[str]]:
    reasons: list[str] = []
    has_budget = budget_max > 0
    weights = dict(_WEIGHTS)
    if priority in {"value", "liquidity", "age"}:
        # 사용자가 고른 축의 비중을 높이되 모든 축의 합은 1을 유지한다.
        remaining = 1 - weights[priority]
        for key in weights:
            weights[key] = weights[key] * (remaining - 0.2) / remaining if key != priority else weights[key] + 0.2
    if not has_budget:   # 예산 미입력 → 예산 가중치를 가격·유동성에 재배분
        weights["value"]     += weights["budget"] * 0.6
        weights["liquidity"] += weights["budget"] * 0.4
        weights["budget"] = 0.0

    # 예산 적합
    budget_score = 0.0
    if has_budget:
        lo = budget_min if budget_min > 0 else round(budget_max * 0.5)
        mid, half = (lo + budget_max) / 2, max((budget_max - lo) / 2, 1)
        diff = abs(c["avg_price"] - mid)
        budget_score = _clamp(10 * (1 - diff / (half * 2)))
        if lo <= c["avg_price"] <= budget_max:
            reasons.append(f"평균 실거래가 {c['avg_price']:,}만원 — 예산 범위 내")

    # 가격 매력 (지역 평균 평단가 대비)
    value_score = 5.0
    if region_avg_per_sqm > 0 and c["avg_per_sqm"] > 0:
        ratio = c["avg_per_sqm"] / region_avg_per_sqm
        value_score = _clamp(10 * (1.15 - ratio) / 0.30)
        pct = (1 - ratio) * 100
        if pct >= 3:
            reasons.append(f"지역 평균 평단가 대비 {pct:.0f}% 낮음")
        elif pct <= -10:
            reasons.append(f"지역 평균 평단가 대비 {-pct:.0f}% 높음 (프리미엄 단지)")

    # 거래 유동성
    liquidity_score = _clamp(c["deal_count"] / 2.0)
    if c["deal_count"] >= 10:
        reasons.append(f"최근 거래 {c['deal_count']}건 — 유동성 우수")

    # 연식
    age_score = 5.0
    if c["build_year"] > 0:
        age = datetime.now().year - c["build_year"]
        age_score = _clamp(10 - max(age - 5, 0) * 0.35)
        if age <= 7:
            reasons.append(f"{c['build_year']}년 준공 신축급")

    total = (budget_score  * weights["budget"]
             + value_score * weights["value"]
             + liquidity_score * weights["liquidity"]
             + age_score   * weights["age"])
    c["score_factors"] = {"budget": round(budget_score, 2), "value": round(value_score, 2),
                          "liquidity": round(liquidity_score, 2), "age": round(age_score, 2)}
    c["score_weights"] = {key: round(value, 3) for key, value in weights.items()}
    return round(total, 2), reasons


# ─────────────────────────────────────────
#  공개 API
# ─────────────────────────────────────────

def recommend_complexes(
    region: str,
    budget_min: int = 0,     # 만원
    budget_max: int = 0,     # 만원
    area_m2: float = 0.0,
    months: int = 6,
    limit: int = 5,
    *, region_code: str | None = None, area_min_sqm: float = 0,
    strict_budget: bool = False, min_build_year: int = 0, priority: str | None = None,
) -> dict:
    """
    실거래 기반 단지 추천.

    반환: {
      region, months, complex_count, region_avg_per_sqm,
      results: [{complex_name, dong, avg_price, avg_per_sqm, avg_area_m2,
                 deal_count, build_year, last_deal_ym, score, reasons}, ...],
      report: 마크다운, error: ""
    }
    """
    region = (region or "").strip()
    selected_dong = None
    if region_code:
        from db.base import session_scope
        from db.models import LegalRegion
        from fastapi import HTTPException
        with session_scope() as session:
            selected = session.get(LegalRegion, region_code)
            if not selected or not selected.is_active or selected.level not in {"sigungu", "eup_myeon_dong"}:
                raise HTTPException(status_code=404, detail="선택한 지역을 찾을 수 없습니다")
            lawd = selected.lawd_code
            region = selected.full_name
            if selected.level == "eup_myeon_dong":
                selected_dong = (selected.code, selected.name)
    else:
        lawd = get_lawd_code(region)
    if not lawd:
        return {"error": f"'{region}' 지역을 찾을 수 없습니다. 시군구 단위로 입력하세요 (예: 춘천시, 해운대구)",
                "results": []}

    samples = [s for s in _load_samples(lawd, months) if not s.get("is_cancelled")]
    if selected_dong:
        code, name = selected_dong
        samples = [s for s in samples if s.get("bjdong_code") == code or
                   (not s.get("bjdong_code") and (s.get("dong") or "").strip() == name)]
    if not samples:
        return {"error": f"'{region}' 최근 {months}개월 아파트 실거래 없음", "results": []}

    if area_min_sqm > 0:
        samples = [s for s in samples if (s.get("area_sqm") or 0) >= area_min_sqm]
    # 면적 필터 (거래 단위) → 시점수정 → 단지 집계
    if area_m2 > 0:
        samples = [s for s in samples
                   if (s.get("area_sqm") or 0) > 0
                   and abs(s["area_sqm"] - area_m2) / area_m2 <= 0.15]
        if not samples:
            return {"error": f"'{region}' 전용 {area_m2}㎡±15% 거래 없음 — 면적 조건을 넓혀보세요",
                    "results": []}

    samples, _ = _apply_time_adjustment(samples, "주거용", "", region)
    complexes  = _aggregate_complexes(samples)
    if min_build_year:
        complexes = [c for c in complexes if c["build_year"] and c["build_year"] >= min_build_year]
    if not complexes:
        return {"error": "집계 가능한 단지 없음 (단지당 최소 2건 거래 필요)", "results": []}

    region_avg_per_sqm = round(mean(c["avg_per_sqm"] for c in complexes))

    # 예산 필터 (완만: 평균가가 예산 상한 ±10% 이내)
    pool = complexes
    if budget_max > 0:
        pool = [c for c in complexes if c["avg_price"] <= budget_max * (1 if strict_budget else 1.10)
                and (budget_min <= 0 or c["avg_price"] >= budget_min * 0.90)]
        if not pool:
            return {"error": f"예산 {budget_min:,}~{budget_max:,}만원에 맞는 단지 없음"
                             f" (지역 평균 평단가 {region_avg_per_sqm:,}만원/㎡)",
                    "results": [], "region_avg_per_sqm": region_avg_per_sqm}

    for c in pool:
        c["score"], c["reasons"] = _score_complex(c, region_avg_per_sqm, budget_min, budget_max, priority)
        if priority in {"cash", "monthly"}:
            c["reasons"].append("필요 현금·월 상환액은 후보를 저장한 뒤 자금 조건으로 비교하세요")
    pool.sort(key=lambda c: c["score"], reverse=True)
    results = pool[:limit]
    enrich_complex_addresses(results, region, lawd)

    # ── 마크다운 리포트 ──
    lines = [
        f"# {region} 실거래 기반 단지 추천",
        "",
        f"> 최근 {months}개월 아파트 실거래 {len(samples)}건 · 단지 {len(complexes)}개 분석"
        f" · 지역 평균 평단가 {region_avg_per_sqm:,}만원/㎡",
        "> 가격은 실거래 기반 추정 시세이며 호가·매물 존재 여부는 별도 확인이 필요합니다.",
        "",
        "| 순위 | 단지명 | 동 | 평균 실거래가 | 평단가 | 거래 | 연식 | 점수 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(results, 1):
        lines.append(
            f"| {i} | {c['complex_name']} | {c['dong']} | {c['avg_price']:,}만원 "
            f"| {c['avg_per_sqm']:,}만원/㎡ | {c['deal_count']}건 "
            f"| {c['build_year'] or '—'} | {c['score']} |")
    lines.append("")
    for i, c in enumerate(results, 1):
        lines.append(f"**{c['complex_name']} 주소** — 도로명: {c.get('road_address') or '확인되지 않음'} / 지번: {c.get('jibun_address') or '확인되지 않음'}")
        if c["reasons"]:
            lines.append(f"**{i}. {c['complex_name']}** — " + " · ".join(c["reasons"]))

    return {
        "region":              region,
        "lawd_code":           lawd,
        "months":              months,
        "sample_count":        len(samples),
        "complex_count":       len(complexes),
        "region_avg_per_sqm":  region_avg_per_sqm,
        "results":             results,
        "report":              "\n".join(lines),
        "error":               "",
    }
