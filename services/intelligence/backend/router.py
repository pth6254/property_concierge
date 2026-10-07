"""
router.py — 파이프라인 진입점

그래프 빌드 로직은 graphs/appraisal_graph.py 로 이동.
이 파일은 싱글톤 캐시와 공개 API(run_appraisal, run_recommendation,
run_simulation, run_comparison)만 유지.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# 외부 `graphs` 패키지(site-packages)와 충돌하지 않도록 backend/ 와 프로젝트 루트를 sys.path 선두에 삽입
_BACKEND_DIR  = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import find_dotenv, load_dotenv

from backend.graphs.appraisal_graph import build_appraisal_graph
from backend.graphs.comparison_graph import build_comparison_graph
from backend.graphs.recommendation_graph import build_recommendation_graph
from backend.graphs.simulation_graph import build_simulation_graph
from state import AgentState

load_dotenv(find_dotenv())


# ─────────────────────────────────────────
#  API 키 검증 (모듈 임포트 시 1회 실행)
# ─────────────────────────────────────────

def _check_api_keys():
    missing = []
    if not os.getenv("KAKAO_REST_API_KEY"):
        missing.append("KAKAO_REST_API_KEY")
    if not os.getenv("MOLIT_API_KEY"):
        missing.append("MOLIT_API_KEY")
    if not os.getenv("TAVILY_API_KEY"):
        missing.append("TAVILY_API_KEY (선택)")
    if missing:
        print(f"[router] ⚠️  환경변수 미설정: {', '.join(missing)}")

_check_api_keys()


# ─────────────────────────────────────────
#  그래프 싱글톤
# ─────────────────────────────────────────

_graph     = None
_rec_graph = None
_sim_graph = None
_cmp_graph = None


def _get_graph():
    """감정평가 그래프 — 최초 요청 시 compile(), 이후 재사용"""
    global _graph
    if _graph is None:
        print("[router] 감정평가 그래프 컴파일 중...")
        _graph = build_appraisal_graph()
        print("[router] 감정평가 그래프 컴파일 완료")
    return _graph


def _get_rec_graph():
    """추천 그래프 — 최초 요청 시 compile(), 이후 재사용"""
    global _rec_graph
    if _rec_graph is None:
        print("[router] 추천 그래프 컴파일 중...")
        _rec_graph = build_recommendation_graph()
        print("[router] 추천 그래프 컴파일 완료")
    return _rec_graph


def _get_sim_graph():
    """시뮬레이션 그래프 — 최초 요청 시 compile(), 이후 재사용"""
    global _sim_graph
    if _sim_graph is None:
        print("[router] 시뮬레이션 그래프 컴파일 중...")
        _sim_graph = build_simulation_graph()
        print("[router] 시뮬레이션 그래프 컴파일 완료")
    return _sim_graph


def _get_cmp_graph():
    """비교 그래프 — 최초 요청 시 compile(), 이후 재사용"""
    global _cmp_graph
    if _cmp_graph is None:
        print("[router] 비교 그래프 컴파일 중...")
        _cmp_graph = build_comparison_graph()
        print("[router] 비교 그래프 컴파일 완료")
    return _cmp_graph


# ─────────────────────────────────────────
#  공개 실행 인터페이스
# ─────────────────────────────────────────

def run_appraisal(
    user_input: str,
    building_name: str = "",
    appraisal_date: str = "",
    appraisal_purpose: str = "",
    progress_cb=None,
    *,
    address: str = "",
    property_category: str = "",
    property_detail: str = "",
    area_sqm: float | None = None,
    income_valuation: dict | None = None,
    valuation_context: dict | None = None,
) -> dict:
    """
    감정평가(시세추정) 실행 — FastAPI 등 외부에서 호출하는 공개 API.

    Args:
        user_input        : 자연어 요청
        building_name     : 건물명·단지명 (선택)
        appraisal_date    : 기준시점 YYYYMMDD (빈 문자열 = 현재)
        appraisal_purpose : 조회 목적 (담보/경매/과세/매매/보상/임의)
        progress_cb       : 노드 완료마다 호출되는 콜백 fn(node_name: str).
                            None이면 invoke(), 지정 시 stream()으로 실행.
        address           : 사용자가 검색 결과에서 직접 선택한 공식 주소.
        property_category : 사용자가 직접 선택한 5개 부동산 유형.
        property_detail   : 사용자가 직접 선택한 세부 유형.
    """
    text = user_input.strip()

    # 기준시점이 명시된 경우 텍스트에 포함 → NLP가 appraisal_date로 추출
    if appraisal_date:
        try:
            from datetime import datetime as _dt
            d = _dt.strptime(appraisal_date, "%Y%m%d")
            text = text + f" {d.year}년 {d.month}월 {d.day}일 기준"
        except ValueError:
            pass

    initial_state = {
        "user_input":        text,
        "building_name":     building_name.strip(),
        "appraisal_purpose": appraisal_purpose.strip(),
        "raw_inputs": {
            "address": address.strip(),
            "property_category": property_category.strip(),
            "property_detail": property_detail.strip(),
            "area_sqm": area_sqm,
            "appraisal_date": appraisal_date,
            "income_valuation": income_valuation,
            "valuation_context": valuation_context,
        },
        "error":             "",
        "retry_count":       0,
    }

    try:
        from backend.valuation.policy import plan, allowed, blocked_result, finalize
        if property_category:
            initial_state["valuation_plan"] = plan(initial_state)
            if not allowed(initial_state["valuation_plan"]):
                from backend.services.valuation_support import support_report
                return support_report(blocked_result(initial_state, initial_state["valuation_plan"]))
        # 구조화된 요청은 이미 유형과 주소를 사용자가 선택했다. 임대료·필지 조회에 LLM 재해석을 끼우지 않는다.
        if property_category in {"상업용", "업무용", "토지"}:
            from backend.services.valuation_support import analyze_support, support_report
            if progress_cb:
                progress_cb("입력 임대료 계산" if property_category != "토지" else "필지 공개정보 조회")
            return support_report(finalize(analyze_support(initial_state, property_category)))
        graph = _get_graph()
        if progress_cb is None:
            return graph.invoke(initial_state)

        # 진행 콜백 모드: 노드별 부분 상태를 병합하며 완료 노드 통지
        state = dict(initial_state)
        for update in graph.stream(initial_state, stream_mode="updates"):
            for node_name, partial in update.items():
                if isinstance(partial, dict):
                    state.update(partial)
                try:
                    progress_cb(node_name)
                except Exception:
                    pass  # 콜백 오류가 파이프라인을 중단시키지 않도록
        return state
    except Exception as exc:
        logger.exception("[router] run_appraisal 실패")
        return {"error": str(exc), "final_report": f"# 시세추정 실패\n\n> {exc}", "analysis_result": {}}


def run_recommendation(
    query,
    limit: int = 5,
    run_appraisal: bool = False,
) -> dict:
    """
    매물 추천 실행 — Streamlit, FastAPI 등 외부에서 호출하는 공개 API.

    Args:
        query:         PropertyQuery 객체. 필터·예산·면적 조건 포함.
        limit:         반환할 최대 추천 건수 (기본 5).
        run_appraisal: True면 매물별 감정평가 시도
                       (실패해도 추천은 계속, 기본 False).

    Returns:
        RecommendationState dict:
          - results : list[RecommendationResult]  — 점수 내림차순
          - report  : str                         — 마크다운 리포트
          - error   : str                         — 오류 시 메시지
    """
    graph = _get_rec_graph()
    try:
        return graph.invoke({
            "query":         query,
            "limit":         limit,
            "run_appraisal": run_appraisal,
            "error":         "",
        })
    except Exception as exc:
        logger.exception("[router] run_recommendation 실패")
        return {"error": str(exc), "report": f"# 추천 실패\n\n> {exc}", "results": []}


def run_simulation(
    data=None,
    listing=None,
    overrides: Optional[dict] = None,
) -> dict:
    """
    투자 시뮬레이션 실행 — 외부에서 호출하는 공개 API.

    세 가지 입력 방식:
      1. data=dict           : raw_input으로 전달 → 그래프 내에서 SimulationInput 변환
      2. data=SimulationInput: simulation_input으로 전달 → 그대로 사용
      3. listing + overrides : listing 변환 모드 (overrides는 선택)

    Returns:
        SimulationState dict:
          - built_input : SimulationInput  — 정규화된 입력
          - result      : SimulationResult — 계산 결과
          - report      : str              — 마크다운 리포트
          - error       : str              — 오류 시 메시지
    """
    from schemas.simulation import SimulationInput

    graph = _get_sim_graph()
    state: dict = {"report": "", "error": ""}

    if listing is not None:
        state["listing"] = listing
        if overrides:
            state["listing_overrides"] = overrides
    elif isinstance(data, SimulationInput):
        state["simulation_input"] = data
    elif isinstance(data, dict):
        state["raw_input"] = data
    else:
        state["raw_input"] = None  # build_input_node에서 오류 처리

    try:
        return graph.invoke(state)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[router] run_simulation 실패")
        return {"error": str(exc), "report": f"# 시뮬레이션 실패\n\n> {exc}", "result": None}


def run_comparison(
    listings=None,
    recommendation_results=None,
    simulation_results=None,
    data=None,
) -> dict:
    """
    매물 비교 분석 실행 — 외부에서 호출하는 공개 API.

    두 가지 입력 방식:
      1. data=ComparisonInput : 직접 전달
      2. data=dict            : raw_input으로 전달 → 그래프 내에서 변환
      3. listings (+ 선택: recommendation_results, simulation_results)

    Returns:
        ComparisonState dict:
          - result : ComparisonResult — 비교 분석 결과
          - report : str             — 마크다운 결정 리포트
          - error  : str             — 오류 시 메시지
    """
    from schemas.comparison import ComparisonInput

    graph = _get_cmp_graph()
    state: dict = {"report": "", "error": ""}

    if isinstance(data, ComparisonInput):
        state["comparison_input"] = data
    elif isinstance(data, dict):
        state["raw_input"] = data
    elif listings is not None:
        state["comparison_input"] = ComparisonInput(
            listings               = listings,
            recommendation_results = recommendation_results,
            simulation_results     = simulation_results,
        )
    else:
        state["raw_input"] = {}  # normalize_input_node에서 오류 처리

    try:
        return graph.invoke(state)
    except Exception as exc:
        logger.exception("[router] run_comparison 실패")
        return {"error": str(exc), "report": f"# 비교 분석 실패\n\n> {exc}", "result": None}


if __name__ == "__main__":
    model = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
    print(f"모델: {model}")
    print("=" * 60)

    test_cases = [
        ("마포구 아파트 매매 84㎡",      "마포래미안푸르지오"),
        ("서초구 아파트 매매 59㎡",      "반포래미안원베일리"),
        ("강남구 역삼동 상가 매매 50평",  ""),
        ("판교 사무실 매매 100평",        "파르나스타워"),
        ("인천 남동공단 창고 매매 300평", "남동인더스파크"),
        ("양평군 토지 매매 500평",        ""),
    ]

    for query, bname in test_cases:
        print(f"\n입력: {query}")
        if bname:
            print(f"건물명: {bname}")
        print("-" * 60)
        result = run_appraisal(query, bname)
        if result.get("error") and not result.get("analysis_result"):
            print(f"❌ {result['error'][:100]}")
