"""비교사례 단계와 시점 지수. 가격 모델과 분리해 근거 단계(L1~L3)와 근거 문장을 만든다.

- L1: 같은 건물(법정동+지번)의 기준일 이전 24개월 거래
- L2: 같은 법정동, 준공 ±5년, 전용면적 ±20%의 기준일 이전 12개월 거래 3건 이상
- L3: 위 근거 없음
근거는 항상 기준일(평가 대상 거래일 또는 산출 기준일) **이전** 거래만 쓰고 대상 자신은 제외한다.
금액은 원, 면적은 ㎡, 비교는 ㎡당 가격의 자연로그로 한다.
"""
from __future__ import annotations

import csv
import math
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import median

L1_DAYS, L2_DAYS = 730, 365
L2_AREA_TOLERANCE, L2_YEAR_TOLERANCE, L2_MIN_COUNT = .20, 5, 3
BLOCK_AREA_TOLERANCE = .30
INDEX_WINDOW = 3


@dataclass(frozen=True)
class Trade:
    id: int
    lawd: str
    dong: str
    jibun: str
    day: date
    floor: int | None
    area: float
    price: int
    year_built: int | None
    land_area: float | None
    house_type: str
    direct: bool
    name: str = ""

    @property
    def building(self) -> str:
        return f"{self.lawd}|{self.dong}|{self.jibun}"

    @property
    def block(self) -> str:
        # 큰 필지를 나눈 빌라 블록은 본번을 공유하는 경우가 많다. 좌표 없이 쓰는 위치 근접 대리 변수다.
        return f"{self.lawd}|{self.dong}|{self.jibun.removeprefix('산').split('-')[0].strip()}"

    @property
    def log_per_sqm(self) -> float:
        return math.log(self.price / self.area)


def to_int(value) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def to_float(value) -> float | None:
    try:
        number = float(str(value).strip())
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def normalize_jibun(value: str) -> str:
    """'123-0', '0123-0045', ' 123 - 45 ' 같은 표기를 '123', '123-45'로 맞춘다."""
    text = str(value or "").replace(" ", "").strip()
    mountain = text.startswith("산")
    text = text.removeprefix("산")
    if "-" in text:
        main, sub = text.split("-", 1)
    else:
        main, sub = text, ""
    main, sub = main.lstrip("0") or "0", sub.lstrip("0")
    return ("산" if mountain else "") + main + (f"-{sub}" if sub and sub != "0" else "")


def load_trades(path: Path) -> list[Trade]:
    """수집 CSV를 읽는다. 해제·날짜/면적/가격/지번 누락·중복 신고는 제외한다."""
    seen, out = set(), []
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["cancelled"] == "1":
                continue
            y, m, d = to_int(row["deal_year"]), to_int(row["deal_month"]), to_int(row["deal_day"])
            area, price, jibun = to_float(row["area_m2"]), to_int(row["price_manwon"]), normalize_jibun(row["jibun"])
            if not (y and m and d and area and price and jibun):
                continue
            try:
                day = date(y, m, d)
            except ValueError:
                continue
            trade = Trade(id=int(row["id"]), lawd=row["sigungu_code"], dong=row["dong"].strip(), jibun=jibun, day=day,
                          floor=to_int(row["floor"]), area=area, price=price * 10_000,  # 신고 금액은 만원 단위
                          year_built=to_int(row["build_year"]), land_area=to_float(row["land_area_m2"]),
                          house_type=row["house_type"].strip() or "미상", direct=row["deal_type"].strip() == "직거래",
                          name=row.get("building_name", "").strip())
            identity = (trade.building, trade.day, trade.floor, trade.area, trade.price)
            if identity in seen:
                continue
            seen.add(identity)
            out.append(trade)
    out.sort(key=lambda t: (t.day, t.id))
    return out


def month_of(day: date) -> int:
    return day.year * 12 + day.month - 1


class MarketIndex:
    """시군구별 ㎡당 가격(로그) 최근 3개월 중앙값 지수. 기준 월은 쓰지 않고 그 이전 달까지만 쓴다."""

    def __init__(self, trades: list[Trade]):
        by = defaultdict(lambda: defaultdict(list))
        for t in trades:
            by[t.lawd][month_of(t.day)].append(t.log_per_sqm)
        self.level: dict[str, dict[int, float]] = {}
        for lawd, months in by.items():
            ordered, level = sorted(months), {}
            for m in range(ordered[0], ordered[-1] + 1):
                window = [v for k in range(m - INDEX_WINDOW + 1, m + 1) for v in months.get(k, [])]
                if len(window) >= 20:
                    level[m] = median(window)
            self.level[lawd] = level

    def at(self, lawd: str, month: int) -> float | None:
        level = self.level.get(lawd, {})
        for m in range(month, month - 12, -1):
            if m in level:
                return level[m]
        return None

    def adjust(self, lawd: str, from_day: date, to_day: date) -> float:
        a, b = self.at(lawd, month_of(from_day)), self.at(lawd, month_of(to_day) - 1)
        return 0.0 if a is None or b is None else b - a


@dataclass
class Evidence:
    level: str
    estimate: float | None
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
    def __init__(self, trades: list[Trade], index: MarketIndex):
        self.index = index
        self.by_building, self.by_dong, self.by_block = defaultdict(list), defaultdict(list), defaultdict(list)
        for t in trades:
            self.by_building[t.building].append(t)
            self.by_dong[f"{t.lawd}|{t.dong}"].append(t)
            self.by_block[t.block].append(t)
        self.dong_days = {key: [t.day for t in rows] for key, rows in self.by_dong.items()}

    def building_trades(self, lawd: str, dong: str, jibun: str) -> list[Trade]:
        return self.by_building.get(f"{lawd}|{dong}|{jibun}", [])

    def evidence(self, target: Trade, cutoff: date) -> Evidence:
        """cutoff **이전** 거래만 쓴다. 평가에서는 대상 거래일, 산출에서는 산출 기준일 다음 날이다."""
        adjusted = lambda t: t.log_per_sqm + self.index.adjust(t.lawd, t.day, cutoff)
        l1 = [t for t in self.by_building.get(target.building, [])
              if t.id != target.id and cutoff - timedelta(days=L1_DAYS) <= t.day < cutoff]
        l1_values = [adjusted(t) for t in l1]
        l1_median = median(l1_values) if l1_values else None
        nearest = min(l1, key=lambda t: abs(t.area / target.area - 1), default=None)
        key = f"{target.lawd}|{target.dong}"
        rows, days = self.by_dong.get(key, []), self.dong_days.get(key, [])
        window = rows[bisect_left(days, cutoff - timedelta(days=L2_DAYS)):bisect_left(days, cutoff)]
        l2 = [t for t in window if t.id != target.id and t.building != target.building
              and abs(t.area / target.area - 1) <= L2_AREA_TOLERANCE
              and (target.year_built is None or t.year_built is None or abs(t.year_built - target.year_built) <= L2_YEAR_TOLERANCE)]
        l2_values = [adjusted(t) for t in l2]
        l2_median = median(l2_values) if len(l2_values) >= L2_MIN_COUNT else None
        block = [t for t in self.by_block.get(target.block, []) if t.id != target.id and t.building != target.building
                 and cutoff - timedelta(days=L2_DAYS) <= t.day < cutoff and abs(t.area / target.area - 1) <= BLOCK_AREA_TOLERANCE]
        block_values = [adjusted(t) for t in block]
        if l1_median is not None:
            level, estimate = "L1", l1_median
            basis = f"같은 건물 최근 24개월 {len(l1)}건 ㎡당 중앙값(시점 보정)"
        elif l2_median is not None:
            level, estimate = "L2", l2_median
            basis = f"같은 동 준공±{L2_YEAR_TOLERANCE}년·면적±{int(L2_AREA_TOLERANCE * 100)}% 최근 12개월 {len(l2)}건 ㎡당 중앙값(시점 보정)"
        else:
            level, estimate, basis = "L3", None, "같은 건물·유사 물건의 최근 거래 없음"
        return Evidence(level, estimate, len(l1), l1_median,
                        None if nearest is None else abs(nearest.area / target.area - 1),
                        None if not l1 else (cutoff - max(t.day for t in l1)).days,
                        len(l2), l2_median, len(block), median(block_values) if block_values else None, basis)
