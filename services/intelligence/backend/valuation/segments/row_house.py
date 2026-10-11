"""연립·다세대(R-RH) 비교사례 단계. 가격 모델(CatBoost 등)을 import하지 않는다.

빌라는 아파트처럼 같은 단지 거래가 충분하지 않다. 그래서 근거를 단계로 나눈다.
- L1: 같은 건물(법정동+지번)의 이전 거래
- L2: 같은 법정동의 준공연도·면적이 비슷한 이전 거래
- L3: 위 근거가 없음(통계 보정만 가능)
모든 근거는 대상 거래일 **이전** 거래만 쓰고 대상 자신은 제외한다. 평가와 운영이 같은 규칙을 써야 누수가 없다.
금액은 원, 면적은 ㎡. 가격 비교는 ㎡당 가격의 로그로 한다.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

L1_DAYS = 730          # 같은 건물: 최근 24개월
L2_DAYS = 365          # 유사 물건: 최근 12개월
L2_AREA_TOLERANCE = .20
L2_YEAR_TOLERANCE = 5
L2_MIN_COUNT = 3
INDEX_WINDOW = 3       # 시점 지수: 최근 3개월 중앙값
BLOCK_AREA_TOLERANCE = .30  # 같은 번지 블록: 본번이 같은 인접 필지


@dataclass(frozen=True)
class Trade:
    id: int
    lawd: str
    dong: str
    jibun: str
    day: date
    floor: int | None
    area: float
    price: int            # 원
    year_built: int | None
    land_area: float | None
    house_type: str
    direct: bool

    @property
    def building(self) -> str:
        return f"{self.lawd}|{self.dong}|{self.jibun}"

    @property
    def block(self) -> str:
        # 큰 필지를 나눈 빌라 블록은 본번을 공유하는 경우가 많다. 좌표 없이 쓰는 위치 근접 대리 변수다.
        main = self.jibun.removeprefix("산").split("-")[0].strip()
        return f"{self.lawd}|{self.dong}|{main}"

    @property
    def log_per_sqm(self) -> float:
        return math.log(self.price / self.area)


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize(rows: list[dict]) -> list[Trade]:
    """저장 실거래 행을 비교용으로 정리한다. 해제·날짜/면적/가격 누락·지번 없음·중복 신고는 제외한다."""
    seen, out = set(), []
    for row in rows:
        if row.get("is_cancelled"):
            continue
        year, month, day = _int(row.get("deal_year")), _int(row.get("deal_month")), _int(row.get("deal_day"))
        area, price = row.get("area_sqm") or 0, row.get("price") or 0
        jibun = (row.get("jibun") or "").strip()
        if not (year and month and day) or area <= 0 or price <= 0 or not jibun:
            continue
        try:
            when = date(year, month, day)
        except ValueError:
            continue
        floor = _int(row.get("floor"))
        trade = Trade(id=int(row["id"]), lawd=str(row["lawd_cd"]), dong=(row.get("dong") or "").strip(), jibun=jibun,
                      day=when, floor=floor, area=float(area), price=int(price) * 10_000,  # 국토부 금액은 만원 단위
                      year_built=_int(row.get("year_built")), land_area=row.get("land_area_sqm"),
                      house_type=(row.get("building_use") or "").strip() or "미상", direct=row.get("transaction_type") == "직거래")
        identity = (trade.building, trade.day, trade.floor, trade.area, trade.price)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(trade)
    out.sort(key=lambda t: (t.day, t.id))
    return out


def _month(day: date) -> int:
    return day.year * 12 + day.month - 1


class MarketIndex:
    """시군구별 ㎡당 가격(로그) 중앙값의 월별 지수. 대상 월은 쓰지 않고 그 이전 달까지만 쓴다."""

    def __init__(self, trades: list[Trade]):
        by = defaultdict(lambda: defaultdict(list))
        for t in trades:
            by[t.lawd][_month(t.day)].append(t.log_per_sqm)
        self._level: dict[str, dict[int, float]] = {}
        for lawd, months in by.items():
            level, ordered = {}, sorted(months)
            for m in range(ordered[0], ordered[-1] + 1):
                window = [v for k in range(m - INDEX_WINDOW + 1, m + 1) for v in months.get(k, [])]
                if len(window) >= 20:
                    level[m] = median(window)
            self._level[lawd] = level

    def at(self, lawd: str, month: int) -> float | None:
        level = self._level.get(lawd, {})
        for m in range(month, month - 12, -1):
            if m in level:
                return level[m]
        return None

    def adjust(self, lawd: str, from_day: date, to_day: date) -> float:
        """from_day 거래를 to_day 시점으로 옮기는 로그 보정값. 대상 월은 쓰지 않고 직전 달 지수를 쓴다."""
        a, b = self.at(lawd, _month(from_day)), self.at(lawd, _month(to_day) - 1)
        return 0.0 if a is None or b is None else b - a


@dataclass
class Evidence:
    level: str                 # L1 / L2 / L3
    estimate: float | None     # 시점 보정한 ㎡당 가격 로그
    l1_count: int
    l1_median: float | None
    l1_area_gap: float | None
    l1_days: int | None
    l2_count: int
    l2_median: float | None
    block_count: int
    block_median: float | None
    basis: str


class ComparableIndex:
    """같은 건물·같은 동의 이전 거래를 빠르게 찾기 위한 색인."""

    def __init__(self, trades: list[Trade], index: MarketIndex):
        self.index = index
        self.by_building: dict[str, list[Trade]] = defaultdict(list)
        self.by_dong: dict[str, list[Trade]] = defaultdict(list)
        self.by_block: dict[str, list[Trade]] = defaultdict(list)
        for t in trades:
            self.by_building[t.building].append(t)
            self.by_block[t.block].append(t)
            self.by_dong[f"{t.lawd}|{t.dong}"].append(t)
        self._dong_days = {key: [t.day for t in rows] for key, rows in self.by_dong.items()}

    def evidence(self, target: Trade, as_of: date | None = None) -> Evidence:
        """as_of(기본: 대상 거래일) **이전** 거래만 근거로 쓴다."""
        cutoff = as_of or target.day
        l1 = [t for t in self.by_building.get(target.building, [])
              if t.id != target.id and t.day < cutoff and t.day >= cutoff - timedelta(days=L1_DAYS)]
        def adjusted(t: Trade) -> float:
            return t.log_per_sqm + self.index.adjust(t.lawd, t.day, cutoff)
        l1_values = [adjusted(t) for t in l1]
        l1_median = median(l1_values) if l1_values else None
        nearest = min(l1, key=lambda t: abs(t.area / target.area - 1), default=None)
        key = f"{target.lawd}|{target.dong}"
        rows, days = self.by_dong.get(key, []), self._dong_days.get(key, [])
        start = bisect_left(days, cutoff - timedelta(days=L2_DAYS))
        stop = bisect_left(days, cutoff)
        l2 = [t for t in rows[start:stop] if t.id != target.id and t.building != target.building
              and abs(t.area / target.area - 1) <= L2_AREA_TOLERANCE
              and (target.year_built is None or t.year_built is None or abs(t.year_built - target.year_built) <= L2_YEAR_TOLERANCE)]
        block = [t for t in self.by_block.get(target.block, []) if t.id != target.id and t.building != target.building
                 and cutoff - timedelta(days=L2_DAYS) <= t.day < cutoff and abs(t.area / target.area - 1) <= BLOCK_AREA_TOLERANCE]
        block_values = [adjusted(t) for t in block]
        l2_values = [adjusted(t) for t in l2]
        l2_median = median(l2_values) if len(l2_values) >= L2_MIN_COUNT else None
        if l1_median is not None:
            level, estimate = "L1", l1_median
            basis = f"같은 건물 최근 {len(l1)}건(24개월) ㎡당 중앙값을 시점 보정"
        elif l2_median is not None:
            level, estimate = "L2", l2_median
            basis = f"같은 동 준공 ±{L2_YEAR_TOLERANCE}년·면적 ±{int(L2_AREA_TOLERANCE*100)}% 최근 {len(l2)}건(12개월) ㎡당 중앙값을 시점 보정"
        else:
            level, estimate, basis = "L3", None, "같은 건물·유사 물건의 최근 거래 없음"
        return Evidence(level=level, estimate=estimate, l1_count=len(l1), l1_median=l1_median,
                        l1_area_gap=None if nearest is None else abs(nearest.area / target.area - 1),
                        l1_days=None if nearest is None else (cutoff - max(t.day for t in l1)).days,
                        l2_count=len(l2), l2_median=l2_median, block_count=len(block),
                        block_median=median(block_values) if block_values else None, basis=basis)
