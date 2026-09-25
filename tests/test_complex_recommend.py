"""
test_complex_recommend.py — 실거래 기반 단지 추천 단위 테스트 (네트워크 목킹)
"""

from __future__ import annotations

import pytest

import services.complex_recommend_service as crs


def _sample(name, price, area, dong="교동", year="2015", ym=("2026", "5")):
    return {
        "apt_name": name, "price": price, "area_sqm": area,
        "per_sqm": round(price / area), "dong": dong, "year_built": year,
        "deal_year": ym[0], "deal_month": ym[1],
        "floor": "10",
    }


MOCK_SAMPLES = (
    [_sample("A단지", 30000, 84.9) for _ in range(6)]
    + [_sample("B단지", 45000, 84.5, year="2021") for _ in range(3)]
    + [_sample("C단지", 20000, 59.8, year="2001") for _ in range(12)]
    + [_sample("원룸빌", 8000, 25.0)]                     # 1건 → 최소 건수 미달 제외
)


@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setattr(crs, "enrich_complex_addresses", lambda *args: None)
    monkeypatch.setattr(crs, "_load_samples", lambda lawd, months: list(MOCK_SAMPLES))
    monkeypatch.setattr(crs, "get_lawd_code", lambda r: "51110" if r == "춘천시" else "")
    # 시점수정 통과 (계수 1.0)
    monkeypatch.setattr(crs, "_apply_time_adjustment",
                        lambda s, cat, as_of, region: (s, 0.003))
    return crs


def test_unknown_region_error(mocked):
    r = mocked.recommend_complexes("없는곳")
    assert r["error"] and not r["results"]


def test_aggregation_and_ranking(mocked):
    r = mocked.recommend_complexes("춘천시", limit=5)
    assert not r["error"]
    names = [c["complex_name"] for c in r["results"]]
    assert "원룸빌" not in names            # 1건 단지 제외
    assert len(names) == 3
    scores = [c["score"] for c in r["results"]]
    assert scores == sorted(scores, reverse=True)


def test_budget_filter(mocked):
    r = mocked.recommend_complexes("춘천시", budget_max=25000)
    names = [c["complex_name"] for c in r["results"]]
    assert names == ["C단지"]              # 2억 이하는 C단지뿐 (상한 +10% 완충)


def test_area_filter(mocked):
    r = mocked.recommend_complexes("춘천시", area_m2=84.0)
    names = [c["complex_name"] for c in r["results"]]
    assert "C단지" not in names            # 59㎡ 단지 제외
    assert set(names) == {"A단지", "B단지"}


def test_stats_fields(mocked):
    r = mocked.recommend_complexes("춘천시")
    assert r["region_avg_per_sqm"] > 0
    c = next(x for x in r["results"] if x["complex_name"] == "C단지")
    assert c["deal_count"] == 12
    assert c["avg_price"] == 20000
    assert c["build_year"] == 2001
    assert "실거래" in r["report"]


def test_liquidity_reason(mocked):
    r = mocked.recommend_complexes("춘천시")
    c = next(x for x in r["results"] if x["complex_name"] == "C단지")
    assert any("유동성" in reason for reason in c["reasons"])
