"""
DeepAgent 부동산 감정평가 — 심층 분석 통합 노드
LangGraph 노드로 사용: 실거래가 API + RAG + 캐시를 한 번에 실행

이 모듈이 agents.py의 각 에이전트에서 호출됩니다.
"""

from __future__ import annotations

from cache_db import cached_api_call, get_lawd_code, init_cache_db
from price_engine import fetch_real_transaction_prices
from rag_pipeline import run_rag_pipeline


def deep_analysis_node(state: dict) -> dict:
    """
    LangGraph 심층 분석 통합 노드.

    흐름:
      1. PostgreSQL 캐시 확인 → 있으면 API 스킵
      2. 국토부 실거래가 API 호출
      3. 결과를 RAG 파이프라인에 전달
      4. rag_top_matches + price_data를 state에 저장
    """
    intent = state.get("intent")
    if not intent:
        return {**state, "error": "deep_analysis: intent 없음"}

    # 지역코드: 지오코딩 시군구코드 우선 (전국 지원) → 지역명 테이블 폴백
    geo    = state.get("geocoding_result") or {}
    region = geo.get("region_2depth", "") if isinstance(geo, dict) else ""
    lawd   = (geo.get("sigungu_cd", "")[:5] if isinstance(geo, dict) else "") or get_lawd_code(region)

    if not lawd:
        print(f"[deep_analysis] '{region}' 지역코드 없음 — 더미 데이터 사용")

    # ── 1. 실거래가 API (캐시 우선) ──
    price_data = cached_api_call(
        func=fetch_real_transaction_prices,
        namespace="molit",
        ttl=86400,   # 24시간
        category=intent.category,
        region_2depth=region,
        lawd_code=lawd,
    )

    state["price_data"] = price_data
    print(f"[deep_analysis] 시세: 평균 {price_data.get('avg', 0):,}만원 "
          f"({price_data.get('count', 0)}건)")

    # ── 2. RAG 파이프라인 ──
    state = run_rag_pipeline(state, price_data)

    return state


# pgvector 없이 테스트할 수 있는 경량 버전
def deep_analysis_lite(state: dict) -> dict:
    """
    pgvector 없이 실거래가 API + 캐시만 사용하는 경량 버전.
    RAG 없이 빠르게 시세 데이터만 가져올 때 사용.
    """
    intent = state.get("intent")
    if not intent:
        return state

    geo    = state.get("geocoding_result") or {}
    region = geo.get("region_2depth", "") if isinstance(geo, dict) else ""
    lawd   = (geo.get("sigungu_cd", "")[:5] if isinstance(geo, dict) else "") or get_lawd_code(region)

    price_data = cached_api_call(
        func=fetch_real_transaction_prices,
        namespace="molit",
        ttl=86400,
        category=intent.category,
        region_2depth=region,
        lawd_code=lawd,
    )

    state["price_data"]     = price_data
    state["rag_top_matches"] = []
    state["rag_query"]       = ""
    state["rag_match_count"] = 0
    return state


if __name__ == "__main__":
    init_cache_db()
    print("심층 분석 노드 준비 완료")
    print("  full : deep_analysis_node  (pgvector + RAG 필요)")
    print("  lite : deep_analysis_lite  (캐시 + API만)")
