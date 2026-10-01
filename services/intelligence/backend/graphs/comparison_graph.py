"""
comparison_graph.py — 매물 비교 LangGraph 파이프라인

입력 (ComparisonState) — 두 가지 방식 중 하나:
  방식 A: raw_input (dict)              → ComparisonInput 변환
  방식 B: comparison_input (ComparisonInput) → 그대로 사용

출력 (ComparisonState):
  result  : ComparisonResult — 비교 분석 결과
  report  : str              — 마크다운 결정 리포트
  error   : str              — 오류 메시지

노드 흐름:
  입력정규화 ──(OK)──▶ 비교실행 ──(OK)──▶ 리포트생성 ──▶ END
     └──(오류)──▶ 오류처리 ──▶ END
                          └──(오류)──▶ 오류처리 ──▶ END
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Optional

from typing_extensions import TypedDict
from langgraph.graph import END, StateGraph

_GRAPHS_DIR   = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_GRAPHS_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schemas.comparison import ComparisonInput, ComparisonResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
#  State
# ─────────────────────────────────────────

class ComparisonState(TypedDict, total=False):
    """비교 파이프라인 공유 상태"""
    raw_input:        Optional[dict]             # 방식 A
    comparison_input: Optional[ComparisonInput]  # 방식 B
    result:           Optional[ComparisonResult] # 비교 결과
    report:           str                        # 마크다운 리포트
    report_output:    Optional[object]           # ComparisonReport (구조화 리포트)
    error:            str                        # 오류 메시지


# ─────────────────────────────────────────
#  노드
# ─────────────────────────────────────────

def normalize_input_node(state: ComparisonState) -> ComparisonState:
    """
    ComparisonInput이 없으면 raw_input dict를 변환한다.
    """
    if state.get("comparison_input") is not None:
        return state

    raw = state.get("raw_input") or {}
    try:
        from schemas.property_listing import PropertyListing

        listings_raw = raw.get("listings", [])
        if not listings_raw:
            return {**state, "error": "비교할 매물 목록(listings)이 없습니다."}

        listings = [
            l if isinstance(l, PropertyListing) else PropertyListing(**l)
            for l in listings_raw
        ]
        inp = ComparisonInput(
            listings              = listings,
            recommendation_results= raw.get("recommendation_results"),
            simulation_results    = raw.get("simulation_results"),
            budget_max            = raw.get("budget_max"),
        )
        logger.debug("[비교그래프] 입력정규화 — dict 변환 완료 (%d건)", len(listings))
        return {**state, "comparison_input": inp}

    except Exception as exc:
        logger.exception("[비교그래프] normalize_input_node 실패")
        return {**state, "error": f"입력 변환 오류: {exc}"}


def compare_node(state: ComparisonState) -> ComparisonState:
    """ComparisonInput → ComparisonResult 계산"""
    inp = state.get("comparison_input")
    if inp is None:
        return {**state, "error": "comparison_input이 없습니다."}

    try:
        from services.comparison_service import compare_listings

        result = compare_listings(
            listings              = inp.listings,
            recommendation_results= inp.recommendation_results,
            simulation_results    = inp.simulation_results,
        )
        logger.debug("[비교그래프] 비교실행 완료 — %d건", len(inp.listings))
        return {**state, "result": result}

    except Exception as exc:
        logger.exception("[비교그래프] compare_node 실패")
        return {**state, "error": f"비교 분석 오류: {exc}"}


def report_node(state: ComparisonState) -> ComparisonState:
    """ComparisonResult.decision_report를 state.report + report_output으로 저장한다."""
    from schemas.report import ComparisonReport

    result = state.get("result")
    if result is None:
        return {**state, "error": "비교 결과가 없습니다."}

    report        = result.decision_report
    report_output = ComparisonReport(result=result, markdown=report)
    return {**state, "report": report, "report_output": report_output}


def error_handler_node(state: ComparisonState) -> ComparisonState:
    """오류 메시지를 fallback 리포트에 반영한다."""
    msg = state.get("error", "알 수 없는 오류")
    logger.warning("[비교그래프] 오류처리: %s", msg)
    if not state.get("report"):
        return {**state, "report": f"# 비교 분석 오류\n\n> {msg}\n"}
    return state


# ─────────────────────────────────────────
#  라우팅 함수
# ─────────────────────────────────────────

def _route_after_normalize(state: ComparisonState) -> str:
    return "오류처리" if state.get("error") else "비교실행"


def _route_after_compare(state: ComparisonState) -> str:
    return "오류처리" if state.get("error") else "리포트생성"


# ─────────────────────────────────────────
#  그래프 빌드
# ─────────────────────────────────────────

def build_comparison_graph():
    """
    비교 파이프라인 StateGraph를 빌드·컴파일해 반환.

    router.py의 run_comparison()이 싱글톤으로 캐싱한다.
    """
    graph = StateGraph(ComparisonState)

    graph.add_node("입력정규화", normalize_input_node)
    graph.add_node("비교실행",   compare_node)
    graph.add_node("리포트생성", report_node)
    graph.add_node("오류처리",   error_handler_node)

    graph.set_entry_point("입력정규화")

    graph.add_conditional_edges(
        "입력정규화",
        _route_after_normalize,
        {"비교실행": "비교실행", "오류처리": "오류처리"},
    )
    graph.add_conditional_edges(
        "비교실행",
        _route_after_compare,
        {"리포트생성": "리포트생성", "오류처리": "오류처리"},
    )
    graph.add_edge("리포트생성", END)
    graph.add_edge("오류처리",   END)

    return graph.compile()
