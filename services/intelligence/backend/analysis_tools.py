"""
analysis_tools.py — 삭제 완료

이 파일은 더 이상 사용하지 않습니다.
각 심볼의 새 위치:

  ValuationResult, _intent_summary  →  models.py
  fetch_real_transaction_prices      →  price_engine.py
  calc_estimated_value               →  price_engine.py
  calc_valuation_verdict             →  price_engine.py
  calc_investment_return             →  price_engine.py
  calc_cost_approach                 →  price_engine.py
  _fetch_by_income_approach          →  price_engine.py
  generate_appraisal_opinion         →  llm_utils.py
  search_nearby_facilities           →  llm_utils.py
  search_web_tavily                  →  llm_utils.py
"""

raise ImportError(
    "analysis_tools.py는 제거되었습니다. "
    "price_engine / llm_utils / models 에서 직접 import 하세요. "
    "위 docstring에서 새 위치를 확인하세요."
)
