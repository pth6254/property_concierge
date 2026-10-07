"""
test_price_analysis_service.py — services.price_analysis_service.analyze_price 단위 테스트

fetch_real_transaction_prices를 mock해 외부 API 없이 검증.
"""

from unittest.mock import patch

import pytest
from schemas.property_query import PropertyQuery
from services.price_analysis_service import (
    _calc_confidence,
    _collect_warnings,
    _to_comparables,
    _to_manwon,
    _to_won,
    analyze_price,
)


# ─────────────────────────────────────────
#  단위 변환 헬퍼
# ─────────────────────────────────────────

class TestUnitConversion:
    def test_to_won(self):
        assert _to_won(50000) == 500_000_000
        assert _to_won(0) is None
        assert _to_won(None) is None

    def test_to_manwon(self):
        assert _to_manwon(500_000_000) == 50000
        assert _to_manwon(0) is None
        assert _to_manwon(None) is None

    def test_roundtrip(self):
        original = 80000
        assert _to_manwon(_to_won(original)) == original


# ─────────────────────────────────────────
#  신뢰도 계산
# ─────────────────────────────────────────

class TestCalcConfidence:
    """confidence.compute_confidence 위임 후 기대값 (다요인 모델).

    표본(samples)·매칭수준 미제공 시 기본 기반점 0.60에서
    표본 수 가감만 적용된다. 보정테이블은 fixture로 비활성화.
    """

    @pytest.fixture(autouse=True)
    def _no_calibration(self, monkeypatch):
        import confidence
        monkeypatch.setattr(confidence, "CALIBRATION_PATH", "/nonexistent/calib.json")
        monkeypatch.setattr(confidence, "_calibration_cache", None)

    @pytest.mark.parametrize("count,expected_range", [
        (0,  (0.09, 0.11)),   # 데이터 없음 → 바닥
        (1,  (0.41, 0.43)),   # 0.60 − 0.18
        (3,  (0.51, 0.53)),   # 0.60 − 0.08
        (7,  (0.59, 0.61)),   # 0.60
        (12, (0.62, 0.64)),   # 0.60 + 0.03
        (25, (0.64, 0.66)),   # 0.60 + 0.05
    ])
    def test_count_based_confidence(self, count, expected_range):
        data = {"avg": 50000, "count": count}
        c    = _calc_confidence(data)
        assert expected_range[0] <= c <= expected_range[1]

    def test_fallback_source_caps_at_040(self):
        for source in ["공시가격 역산", "수익환원법 사용", "건축원가법 기반"]:
            data = {"avg": 50000, "count": 30, "source": source}
            assert _calc_confidence(data) <= 0.40

    def test_error_returns_010(self):
        data = {"avg": 0, "count": 0, "error": "API 오류"}
        assert _calc_confidence(data) == 0.10

    def test_same_complex_samples_raise_confidence(self):
        """동일 단지 표본 + 낮은 산포 → 기본값보다 높은 신뢰도."""
        samples = [
            {"apt_name": "래미안", "apt_name_matched": "래미안", "per_sqm": 5000, "dong": "반포동"},
            {"apt_name": "래미안", "apt_name_matched": "래미안", "per_sqm": 5100, "dong": "반포동"},
            {"apt_name": "래미안", "apt_name_matched": "래미안", "per_sqm": 4950, "dong": "반포동"},
            {"apt_name": "래미안", "apt_name_matched": "래미안", "per_sqm": 5050, "dong": "반포동"},
            {"apt_name": "래미안", "apt_name_matched": "래미안", "per_sqm": 5020, "dong": "반포동"},
        ]
        data = {"avg": 50000, "count": 5, "samples": samples}
        assert _calc_confidence(data) >= 0.80

    def test_high_dispersion_lowers_confidence(self):
        """같은 조건에서 산포가 크면 신뢰도가 낮아진다."""
        tight = [{"apt_name": "A", "apt_name_matched": "", "per_sqm": v, "dong": "d"}
                 for v in (5000, 5050, 4950, 5020, 5010)]
        wide  = [{"apt_name": "A", "apt_name_matched": "", "per_sqm": v, "dong": "d"}
                 for v in (3000, 7000, 4500, 8000, 2500)]
        c_tight = _calc_confidence({"avg": 50000, "count": 5, "samples": tight})
        c_wide  = _calc_confidence({"avg": 50000, "count": 5, "samples": wide})
        assert c_wide < c_tight


# ─────────────────────────────────────────
#  경고 메시지
# ─────────────────────────────────────────

class TestCollectWarnings:
    def test_no_transaction_data(self):
        warnings = _collect_warnings({"avg": 0, "count": 0}, area_m2=84.0)
        assert any("실거래 데이터 없음" in w for w in warnings)

    def test_few_samples_warning(self):
        warnings = _collect_warnings({"avg": 50000, "count": 3}, area_m2=84.0)
        assert any("표본 부족" in w or "미만" in w for w in warnings)

    def test_no_area_warning(self):
        warnings = _collect_warnings({"avg": 50000, "count": 10}, area_m2=None)
        assert any("면적" in w for w in warnings)

    def test_no_warnings_for_good_data(self):
        warnings = _collect_warnings({"avg": 50000, "count": 20, "used_months": 3}, area_m2=84.0)
        assert len(warnings) == 0

    def test_extended_months_warning(self):
        warnings = _collect_warnings({"avg": 50000, "count": 8, "used_months": 6}, area_m2=84.0)
        assert any("6개월" in w for w in warnings)


# ─────────────────────────────────────────
#  _to_comparables
# ─────────────────────────────────────────

class TestToComparables:
    def _sample(self, apt_name="래미안", price=50000, area=84.0, dong="아현동"):
        return {
            "apt_name":    apt_name,
            "price":       price,
            "area_sqm":    area,
            "per_sqm":     round(price / area),
            "dong":        dong,
            "deal_year":   "2025",
            "deal_month":  "3",
        }

    def test_basic_conversion(self):
        price_data = {"samples": [self._sample()]}
        comps      = _to_comparables(price_data, "래미안")
        assert len(comps) == 1
        assert comps[0].deal_price == 50000 * 10_000    # 만원 → 원
        assert comps[0].deal_date  == "2025-03"

    def test_match_level_same_complex(self):
        price_data = {"samples": [self._sample(apt_name="래미안")]}
        comps      = _to_comparables(price_data, "래미안")
        assert comps[0].match_level == "same_complex"

    def test_match_level_same_dong(self):
        sample = {**self._sample(apt_name="다른단지", dong="아현동"), "query_sigungu_code": "11440"}
        price_data = {"samples": [sample], "target_dong": "아현동", "target_sigungu_code": "11440"}
        comps      = _to_comparables(price_data, "래미안")
        assert comps[0].match_level == "same_dong"

    def test_match_level_same_gu(self):
        sample = {**self._sample(apt_name="다른단지", dong="신촌동"), "query_sigungu_code": "11440"}
        price_data = {"samples": [sample], "target_dong": "아현동", "target_sigungu_code": "11440"}
        comps      = _to_comparables(price_data, "래미안")
        assert comps[0].match_level == "same_gu"

    def test_dong_name_alone_does_not_prove_matching(self):
        comp = _to_comparables({"samples": [self._sample(apt_name="다른단지")]}, "")[0]
        assert comp.match_level == "fallback"

    def test_same_name_in_other_district_is_not_same_complex(self):
        sample = {**self._sample(), "bjdong_code": "1111000000"}
        comp = _to_comparables({"samples": [sample], "target_sigungu_code": "11440"}, "래미안")[0]
        assert comp.match_level == "nearby"

    def test_empty_samples(self):
        comps = _to_comparables({"samples": []}, "")
        assert comps == []


def test_district_fallback_never_claims_first_complex(monkeypatch):
    import price_engine as engine
    from confidence import dominant_match_level
    monkeypatch.setattr(engine, "MOLIT_API_KEY", "isolated-test-key")
    sample = {"apt_name": "다른단지", "dong": "신촌동", "price": 50000,
              "area_sqm": 84.0, "per_sqm": 595, "floor": "5", "deal_year": "2025", "deal_month": "3"}
    monkeypatch.setattr(engine, "_fetch_by_ymds", lambda *args: [dict(sample)])
    monkeypatch.setattr(engine, "_apply_time_adjustment", lambda rows, *args: (rows, 0))
    value = engine.fetch_real_transaction_prices("주거용", "마포구", "아파트", apt_name="없는단지",
                                                region_3depth="아현동", lawd_code="11440")
    assert value["apt_name_matched"] == ""
    comp = _to_comparables(value, value["apt_name_matched"])[0]
    assert comp.match_level == dominant_match_level(value["samples"]) == "same_gu"
    assert comp.region_factor == 0.95


# ─────────────────────────────────────────
#  analyze_price (통합 — fetch mock)
# ─────────────────────────────────────────

MOCK_PRICE_DATA = {
    "avg": 80000, "min": 72000, "max": 88000,
    "count": 5, "per_sqm_avg": 952,
    "samples": [
        {
            "apt_name":   "마포래미안푸르지오",
            "price":      80000,
            "area_sqm":   84.0,
            "per_sqm":    952,
            "dong":       "아현동",
            "deal_year":  "2026",
            "deal_month": "1",
            "deal_day": day,
        }
        for day in range(1, 6)
    ],
    "apt_name_matched": "마포래미안푸르지오",
    "used_months":      3,
    "error":            "",
    "source":           "",
}


class TestAnalyzePrice:
    def _query(self, **kwargs):
        defaults = {
            "intent":        "price_analysis",
            "property_type": "주거용",
            "region":        "마포구",
            "area_m2":       84.0,
            "property_detail": "아파트",
            "address": "서울 마포구 아현동 777",
            "complex_name": "마포래미안푸르지오",
            "appraisal_date": "20260115",
        }
        defaults.update(kwargs)
        return PropertyQuery(**defaults)

    @patch("services.price_analysis_service.fetch_real_transaction_prices",
           return_value=MOCK_PRICE_DATA)
    def test_returns_appraisal_result(self, _mock):
        result = analyze_price(self._query())
        assert result.estimated_price is not None
        assert result.estimated_price > 0

    @patch("services.price_analysis_service.fetch_real_transaction_prices",
           return_value=MOCK_PRICE_DATA)
    def test_price_unit_is_won(self, _mock):
        result = analyze_price(self._query())
        # price_engine 반환은 만원 → 서비스 레이어에서 원으로 변환
        assert result.estimated_price >= 10_000   # 최소 1만원 이상 (원 단위)

    @patch("services.price_analysis_service.fetch_real_transaction_prices",
           return_value=MOCK_PRICE_DATA)
    def test_confidence_reasonable(self, _mock):
        result = analyze_price(self._query())
        assert 0.0 <= result.confidence <= 1.0

    @patch("services.price_analysis_service.fetch_real_transaction_prices",
           return_value=MOCK_PRICE_DATA)
    def test_comparables_populated(self, _mock):
        result = analyze_price(self._query())
        assert len(result.comparables) > 0

    @patch("services.price_analysis_service.fetch_real_transaction_prices",
           return_value=MOCK_PRICE_DATA)
    def test_asking_price_preserved(self, _mock):
        result = analyze_price(self._query(asking_price=900_000_000))
        assert result.asking_price == 900_000_000

    @patch("services.price_analysis_service.fetch_real_transaction_prices",
           return_value=MOCK_PRICE_DATA)
    def test_price_range_consistent(self, _mock):
        """gap_rate(호가 대비 괴리율)는 제거됨 — 추정가 범위 정합성으로 대체."""
        result = analyze_price(self._query(asking_price=900_000_000))
        if result.estimated_price is not None:
            assert result.low_price  <= result.estimated_price
            assert result.high_price >= result.estimated_price

    def test_no_region_returns_analysis_fail(self):
        query  = self._query(region=None)
        result = analyze_price(query)
        assert result.confidence == 0.0
        assert any("region" in w.lower() or "지역" in w for w in result.warnings)

    @patch("services.price_analysis_service.fetch_real_transaction_prices",
           return_value={"avg": 0, "count": 0, "per_sqm_avg": 0,
                         "samples": [], "apt_name_matched": "", "error": "API 오류"})
    def test_empty_price_data_low_confidence(self, _mock):
        result = analyze_price(self._query())
        assert result.confidence <= 0.10
