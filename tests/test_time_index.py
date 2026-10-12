"""시점 보정 지수: 단지 구성 변화에 흔들리지 않는지, cutoff 이후 거래를 쓰지 않는지, 운영 재현 계수가 공표 시차를 지키는지."""
import math
from datetime import date

from backend.valuation.segments.apartment import Trade
from backend.valuation.time_index import ChainIndex, month_index
from evaluation.time_index_eval import APPROX_RATE, _reb_factor


def _trade(i, complex_name, day, per_sqm, area=84.9):
    return Trade(id=i, lawd="11650", dong="반포동", complex=complex_name, day=day, floor=10, area=area,
                 price=int(per_sqm * area), year_built=2010, direct=False)


def _market(months=8, growth=.01, shift_mix=False):
    trades, i = [], 0
    for m in range(months):
        day = date(2025, m + 1, 10)
        for c, base in (("비싼", 60_000_000), ("싼", 20_000_000)):
            # 뒤로 갈수록 비싼 단지 거래만 늘면 단순 중앙값은 가격 상승처럼 보인다.
            count = 30 if not shift_mix else (10 if c == "비싼" and m < 4 else 50 if c == "비싼" else 30)
            for k in range(count):
                trades.append(_trade(i, c, day, base * math.exp(growth * m) * (1 + (k % 5 - 2) * .005))); i += 1
    return trades


def test_chain_index_tracks_within_complex_growth_not_mix():
    trades = _market(shift_mix=True)
    index = ChainIndex(trades, cutoff_month=month_index(date(2025, 9, 1)))
    level = index.level["11650"]
    steps = [level[m + 1] - level[m] for m in sorted(level)[:-1]]
    assert all(abs(s - .01) < .004 for s in steps)  # 구성 변화가 아니라 단지 내 월 1% 상승을 잡는다


def test_chain_index_ignores_trades_from_cutoff_month_and_extrapolates_only_when_asked():
    trades = _market(months=8)
    cutoff = month_index(date(2025, 7, 1))
    index = ChainIndex(trades, cutoff_month=cutoff)
    assert max(index.level["11650"]) == cutoff - 1
    later = date(2025, 8, 15)
    assert index.adjust("11650", date(2025, 6, 15), later, extrapolate=False) == 0.0
    assert abs(index.adjust("11650", date(2025, 6, 15), later, extrapolate=True) - .02) < .005


def test_reb_factor_respects_publication_lag_then_uses_fixed_rate_or_trend():
    m = lambda y, mo: y * 12 + mo - 1
    levels = {m(2026, k): 100 * 1.01 ** k for k in range(1, 10)}
    early = _reb_factor(levels, date(2026, 3, 5), date(2026, 8, 10), trend=False)   # 8월 10일: 6월까지 공표
    assert abs(early - (levels[m(2026, 6)] / levels[m(2026, 3)]) * (1 + APPROX_RATE) ** 2) < 1e-9
    trend = _reb_factor(levels, date(2026, 3, 5), date(2026, 8, 10), trend=True)
    assert abs(trend - (levels[m(2026, 6)] / levels[m(2026, 3)]) * 1.01 ** 2) < 1e-6
    assert _reb_factor(levels, date(2026, 7, 2), date(2026, 8, 20), trend=False) == (1 + APPROX_RATE) ** 1
