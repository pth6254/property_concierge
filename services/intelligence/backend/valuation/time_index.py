"""실거래 시점 보정 지수.

실거래는 과거 거래라서 비교사례를 기준일 시점으로 옮겨야 한다. 운영 규칙은 부동산원 월간 지수 + 미공표 구간 월 0.3% 고정률을 쓰는데,
급등기에는 고정률 부분이 시장을 따라가지 못한다. 여기서는 저장 실거래만으로 만드는 지수를 둔다.

- ChainIndex: 같은 단지·면적대(10㎡) 칸의 고정효과를 빼고 남은 월별 수준(시간 더미 회귀를 반복 중앙값으로 푼 것).
  구 전체 중앙값(MarketIndex)은 그달 어떤 단지가 거래됐는지에 따라 흔들린다. 같은 칸끼리 비교하면 그 구성 변화가 빠진다.
- 기준일이 마지막 완결 월보다 뒤면 최근 3개월 기울기로 연장할 수 있다(extrapolate=True).
지수는 cutoff 달 **이전의 완결 월** 거래만으로 만든다. 평가와 운영이 같은 규칙을 써야 누수가 없다.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import median


def month_index(day: date) -> int:
    return day.year * 12 + day.month - 1


def fractional_month(day: date) -> float:
    # 월 중간(15일)을 그 달 지수의 위치로 본다.
    return month_index(day) + (day.day - 15) / 30


class ChainIndex:
    """시군구별 단지·면적대 고정효과 월별 지수(로그). cutoff_month 이전 완결 월만 쓴다."""

    def __init__(self, trades, cutoff_month: int, min_cell_trades: int = 2, min_month_trades: int = 20, iterations: int = 6):
        by_lawd = defaultdict(list)
        for t in trades:
            m = month_index(t.day)
            if m < cutoff_month:
                by_lawd[t.lawd].append((f"{t.complex}|{round(t.area / 10)}", m, t.log_per_sqm))
        self.level: dict[str, dict[int, float]] = {}
        for lawd, rows in by_lawd.items():
            counts = defaultdict(int)
            for cell, _, _ in rows:
                counts[cell] += 1
            rows = [r for r in rows if counts[r[0]] >= min_cell_trades]
            months = defaultdict(list)
            for r in rows:
                months[r[1]].append(r)
            usable = {m for m, items in months.items() if len(items) >= min_month_trades}
            rows = [r for r in rows if r[1] in usable]
            if not rows:
                continue
            level = {m: 0.0 for m in usable}
            effect: dict[str, float] = {}
            for _ in range(iterations):
                cells = defaultdict(list)
                for cell, m, value in rows:
                    cells[cell].append(value - level[m])
                effect = {cell: median(values) for cell, values in cells.items()}
                by_month = defaultdict(list)
                for cell, m, value in rows:
                    by_month[m].append(value - effect[cell])
                level = {m: median(values) for m, values in by_month.items()}
            base = level[min(level)]
            self.level[lawd] = {m: v - base for m, v in sorted(level.items())}

    def _slope(self, lawd: str, last: int) -> float:
        level = self.level.get(lawd, {})
        if last in level and last - 3 in level:
            return (level[last] - level[last - 3]) / 3
        return 0.0

    def at(self, lawd: str, when: date, extrapolate: bool) -> float | None:
        level = self.level.get(lawd)
        if not level:
            return None
        m = month_index(when)
        if m in level:
            return level[m]
        last = max(level)
        if m > last:
            gap = fractional_month(when) - last
            return level[last] + (self._slope(lawd, last) * gap if extrapolate else 0.0)
        earlier = [k for k in level if k <= m]
        return level[max(earlier)] if earlier else None

    def adjust(self, lawd: str, from_day: date, to_day: date, extrapolate: bool = False) -> float:
        a, b = self.at(lawd, from_day, extrapolate), self.at(lawd, to_day, extrapolate)
        return 0.0 if a is None or b is None else b - a
