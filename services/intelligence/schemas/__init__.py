"""
schemas — 부동산 의사결정 서비스 공통 데이터 모델
"""

from schemas.appraisal_result import AppraisalResult, ComparableTransaction
from schemas.comparison import ComparisonInput, ComparisonResult, PropertyComparisonRow
from schemas.property_listing import PropertyListing
from schemas.property_query import PropertyQuery
from schemas.recommendation_result import RecommendationResult
from schemas.report import (
    AppraisalReport,
    ComparisonReport,
    RecommendationReport,
    SimulationReport,
)
from schemas.simulation import (
    AcquisitionCost,
    CashFlowSummary,
    LoanSummary,
    ScenarioResult,
    SimulationInput,
    SimulationResult,
)

__all__ = [
    "PropertyQuery",
    "ComparableTransaction",
    "AppraisalResult",
    "PropertyListing",
    "RecommendationResult",
    "SimulationInput",
    "SimulationResult",
    "AcquisitionCost",
    "LoanSummary",
    "CashFlowSummary",
    "ScenarioResult",
    "ComparisonInput",
    "ComparisonResult",
    "PropertyComparisonRow",
    "AppraisalReport",
    "RecommendationReport",
    "SimulationReport",
    "ComparisonReport",
]
