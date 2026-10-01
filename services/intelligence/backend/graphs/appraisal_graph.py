"""
appraisal_graph.py — 감정평가 LangGraph 파이프라인

router.py에 인라인으로 있던 그래프 빌드 로직을 분리.
라우팅 노드(route_by_category, router_node, error_handler)도 함께 위치.

외부에서는 build_appraisal_graph() 만 호출하면 된다.
"""

from __future__ import annotations

import os
import sys

from langgraph.graph import END, StateGraph

_GRAPHS_DIR   = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_GRAPHS_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from state import AgentState


# ─────────────────────────────────────────
#  카테고리 → 에이전트 매핑
# ─────────────────────────────────────────

CATEGORY_TO_AGENT = {
    "주거용": "residential_agent",
    "상업용": "commercial_agent",
    "업무용": "office_agent",
    "산업용": "industrial_agent",
    "토지":   "land_agent",
}


# ─────────────────────────────────────────
#  라우팅 노드
# ─────────────────────────────────────────

def route_by_category(state: AgentState) -> str:
    if state.get("error") or not state.get("intent"):
        return "error_handler"

    category   = state["intent"].category
    agent_node = CATEGORY_TO_AGENT.get(category)

    if not agent_node:
        print(f"[라우터] ⚠️ 알 수 없는 카테고리 '{category}' → 주거용으로 대체")
        return "residential_agent"

    print(f"[라우터] '{category}' → {agent_node}")
    return agent_node


def router_node(state: AgentState) -> AgentState:
    if state.get("intent"):
        category = state["intent"].category
        state["routed_to"] = CATEGORY_TO_AGENT.get(category, "residential_agent")
    return state


def error_handler(state: AgentState) -> AgentState:
    print(f"[오류] 처리 불가: {state.get('error', '알 수 없는 오류')}")
    return state


# ─────────────────────────────────────────
#  그래프 빌드
# ─────────────────────────────────────────

def build_appraisal_graph():
    """
    감정평가 통합 파이프라인 빌드.

    노드 import를 함수 안에서 처리해 순환 import를 방지.
    router.py의 _get_graph()가 최초 1회 호출한다.
    """
    from intent_agent import intent_analysis_node, validate_node, should_retry
    from geocoding import geocoding_node
    from appraisal_report import report_node
    from deep_analysis import deep_analysis_node
    from agents import (
        residential_agent,
        commercial_agent,
        office_agent,
        industrial_agent,
        land_agent,
    )

    graph = StateGraph(AgentState)

    graph.add_node("의도분석",          intent_analysis_node)
    graph.add_node("검증",              validate_node)
    graph.add_node("지오코딩",          geocoding_node)
    graph.add_node("심층분석",          deep_analysis_node)
    graph.add_node("라우터",            router_node)
    graph.add_node("residential_agent", residential_agent)
    graph.add_node("commercial_agent",  commercial_agent)
    graph.add_node("office_agent",      office_agent)
    graph.add_node("industrial_agent",  industrial_agent)
    graph.add_node("land_agent",        land_agent)
    graph.add_node("감정평가_리포트",   report_node)
    graph.add_node("오류처리",          error_handler)

    graph.set_entry_point("의도분석")
    graph.add_edge("의도분석", "검증")
    graph.add_conditional_edges(
        "검증",
        should_retry,
        {"retry": "의도분석", "end": "지오코딩"},
    )
    graph.add_edge("지오코딩", "심층분석")
    graph.add_edge("심층분석", "라우터")

    graph.add_conditional_edges(
        "라우터",
        route_by_category,
        {
            "residential_agent": "residential_agent",
            "commercial_agent":  "commercial_agent",
            "office_agent":      "office_agent",
            "industrial_agent":  "industrial_agent",
            "land_agent":        "land_agent",
            "error_handler":     "오류처리",
        },
    )

    for node in ["residential_agent", "commercial_agent", "office_agent",
                 "industrial_agent", "land_agent"]:
        graph.add_edge(node, "감정평가_리포트")

    graph.add_edge("감정평가_리포트", END)
    graph.add_edge("오류처리",        END)

    return graph.compile()
