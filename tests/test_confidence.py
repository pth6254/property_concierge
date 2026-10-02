"""
test_confidence.py — AVM 신뢰도 산출 단위 테스트 (보정테이블 비활성 상태)
"""

from __future__ import annotations

import pytest

import confidence as cf


@pytest.fixture(autouse=True)
def _no_calibration(monkeypatch):
    """보정테이블 없이 휴리스틱만 검증 (헤르메틱)."""
    monkeypatch.setattr(cf, "CALIBRATION_PATH", "/nonexistent/calib.json")
    monkeypatch.setattr(cf, "_calibration_cache", None)


def _samples(n, per_sqm_base=5000, spread=50, matched=True, dong="반포동"):
    name = "래미안"
    return [{
        "apt_name": name,
        "apt_name_matched": name if matched else "",
        "per_sqm": per_sqm_base + (i - n // 2) * spread,
        "dong": dong,
        "target_dong": "반포동", "target_sigungu_code": "11650", "query_sigungu_code": "11650",
    } for i in range(n)]


# ─────────────────────────────────────────
#  기본 동작
# ─────────────────────────────────────────

def test_no_data_floor():
    assert cf.compute_confidence(count=0)["score"] == cf.SCORE_FLOOR


def test_same_complex_high():
    r = cf.compute_confidence(count=5, samples=_samples(5))
    assert r["match_level"] == "same_complex"
    assert r["score"] >= 0.80


def test_match_level_ordering():
    """동일단지 > 동일동 > 동일구 > nearby > 폴백."""
    scores = [
        cf.compute_confidence(count=5, match_level=lv)["score"]
        for lv in ("same_complex", "same_dong", "same_gu", "nearby", "fallback")
    ]
    assert scores == sorted(scores, reverse=True)


def test_dispersion_penalty():
    tight = cf.compute_confidence(count=5, samples=_samples(5, spread=30))["score"]
    wide  = cf.compute_confidence(count=5, samples=_samples(5, spread=1500))["score"]
    assert wide < tight


def test_freshness_penalty():
    fresh = cf.compute_confidence(count=5, match_level="same_gu", used_months=3)["score"]
    old   = cf.compute_confidence(count=5, match_level="same_gu", used_months=13)["score"]
    assert old < fresh


def test_fallback_source_cap():
    r = cf.compute_confidence(count=30, source="공시가격 역산")
    assert r["score"] <= 0.40
    assert r["match_level"] == "fallback"


def test_reb_index_bonus():
    base = _samples(5)
    with_reb = [dict(s, time_adj_months=2, time_adj_source="reb_index") for s in base]
    with_apx = [dict(s, time_adj_months=2, time_adj_source="approx") for s in base]
    assert (cf.compute_confidence(count=5, samples=with_reb)["score"]
            > cf.compute_confidence(count=5, samples=with_apx)["score"])


def test_score_bounds():
    for count in (0, 1, 3, 7, 15, 50):
        for lv in ("same_complex", "same_gu", "fallback", ""):
            s = cf.compute_confidence(count=count, match_level=lv)["score"]
            assert cf.SCORE_FLOOR <= s <= cf.SCORE_CAP


# ─────────────────────────────────────────
#  보정테이블 블렌딩
# ─────────────────────────────────────────

def test_calibration_blend(monkeypatch):
    """버킷 실측 hit10이 표본 수 가중으로 블렌딩된다."""
    monkeypatch.setattr(cf, "load_calibration", lambda: {
        "buckets": {"same_complex|n5-9": {"hit10": 0.50, "n": 80}},
    })
    r = cf.compute_confidence(count=5, samples=_samples(5))
    assert r["basis"] == "calibrated"
    # w = 80/100 = 0.8 → 0.5*0.8 + heuristic*0.2 → 휴리스틱(~0.87)보다 실측에 가깝게
    assert 0.50 <= r["score"] <= 0.62


def test_calibration_missing_bucket_falls_back(monkeypatch):
    monkeypatch.setattr(cf, "load_calibration", lambda: {"buckets": {}})
    r = cf.compute_confidence(count=5, samples=_samples(5))
    assert r["basis"] == "heuristic"


# ─────────────────────────────────────────
#  유틸
# ─────────────────────────────────────────

def test_count_band():
    assert cf.count_band(1) == "n1"
    assert cf.count_band(3) == "n2-4"
    assert cf.count_band(7) == "n5-9"
    assert cf.count_band(25) == "n10+"


def test_dominant_match_level():
    assert cf.dominant_match_level(_samples(3)) == "same_complex"
    assert cf.dominant_match_level(_samples(3, matched=False)) == "same_dong"
    assert cf.dominant_match_level(_samples(3, matched=False, dong="")) == "same_gu"
    assert cf.dominant_match_level([]) == ""


def test_unverified_dong_does_not_raise_confidence():
    rows = [{"dong": "반포동", "per_sqm": 5000} for _ in range(5)]
    assert cf.dominant_match_level(rows) == "fallback"
    assert cf.compute_confidence(count=5, samples=rows)["score"] < cf.compute_confidence(count=5, match_level="same_dong")["score"]
