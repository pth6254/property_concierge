"""
state.py — LangGraph 파이프라인 공유 상태 정의

AgentState는 모든 그래프 노드가 읽고 쓰는 단일 상태 객체.
router.py와 graphs/ 양쪽에서 import하므로 별도 파일로 분리.
"""

from __future__ import annotations

from typing import Optional

from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    """전체 파이프라인 공유 상태"""
    user_input:       str
    building_name:    str
    raw_inputs:       dict           # 사용자가 직접 고른 주소·유형 (LLM 추론과 분리)
    intent:           Optional[object]   # PropertyIntent (순환 import 방지로 object 사용)
    raw_llm_output:   str
    error:            str
    retry_count:      int
    routed_to:        str
    geocoding_result: Optional[dict]
    price_data:       dict
    rag_top_matches:  list
    rag_query:        str
    rag_match_count:  int
    analysis_result:  dict
    final_report:     str
    report_output:    Optional[object]   # AppraisalReport (순환 import 방지로 object 사용)
