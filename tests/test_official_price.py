"""공동주택 공시가격 변수: 공표 시점 준수, 호실·층 매칭, 같은 기준연도의 비교사례 대비 차이."""
import math
from datetime import date

from backend.valuation.official_price import OfficialPrices, available_year, official_features
from backend.valuation.segments.apartment import Trade


def _prices():
    rows = []
    for year, scale in ((2025, 1.0), (2026, 1.2)):
        for floor in (3, 15, 25):
            for ho in (1, 2):
                rows.append(("P1", year, "101", f"{floor}0{ho}", str(floor), 84.9, int(1_000_000 * 84.9 * scale * (1 + floor / 100))))
        rows.append(("P2", year, "1", "301", "3", 84.0, int(800_000 * 84.0 * scale)))
    return OfficialPrices(rows)


def test_available_year_respects_april_publication():
    assert available_year(date(2026, 4, 30)) == 2025 and available_year(date(2026, 5, 1)) == 2026


def test_year_never_uses_unpublished_future_prices():
    prices = OfficialPrices([("P1", 2026, "", "", "3", 84.9, 1_000_000_000)])
    assert prices.year_for("P1", date(2026, 3, 1)) is None   # 2026년 공시는 5월부터
    assert prices.year_for("P1", date(2026, 6, 1)) == 2026


def test_unit_level_prefers_exact_dong_ho_then_floor_and_area():
    prices = _prices()
    exact = prices.unit_level("P1", 2026, None, 84.9, dong="101동", ho="2502호")
    assert abs(exact - math.log(1_000_000 * 1.2 * 1.25)) < 1e-6
    by_floor = prices.unit_level("P1", 2026, 15, 84.5)
    assert abs(by_floor - math.log(1_000_000 * 1.2 * 1.15)) < 1e-6
    assert prices.unit_level("P1", 2026, 7, 84.9) is None


def test_features_compare_target_and_comps_in_the_same_year():
    prices = _prices()
    comp = Trade(1, "11650", "반포동", "c", date(2025, 12, 1), 3, 84.9, 1, 2010, False, "x")
    pnu_of = lambda t: "P1"
    out = official_features(prices, pnu_of, "P1", date(2026, 7, 1), 25, 84.9, [comp])
    # 25층과 3층의 같은 연도(2026) 공시 차이: log(1.25/1.03)
    assert abs(out["official_gap"] - math.log(1.25 / 1.03)) < 1e-6
    assert out["official_premium"] > 0 and not math.isnan(out["official_level"])
    empty = official_features(None, pnu_of, "P1", date(2026, 7, 1), 25, 84.9, [comp])
    assert all(math.isnan(v) for v in empty.values())
