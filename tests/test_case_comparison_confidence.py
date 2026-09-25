"""만료되거나 근거가 약한 시세추정은 후보의 가격상 장점으로 판정하지 않는다."""
from backend.services.case_comparison_service import compare_case_candidates


def test_stale_and_low_confidence_appraisals_do_not_create_price_highlights():
    case = {"id": 1, "title": "검증", "properties": [
        {"id": 1, "name": "만료", "asking_price": 900_000_000, "analyses": [
            {"analysis_type": "appraisal", "status": "stale", "summary": {"estimated_value": 1_000_000_000}}]},
        {"id": 2, "name": "근거 부족", "asking_price": 900_000_000, "analyses": [
            {"analysis_type": "appraisal", "status": "completed", "summary": {
                "estimated_value": 1_000_000_000, "confidence": 0.3, "comparable_count": 1}}]},
    ]}
    stale, weak = compare_case_candidates(case)["rows"]
    for candidate in (stale, weak):
        assert candidate["price_gap_ratio"] is None
        assert "희망가가 추정가 이하" not in candidate["highlights"]
    assert any("신뢰도" in warning for warning in weak["warnings"])
