"""
DeepAgent 부동산 가치 감정평가 — 리포트 생성 노드
router.py에서 분리된 독립 모듈

역할:
  - 전문 에이전트가 채운 AgentState를 받아
    마크다운 감정평가 리포트 문자열로 변환
  - LangGraph 노드 함수 report_node 제공
  - AppraisalResult 기반 가격 분석 리포트 생성 함수 제공
"""

from __future__ import annotations

import logging
import sys
import os
from datetime import datetime as _dt

_BACKEND_DIR  = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
#  내부 헬퍼
# ─────────────────────────────────────────

def _fmt_won(manwon: int, suffix: str = "원") -> str:
    return f"{manwon * 10_000:,}{suffix}"


def _fmt_date(as_of: str) -> str:
    if as_of and len(as_of) >= 8:
        try:
            d = _dt.strptime(as_of[:8], "%Y%m%d")
            return d.strftime("%Y년 %m월 %d일")
        except ValueError:
            pass
    return _dt.now().strftime("%Y년 %m월 %d일") + " (현재)"


def _geo_val(geo, key: str, default=None):
    if isinstance(geo, dict):
        return geo.get(key, default)
    return getattr(geo, key, default)


# ─────────────────────────────────────────
#  analysis_result dict → AppraisalResult 변환
# ─────────────────────────────────────────

def _dict_to_appraisal_result(
    result: dict,
    *,
    additional_warnings: list[str] | None = None,
) -> "AppraisalResult":
    from schemas.appraisal_result import AppraisalResult, ValuationMethodResult

    manwon = 10_000

    estimated  = result.get("estimated_value", 0) or 0
    value_min  = result.get("value_min", 0) or 0
    value_max  = result.get("value_max", 0) or 0
    comp_count = result.get("comparable_count", 0) or 0
    months     = result.get("used_months", 0) or 0
    samples    = result.get("comparables") or []

    # 신뢰도 — 다요인 산출 (매칭수준·표본수·산포·신선도·시점수정) + 백테스트 보정
    from confidence import compute_confidence
    conf = compute_confidence(
        count       = comp_count,
        samples     = samples or None,
        used_months = months,
        source      = result.get("source", "") or "",
    )
    confidence = conf["score"]

    # 공시가격 대비 비율
    official_land_price = result.get("official_land_price", 0) or 0
    area_pyeong         = result.get("area_pyeong", 0) or 0
    area_sqm_approx     = round(area_pyeong * 3.3058, 1) if area_pyeong else 0
    exclusive_area      = result.get("exclusive_area_m2", 0.0) or area_sqm_approx or 0.0

    official_price_ratio = None
    if official_land_price > 0 and exclusive_area > 0 and estimated > 0:
        official_total_manwon = round(official_land_price * exclusive_area / 10000)
        if official_total_manwon > 0:
            official_price_ratio = round(estimated / official_total_manwon, 2)

    # 시산가액 조정 (단일 방법)
    breakdown = []
    if result.get("valuation_method") and estimated:
        breakdown.append(ValuationMethodResult(
            method          = result["valuation_method"],
            estimated_value = estimated * manwon,
            weight          = 1.0,
            note            = f"신뢰도 {confidence:.0%}",
        ))

    appraisal_date_str = _dt.now().strftime("%Y년 %m월 %d일") + " (현재)"

    # 비교사례 목록 — 요인보정 포함 변환 (서비스 로직 재사용)
    comparables_out = []
    if samples:
        try:
            from services.price_analysis_service import _to_comparables
            apt_matched = samples[0].get("apt_name_matched", "") or ""
            comparables_out = _to_comparables({"samples": samples}, apt_matched)
        except Exception as e:
            logger.warning("비교사례 변환 실패: %s", e)

    return AppraisalResult(
        estimated_price      = estimated * manwon if estimated else None,
        low_price            = value_min * manwon if value_min else None,
        high_price           = value_max * manwon if value_max else None,
        confidence           = confidence,
        appraisal_date       = appraisal_date_str,
        land_use_zone        = result.get("land_use_zone") or None,
        official_land_price  = official_land_price if official_land_price > 0 else None,
        official_price_ratio = official_price_ratio,
        build_year           = result.get("build_year") or None,
        exclusive_area_m2    = exclusive_area if exclusive_area > 0 else None,
        valuation_breakdown  = breakdown,
        comparables          = comparables_out,
        legal_restrictions   = result.get("legal_restrictions", []) or [],
        development_plans    = result.get("development_plans", []) or [],
        warnings             = list(additional_warnings or []),
        data_source          = [result["valuation_method"]] if result.get("valuation_method") else [],
        raw                  = result,
    )


# ─────────────────────────────────────────
#  LangGraph 노드
# ─────────────────────────────────────────

def report_node(state: dict) -> dict:
    from schemas.report import AppraisalReport

    intent = state.get("intent")
    geo    = state.get("geocoding_result") or {}
    result = state.get("analysis_result") or {}

    if not result:
        state["final_report"] = "❌ 시세추정 결과 없음"
        return state

    address    = _geo_val(geo, "address_name", "") or ""
    category   = getattr(intent, "category", "")
    detail     = getattr(intent, "category_detail", "")
    area_raw   = getattr(intent, "area_raw", "") or ""
    building   = state.get("building_name", "") or (_geo_val(geo, "place_name", "") or "")
    dong_no    = getattr(intent, "dong_no", "") or ""
    ho_no      = getattr(intent, "ho_no", "") or ""
    floor      = getattr(intent, "floor_inferred", None)
    trans_type = getattr(intent, "transaction_type", "") or ""
    land_use          = _geo_val(geo, "land_use_zone", "") or ""
    asking            = getattr(intent, "price_max", None) or getattr(intent, "price_min", None)
    as_of             = getattr(intent, "appraisal_date", "") or ""
    # state에서 명시적으로 전달된 감정평가 목적 (intent보다 우선)
    appraisal_purpose = state.get("appraisal_purpose", "") or getattr(intent, "appraisal_purpose", "") or ""

    # 기준시점 표시
    appraisal_date_display = _fmt_date(as_of)

    # 감정평가 핵심 수치
    estimated   = result.get("estimated_value", 0)
    value_min   = result.get("value_min", 0)
    value_max   = result.get("value_max", 0)
    ppyeong     = result.get("price_per_pyeong", 0)
    reg_ppyeong = result.get("regional_avg_per_pyeong", 0)
    comp_avg    = result.get("comparable_avg", 0)
    comp_count  = result.get("comparable_count", 0)
    cap_rate    = result.get("cap_rate", 0.0)
    annual_inc  = result.get("annual_income", 0)
    roi_5yr     = result.get("roi_5yr", 0.0)
    inv_grade   = result.get("investment_grade", "")
    method      = result.get("valuation_method", "")
    opinion     = result.get("appraisal_opinion", "")
    strengths   = result.get("strengths", [])
    risks       = result.get("risk_factors", [])
    recommendation = result.get("recommendation", "")

    # 신규 필드
    build_year_val      = result.get("build_year", 0) or 0
    exclusive_area_val  = result.get("exclusive_area_m2", 0.0) or 0.0
    land_use_zone_val   = result.get("land_use_zone", "") or land_use
    official_lp         = _geo_val(geo, "official_land_price", 0) or result.get("official_land_price", 0) or 0
    legal_restrictions  = result.get("legal_restrictions", []) or []
    development_plans   = result.get("development_plans", []) or []
    geocoding_warnings = []
    category_conflict_message = _geo_val(geo, "category_conflict_message", "") or ""
    if category_conflict_message:
        geocoding_warnings.append(category_conflict_message)

    # 공시가격 대비 비율
    official_ratio_str = ""
    if official_lp > 0 and exclusive_area_val > 0 and estimated > 0:
        official_total_manwon = round(official_lp * exclusive_area_val / 10000)
        if official_total_manwon > 0:
            ratio = round(estimated / official_total_manwon, 2)
            official_ratio_str = f"공시가 기준 추정액의 {ratio:.1f}배"

    # ── 대상물 정보 테이블 ────────────────────────────────────────────────
    unit_str = " ".join(filter(None, [dong_no, ho_no]))
    subject_rows = [r for r in [
        f"| 소재지 | {address} |"                          if address              else None,
        f"| 건물명 | {building} |"                         if building             else None,
        f"| 유형 | {category} / {detail} |"                if detail               else f"| 유형 | {category} |",
        f"| 거래 유형 | {trans_type} |"                    if trans_type           else None,
        f"| 동 / 호 | {unit_str} |"                       if unit_str             else None,
        f"| 층수 | {floor}층 |"                            if floor                else None,
        f"| 전용면적 | {area_raw} |"                       if area_raw             else None,
        f"| 건축연도 | {build_year_val}년 |"               if build_year_val       else None,
        f"| 용도지역 | {land_use_zone_val} |"              if land_use_zone_val    else None,
        f"| 공시지가 | {official_lp:,}원/㎡ |"             if official_lp          else None,
        f"| 호가 | {asking:,}만원 |"                       if asking               else None,
        f"| 조회 목적 | {appraisal_purpose} |"             if appraisal_purpose    else None,
        f"| 산정 방식 | {method} |"                        if method               else None,
        f"| 기준시점 | {appraisal_date_display} |",
    ] if r is not None]

    lines = [
        "# 부동산 AI 시세추정 리포트",
        "",
        "> 본 리포트는 자동가치산정(AVM) 기반 참고용 시세 추정 자료이며, "
        "「감정평가 및 감정평가사에 관한 법률」에 따른 감정평가가 아닙니다.",
        "",
        "## 대상물 정보",
        "| 항목 | 내용 |",
        "|------|------|",
        *subject_rows,
        "",
        "## AI 추정 시세",
        "| 구분 | 금액 |",
        "|------|------|",
        f"| **추정 시장가치** | **{_fmt_won(estimated)}** |",
        f"| 추정 범위 | {_fmt_won(value_min)} ~ {_fmt_won(value_max)} |",
        f"| 평당가 | {_fmt_won(ppyeong, '원/평')} |",
        f"| 지역 평균 평당가 | {_fmt_won(reg_ppyeong, '원/평')} |",
        f"| 인근 실거래 평균 | {_fmt_won(comp_avg)} ({comp_count}건) |",
    ]
    if official_ratio_str:
        lines.append(f"| 공시가격 대비 | {official_ratio_str} |")
    lines.append("")

    # ── 산정방법별 추정가 ─────────────────────────────────────────────────
    if method and estimated:
        lines += [
            "## 산정방법별 추정가",
            "| 산정방법 | 추정가 | 가중치 | 비고 |",
            "|---|---|---|---|",
            f"| {method} | {_fmt_won(estimated)} | 100% | |",
            "",
        ]

    # ── 투자 수익성 ───────────────────────────────────────────────────────
    lines += [
        "## 투자 수익성",
        "| 항목 | 수치 |",
        "|------|------|",
        f"| Cap Rate | {cap_rate}% |",
        f"| 연 임대수입 추정 | {_fmt_won(annual_inc)} |",
        f"| 5년 예상 수익률 | {roi_5yr}% |",
        f"| **투자등급** | **{inv_grade}** |",
        "",
    ]

    # ── 공법상 제한사항 ───────────────────────────────────────────────────
    if legal_restrictions:
        lines += ["## 공법상 제한사항"]
        for item in legal_restrictions:
            lines.append(f"- ⚠️ {item}")
        lines.append("")

    # ── 인근 개발계획 ─────────────────────────────────────────────────────
    if development_plans:
        lines += ["## 인근 개발계획"]
        for item in development_plans:
            lines.append(f"- {item}")
        lines.append("")

    if geocoding_warnings:
        lines += ["## 유형 확인 필요"]
        for warning in geocoding_warnings:
            lines.append(f"- ⚠️ {warning}")
        lines.append("")

    # ── AI 분석 의견 ──────────────────────────────────────────────────────
    lines += [
        "## AI 분석 의견",
        opinion,
        "",
        "### 가치 상승 요인",
    ]
    for s in strengths:
        lines.append(f"- {s}")

    lines += ["", "### 리스크 요인"]
    for r in risks:
        lines.append(f"- {r}")

    lines += ["", f"**종합 추천**: {recommendation}"]

    markdown = "\n".join(lines)
    state["final_report"] = markdown

    state["report_output"] = AppraisalReport(
        structured=_dict_to_appraisal_result(
            result,
            additional_warnings=geocoding_warnings,
        ),
        markdown=markdown,
    )

    logger.debug("report_node: 감정평가 리포트 생성 완료 — %d자", len(markdown))
    return state


# ─────────────────────────────────────────
#  AppraisalResult 기반 가격 분석 리포트
# ─────────────────────────────────────────

def generate_price_analysis_report(result: "AppraisalResult") -> str:
    """
    AppraisalResult → 마크다운 가격 분석 리포트.
    단위 변환: 원(schemas) → 표시용
    """
    def _won(v: int | None) -> str:
        return f"{v:,}원" if v else "—"

    def _conf_label(c: float) -> str:
        if c >= 0.80: return f"높음 ({c:.0%}) — 실거래 충분·최신 데이터"
        if c >= 0.60: return f"보통 ({c:.0%}) — 표본 제한적"
        if c >= 0.40: return f"낮음 ({c:.0%}) — 폴백 출처 또는 데이터 노후"
        return f"매우 낮음 ({c:.0%}) — 실거래 없음, 참고용으로만 활용"

    level_map = {
        "same_complex": "동일 단지",
        "same_dong":    "동일 동",
        "same_gu":      "동일 구",
        "nearby":       "인근",
        "fallback":     "폴백",
    }

    lines = [
        "# 가격 분석 리포트",
        "",
        "> ⚠️ 이 리포트는 공개 실거래가 기반 간이 분석입니다. 실제 거래 판단 시 전문가 자문을 받으세요.",
        "",
    ]

    # ── 추정가 ────────────────────────────────────────────────────────────
    lines += [
        "## 추정 시장가치",
        "| 구분 | 금액 |",
        "|------|------|",
        f"| **추정가** | **{_won(result.estimated_price)}** |",
        f"| 하단 | {_won(result.low_price)} |",
        f"| 상단 | {_won(result.high_price)} |",
    ]
    if result.asking_price:
        lines.append(f"| 호가 | {_won(result.asking_price)} |")
    if result.official_price_ratio:
        lines.append(f"| 공시가격 대비 | 공시가 기준 추정액의 {result.official_price_ratio:.1f}배 |")
    lines.append(f"| 신뢰도 | {_conf_label(result.confidence)} |")
    if result.appraisal_date:
        lines.append(f"| 기준시점 | {result.appraisal_date} |")
    if result.appraisal_purpose:
        lines.append(f"| 조회 목적 | {result.appraisal_purpose} |")
    lines.append("")

    # ── 물건 기본사항 ──────────────────────────────────────────────────────
    prop_rows = []
    if result.land_use_zone:
        prop_rows.append(f"| 용도지역 | {result.land_use_zone} |")
    if result.official_land_price:
        prop_rows.append(f"| 공시지가 | {result.official_land_price:,}원/㎡ |")
    if result.build_year:
        prop_rows.append(f"| 건축연도 | {result.build_year}년 |")
    if result.exclusive_area_m2:
        prop_rows.append(f"| 전용면적 | {result.exclusive_area_m2:.2f}㎡ |")
    if result.total_area_m2:
        prop_rows.append(f"| 연면적 | {result.total_area_m2:.2f}㎡ |")
    if result.jimok:
        prop_rows.append(f"| 지목 | {result.jimok} |")
    if result.road_side:
        prop_rows.append(f"| 도로접면 | {result.road_side} |")

    if prop_rows:
        lines += [
            "## 물건 기본사항",
            "| 항목 | 내용 |",
            "|---|---|",
            *prop_rows,
            "",
        ]

    # ── 산정방법별 추정가 ─────────────────────────────────────────────────
    if result.valuation_breakdown:
        lines += [
            "## 산정방법별 추정가",
            "| 산정방법 | 추정가 | 가중치 | 비고 |",
            "|---|---|---|---|",
        ]
        for b in result.valuation_breakdown:
            val_str    = _won(b.estimated_value)
            weight_str = f"{b.weight:.0%}" if b.weight is not None else "—"
            note_str   = b.note or ""
            lines.append(f"| {b.method} | {val_str} | {weight_str} | {note_str} |")
        lines.append("")

    # ── 비교 사례 ─────────────────────────────────────────────────────────
    if result.comparables:
        level_counts: dict[str, int] = {}
        for c in result.comparables:
            lv = level_map.get(c.match_level or "", c.match_level or "기타")
            level_counts[lv] = level_counts.get(lv, 0) + 1
        quality_summary = ", ".join(f"{lv} {cnt}건" for lv, cnt in level_counts.items())

        # 요인보정 컬럼 포함 여부 결정 (비기본값이 있으면 상세 테이블)
        has_factors = any(
            c.region_factor != 1.0 or c.individual_factor != 1.0 or c.adjusted_price_per_m2
            for c in result.comparables
        )

        lines += [
            "## 비교 사례",
            f"> 총 {len(result.comparables)}건 — {quality_summary}",
            "",
        ]

        if has_factors:
            lines += [
                "| 단지명 | 면적 | 층수 | 원거래가/㎡ | 시점수정 | 지역요인 | 개별요인 | 비준단가/㎡ | 거래일 | 매칭 |",
                "|--------|------|------|-----------|---------|---------|---------|----------|--------|------|",
            ]
            for c in result.comparables:
                name      = c.complex_name or "—"
                area      = f"{c.area_m2:.1f}㎡" if c.area_m2 else "—"
                fl        = c.floor or "—"
                raw_pm2   = f"{c.price_per_m2:,}원" if c.price_per_m2 else "—"
                tadj      = f"×{c.time_adj_factor:.4f}" if c.time_adj_factor != 1.0 else "없음"
                rgf       = f"×{c.region_factor:.2f}" if c.region_factor != 1.0 else "×1.00"
                idf       = f"×{c.individual_factor:.2f}" if c.individual_factor != 1.0 else "×1.00"
                adj_pm2   = f"{c.adjusted_price_per_m2:,}원" if c.adjusted_price_per_m2 else "—"
                date      = c.deal_date or "—"
                level     = level_map.get(c.match_level or "", c.match_level or "—")
                lines.append(f"| {name} | {area} | {fl} | {raw_pm2} | {tadj} | {rgf} | {idf} | {adj_pm2} | {date} | {level} |")
        else:
            lines += [
                "| 단지명 | 면적 | 거래가 | 거래일 | 매칭 수준 |",
                "|--------|------|--------|--------|-----------|",
            ]
            for c in result.comparables:
                name  = c.complex_name or "—"
                area  = f"{c.area_m2:.1f}㎡" if c.area_m2 else "—"
                price = _won(c.deal_price)
                date  = c.deal_date or "—"
                level = level_map.get(c.match_level or "", c.match_level or "—")
                lines.append(f"| {name} | {area} | {price} | {date} | {level} |")
        lines.append("")

    # ── 공법상 제한사항 ───────────────────────────────────────────────────
    if result.legal_restrictions:
        lines += ["## 공법상 제한사항"]
        for item in result.legal_restrictions:
            lines.append(f"- ⚠️ {item}")
        lines.append("")

    # ── 인근 개발계획 ─────────────────────────────────────────────────────
    if result.development_plans:
        lines += ["## 인근 개발계획"]
        for item in result.development_plans:
            lines.append(f"- {item}")
        lines.append("")

    # ── 경고 및 데이터 출처 ──────────────────────────────────────────────
    if result.warnings:
        lines += ["## 주의사항"]
        for w in result.warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    if result.data_source:
        lines += [
            "## 데이터 출처",
            ", ".join(result.data_source),
            "",
        ]

    return "\n".join(lines)
