"""
recommendation_graph.py — 매물 추천 LangGraph 파이프라인

입력 : RecommendationState (PropertyQuery + 설정값)
출력 : RecommendationState (results + report 채워진 상태)

노드 흐름:
  쿼리검증 → 추천실행 → 리포트생성 → END
     └─(오류)→ 오류처리 → END
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

from typing_extensions import TypedDict
from langgraph.graph import END, StateGraph

_GRAPHS_DIR   = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_GRAPHS_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schemas.property_query import PropertyQuery
from schemas.recommendation_result import RecommendationResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
#  State
# ─────────────────────────────────────────

class RecommendationState(TypedDict, total=False):
    """추천 파이프라인 공유 상태"""
    query:         PropertyQuery               # 입력 쿼리
    limit:         int                         # 반환 최대 건수
    run_appraisal: bool                        # 감정평가 연동 여부
    results:       list[RecommendationResult]  # 추천 결과
    report:        str                         # 마크다운 리포트
    report_output: Optional[object]            # RecommendationReport (구조화 리포트)
    error:         str                         # 오류 메시지 (있으면 오류처리로 분기)


# ─────────────────────────────────────────
#  노드
# ─────────────────────────────────────────

def validate_query_node(state: RecommendationState) -> RecommendationState:
    """
    쿼리 유효성 검사.
    PropertyQuery 객체 자체는 Pydantic이 검증하므로
    여기서는 추천에 필요한 최소 조건(intent)만 확인한다.
    """
    query = state.get("query")

    if query is None:
        return {**state, "error": "PropertyQuery가 전달되지 않았습니다."}

    if not isinstance(query, PropertyQuery):
        return {**state, "error": f"query 타입 오류: {type(query).__name__}"}

    logger.debug("[추천그래프] 쿼리 검증 완료 — region=%s type=%s",
                 query.region, query.property_type)
    return state


def recommend_node(state: RecommendationState) -> RecommendationState:
    """recommend_listings() 호출 → results 저장"""
    from services.recommendation_service import recommend_listings

    query         = state["query"]
    limit         = state.get("limit", 5)
    run_appraisal = state.get("run_appraisal", False)

    try:
        results = recommend_listings(query, limit=limit, run_appraisal=run_appraisal)
        logger.debug("[추천그래프] 추천 결과 %d건", len(results))
        return {**state, "results": results}
    except Exception as exc:
        logger.exception("[추천그래프] recommend_listings 실패")
        return {**state, "error": f"추천 실행 오류: {exc}", "results": []}


def report_node(state: RecommendationState) -> RecommendationState:
    """format_recommendation_report() 호출 → report + report_output 저장"""
    from schemas.report import RecommendationReport
    from services.recommendation_service import format_recommendation_report

    results = state.get("results", [])
    query   = state["query"]

    try:
        report = format_recommendation_report(results, query)
        report_output = RecommendationReport(results=results, markdown=report)
        return {**state, "report": report, "report_output": report_output}
    except Exception as exc:
        logger.exception("[추천그래프] format_recommendation_report 실패")
        return {**state, "error": f"리포트 생성 오류: {exc}", "report": ""}


def error_handler_node(state: RecommendationState) -> RecommendationState:
    msg = state.get("error", "알 수 없는 오류")
    logger.warning("[추천그래프] 오류처리: %s", msg)
    if not state.get("report"):
        return {**state, "report": f"# 추천 실패\n\n> {msg}"}
    return state


# ─────────────────────────────────────────
#  라우팅 함수
# ─────────────────────────────────────────

def _route_after_validate(state: RecommendationState) -> str:
    return "오류처리" if state.get("error") else "추천실행"


# ─────────────────────────────────────────
#  그래프 빌드
# ─────────────────────────────────────────

def build_recommendation_graph():
    """
    추천 파이프라인 StateGraph를 빌드·컴파일해 반환.

    외부에서는 build_recommendation_graph() 만 호출하면 된다.
    run_recommendation()이 싱글톤으로 캐싱한다.
    """
    graph = StateGraph(RecommendationState)

    graph.add_node("쿼리검증",   validate_query_node)
    graph.add_node("추천실행",   recommend_node)
    graph.add_node("리포트생성", report_node)
    graph.add_node("오류처리",   error_handler_node)

    graph.set_entry_point("쿼리검증")

    graph.add_conditional_edges(
        "쿼리검증",
        _route_after_validate,
        {"추천실행": "추천실행", "오류처리": "오류처리"},
    )
    graph.add_edge("추천실행",   "리포트생성")
    graph.add_edge("리포트생성", END)
    graph.add_edge("오류처리",   END)

    return graph.compile()
