"""
simulation_graph.py — 투자 시뮬레이션 LangGraph 파이프라인

입력 (SimulationState) — 세 가지 방식 중 하나:
  방식 A: raw_input (dict)                → SimulationInput 변환
  방식 B: simulation_input (SimulationInput) → 그대로 사용
  방식 C: listing + listing_overrides     → build_simulation_input_from_listing()

출력 (SimulationState):
  built_input : SimulationInput  — 정규화된 입력 (에코용)
  result      : SimulationResult — 계산 결과
  report      : str              — 마크다운 리포트
  error       : str              — 오류 메시지

노드 흐름:
  입력준비 ──(OK)──▶ 시뮬레이션실행 ──(OK)──▶ 리포트생성 ──▶ END
     └──(오류)──▶ 오류처리 ──▶ END
                              └──(오류)──▶ 오류처리 ──▶ END
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Optional

from typing_extensions import TypedDict
from fastapi import HTTPException
from langgraph.graph import END, StateGraph

_GRAPHS_DIR   = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_GRAPHS_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schemas.simulation import SimulationInput, SimulationResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
#  State
# ─────────────────────────────────────────

class SimulationState(TypedDict, total=False):
    """시뮬레이션 파이프라인 공유 상태"""
    # 입력 — 세 방식 중 하나로 제공
    raw_input:          Optional[dict]             # 방식 A
    simulation_input:   Optional[SimulationInput]  # 방식 B
    listing:            Optional[Any]              # 방식 C
    listing_overrides:  Optional[dict]             # 방식 C 전용 파라미터
    # 처리 결과
    built_input:        Optional[SimulationInput]  # 정규화된 입력
    result:             Optional[SimulationResult] # 계산 결과
    report:             str                        # 마크다운 리포트
    report_output:      Optional[object]           # SimulationReport (구조화 리포트)
    error:              str                        # 오류 메시지


# ─────────────────────────────────────────
#  노드
# ─────────────────────────────────────────

def build_input_node(state: SimulationState) -> SimulationState:
    """
    세 가지 입력 방식을 SimulationInput으로 정규화한다.

    우선순위:
      1. simulation_input — SimulationInput 객체가 이미 있으면 그대로 사용
      2. listing          — PropertyListing/dict + listing_overrides
      3. raw_input        — dict → SimulationInput(**raw_input)
    """
    from services.simulation_service import build_simulation_input_from_listing

    try:
        # 방식 B: 완성된 SimulationInput
        if state.get("simulation_input") is not None:
            inp = state["simulation_input"]
            if not isinstance(inp, SimulationInput):
                return {**state, "error": f"simulation_input 타입 오류: {type(inp).__name__}"}
            logger.debug("[시뮬레이션그래프] 입력준비 — SimulationInput 직접 사용")
            return {**state, "built_input": inp}

        # 방식 C: listing 변환
        if state.get("listing") is not None:
            overrides = state.get("listing_overrides") or {}
            inp = build_simulation_input_from_listing(state["listing"], overrides)
            logger.debug("[시뮬레이션그래프] 입력준비 — listing 변환 완료")
            return {**state, "built_input": inp}

        # 방식 A: dict 변환
        raw = state.get("raw_input")
        if raw is not None:
            if not isinstance(raw, dict):
                return {**state, "error": f"raw_input은 dict여야 합니다: {type(raw).__name__}"}
            inp = SimulationInput(**raw)
            logger.debug("[시뮬레이션그래프] 입력준비 — dict 변환 완료")
            return {**state, "built_input": inp}

        return {
            **state,
            "error": "입력 없음: raw_input, simulation_input, listing 중 하나가 필요합니다.",
        }

    except Exception as exc:
        logger.exception("[시뮬레이션그래프] build_input_node 실패")
        return {**state, "error": f"입력 준비 오류: {exc}"}


def run_simulation_node(state: SimulationState) -> SimulationState:
    """built_input → SimulationResult 계산"""
    from services.simulation_service import run_property_simulation

    inp = state.get("built_input")
    if inp is None:
        return {**state, "error": "built_input이 없습니다."}

    try:
        result = run_property_simulation(inp)
        logger.debug(
            "[시뮬레이션그래프] 시뮬레이션실행 — 매수가 %d, 대출 %d",
            inp.purchase_price, inp.loan_amount,
        )
        return {**state, "result": result}
    except HTTPException:
        # 계산 서비스 장애를 정상 분석 결과로 저장하거나 200 오류 리포트로 감추지 않는다.
        raise
    except Exception as exc:
        logger.exception("[시뮬레이션그래프] run_property_simulation 실패")
        return {**state, "error": f"시뮬레이션 실행 오류: {exc}"}


def report_node(state: SimulationState) -> SimulationState:
    """SimulationResult → 마크다운 리포트 + report_output"""
    from schemas.report import SimulationReport
    from services.simulation_service import generate_simulation_report

    result = state.get("result")
    if result is None:
        return {**state, "error": "result가 없습니다."}

    try:
        inp    = state.get("built_input")
        report = generate_simulation_report(result, inp)
        report_output = SimulationReport(result=result, input=inp, markdown=report)
        return {**state, "report": report, "report_output": report_output}
    except Exception as exc:
        logger.exception("[시뮬레이션그래프] generate_simulation_report 실패")
        return {**state, "error": f"리포트 생성 오류: {exc}", "report": ""}


def error_handler_node(state: SimulationState) -> SimulationState:
    """오류 메시지를 fallback 리포트에 반영한다."""
    msg = state.get("error", "알 수 없는 오류")
    logger.warning("[시뮬레이션그래프] 오류처리: %s", msg)
    if not state.get("report"):
        return {**state, "report": f"# 시뮬레이션 실패\n\n> {msg}"}
    return state


# ─────────────────────────────────────────
#  라우팅 함수
# ─────────────────────────────────────────

def _route_after_build(state: SimulationState) -> str:
    return "오류처리" if state.get("error") else "시뮬레이션실행"


def _route_after_run(state: SimulationState) -> str:
    return "오류처리" if state.get("error") else "리포트생성"


# ─────────────────────────────────────────
#  그래프 빌드
# ─────────────────────────────────────────

def build_simulation_graph():
    """
    시뮬레이션 파이프라인 StateGraph를 빌드·컴파일해 반환.

    외부에서는 build_simulation_graph()만 호출하면 된다.
    router.py의 run_simulation()이 싱글톤으로 캐싱한다.
    """
    graph = StateGraph(SimulationState)

    graph.add_node("입력준비",       build_input_node)
    graph.add_node("시뮬레이션실행", run_simulation_node)
    graph.add_node("리포트생성",     report_node)
    graph.add_node("오류처리",       error_handler_node)

    graph.set_entry_point("입력준비")

    graph.add_conditional_edges(
        "입력준비",
        _route_after_build,
        {"시뮬레이션실행": "시뮬레이션실행", "오류처리": "오류처리"},
    )
    graph.add_conditional_edges(
        "시뮬레이션실행",
        _route_after_run,
        {"리포트생성": "리포트생성", "오류처리": "오류처리"},
    )
    graph.add_edge("리포트생성", END)
    graph.add_edge("오류처리",   END)

    return graph.compile()
