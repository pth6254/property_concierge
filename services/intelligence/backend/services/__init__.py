"""
services — 비즈니스 로직 서비스 레이어

price_analysis_service    : PropertyQuery → AppraisalResult
recommendation_service    : PropertyQuery → list[RecommendationResult]
simulation_service        : SimulationInput | dict → SimulationResult + 마크다운 리포트
comparison_service        : list[PropertyListing] → ComparisonResult + 결정 리포트
"""
