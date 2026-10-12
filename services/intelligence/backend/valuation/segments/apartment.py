"""아파트(R-APT) 비교사례 근거 단계. 가격 모델(CatBoost 등)을 import하지 않는다.

서비스 공개 기준(최근 6개월·같은 단지·전용 ±10%·5건)을 그대로 A1로 두고, 그보다 약한 근거를 단계로 나눈다.
- A1: 같은 단지·전용 ±10%·최근 6개월 5건 이상 (기존 공개 기준)
- A2: 같은 단지·전용 ±10%·최근 12개월 1건 이상 (A1 미달)
- A3: 같은 단지 다른 면적(±35%)·최근 12개월, 또는 같은 동 준공 ±5년·전용 ±20%·최근 12개월 3건 이상
- A4: 위 근거 없음 — 가격을 내지 않는다
모든 근거는 기준일(평가에서는 대상 거래일) **이전** 거래만 쓰고 대상 자신은 제외한다. 평가와 운영이 같은 규칙을 써야 누수가 없다.
금액은 원, 면적은 ㎡. 가격 비교는 ㎡당 가격의 로그로 한다. 시점 보정은 연립·다세대와 같은 시군구 월별 지수를 쓴다.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from backend.valuation.segments.row_house import MarketIndex

A1_DAYS, A1_MIN, A1_AREA = 183, 5, .10
A2_DAYS = 365
A3_COMPLEX_AREA = .35
A3_DONG_AREA, A3_DONG_YEARS, A3_DONG_MIN = .20, 5, 3
LEVELS = ("A1", "A2", "A3", "A4")


def complex_key(lawd: str, dong: str, name: str) -> str:
    # 국토부 단지명은 공백·접미어 표기가 섞인다. 같은 법정동 안에서만 이름을 비교해 다른 동의 동명 단지를 섞지 않는다.
    clean = (name or "").replace(" ", "")
    for suffix in ("아파트",):
        if clean.endswith(suffix) and len(clean) > len(suffix):
            clean = clean[: -len(suffix)]
    return f"{lawd}|{(dong or '').strip()}|{clean}"


@dataclass(frozen=True)
class Trade:
    id: int
    lawd: str
    dong: str
    complex: str
    day: date
    floor: int | None
    area: float
    price: int            # 원
    year_built: int | None
    direct: bool

    @property
    def log_per_sqm(self) -> float:
        return math.log(self.price / self.area)


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize(rows: list[dict]) -> list[Trade]:
    """저장 실거래 행을 비교용으로 정리한다. 해제·날짜/면적/가격/단지명 누락·중복 신고는 제외한다."""
    seen, out = set(), []
    for row in rows:
        if row.get("is_cancelled"):
            continue
        year, month, day = _int(row.get("deal_year")), _int(row.get("deal_month")), _int(row.get("deal_day"))
        area, price, name = row.get("area_sqm") or 0, row.get("price") or 0, (row.get("apt_name") or "").strip()
        if not (year and month and day) or area <= 0 or price <= 0 or not name:
            continue
        try:
            when = date(year, month, day)
        except ValueError:
            continue
        lawd, dong = str(row["lawd_cd"]), (row.get("dong") or "").strip()
        trade = Trade(id=int(row["id"]), lawd=lawd, dong=dong, complex=complex_key(lawd, dong, name), day=when,
                      floor=_int(row.get("floor")), area=float(area), price=int(price) * 10_000,  # 국토부 금액은 만원 단위
                      year_built=_int(row.get("year_built")), direct=row.get("transaction_type") == "직거래")
        identity = (trade.complex, trade.day, trade.floor, trade.area, trade.price)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(trade)
    out.sort(key=lambda t: (t.day, t.id))
    return out


@dataclass(frozen=True)
class Subject:
    """평가 대상. 운영에서는 사용자가 입력한 단지·면적·층·기준일, 평가에서는 실제 거래."""
    lawd: str
    dong: str
    complex: str
    area: float
    floor: int | None
    year_built: int | None
    day: date
    id: int = -1


@dataclass
class Evidence:
    level: str
    estimate: float | None     # 시점 보정한 ㎡당 가격 로그
    a1_count: int
    a1_median: float | None
    a2_count: int
    a2_median: float | None
    last_days: int | None
    cx_count: int
    cx_median: float | None
    cx_area_ratio: float | None
    dong_count: int
    dong_median: float | None
    basis: str


class ComparableIndex:
    """같은 단지·같은 동의 이전 거래를 빠르게 찾기 위한 색인."""

    def __init__(self, trades: list[Trade], index: MarketIndex):
        self.index = index
        self.by_complex: dict[str, list[Trade]] = defaultdict(list)
        self.by_dong: dict[str, list[Trade]] = defaultdict(list)
        for t in trades:
            self.by_complex[t.complex].append(t)
            self.by_dong[f"{t.lawd}|{t.dong}"].append(t)
        self._dong_days = {key: [t.day for t in rows] for key, rows in self.by_dong.items()}
        self._complex_year = {}
        for key, rows in self.by_complex.items():
            years = [t.year_built for t in rows if t.year_built]
            self._complex_year[key] = median(years) if years else None

    def complex_year(self, key: str) -> int | None:
        value = self._complex_year.get(key)
        return None if value is None else int(value)

    def evidence(self, target: Subject, as_of: date | None = None) -> Evidence:
        """as_of(기본: 대상 거래일) **이전** 거래만 근거로 쓴다."""
        cutoff = as_of or target.day
        def adjusted(t: Trade) -> float:
            return t.log_per_sqm + self.index.adjust(t.lawd, t.day, cutoff)
        same = [t for t in self.by_complex.get(target.complex, []) if t.id != target.id and cutoff - timedelta(days=A2_DAYS) <= t.day < cutoff]
        near = [t for t in same if abs(t.area / target.area - 1) <= A1_AREA + 1e-6]
        a1 = [t for t in near if t.day >= cutoff - timedelta(days=A1_DAYS)]
        cx = [t for t in same if abs(t.area / target.area - 1) <= A3_COMPLEX_AREA]
        a1_values, a2_values, cx_values = [adjusted(t) for t in a1], [adjusted(t) for t in near], [adjusted(t) for t in cx]
        key = f"{target.lawd}|{target.dong}"
        rows, days = self.by_dong.get(key, []), self._dong_days.get(key, [])
        start, stop = bisect_left(days, cutoff - timedelta(days=A2_DAYS)), bisect_left(days, cutoff)
        year = target.year_built or self.complex_year(target.complex)
        dong = [t for t in rows[start:stop] if t.id != target.id and t.complex != target.complex
                and abs(t.area / target.area - 1) <= A3_DONG_AREA
                and (year is None or t.year_built is None or abs(t.year_built - year) <= A3_DONG_YEARS)]
        dong_values = [adjusted(t) for t in dong]
        dong_median = median(dong_values) if len(dong_values) >= A3_DONG_MIN else None
        if len(a1) >= A1_MIN:
            level, estimate = "A1", median(a1_values)
            basis = f"같은 단지·전용 ±10% 최근 6개월 {len(a1)}건 ㎡당 중앙값을 시점 보정"
        elif near:
            level, estimate = "A2", median(a2_values)
            basis = f"같은 단지·전용 ±10% 최근 12개월 {len(near)}건 ㎡당 중앙값을 시점 보정 (공개 기준 5건 미달)"
        elif cx:
            level, estimate = "A3", median(cx_values)
            basis = f"같은 단지 다른 면적(±35%) 최근 12개월 {len(cx)}건 ㎡당 중앙값을 시점 보정, 면적 차이는 모델이 보정"
        elif dong_median is not None:
            level, estimate = "A3", dong_median
            basis = f"같은 동 준공 ±5년·전용 ±20% 다른 단지 최근 12개월 {len(dong)}건 ㎡당 중앙값을 시점 보정"
        else:
            level, estimate, basis = "A4", None, "같은 단지·같은 동 유사 단지의 최근 12개월 거래 없음"
        return Evidence(level=level, estimate=estimate, a1_count=len(a1), a1_median=median(a1_values) if a1_values else None,
                        a2_count=len(near), a2_median=median(a2_values) if a2_values else None,
                        last_days=(cutoff - max(t.day for t in near)).days if near else None,
                        cx_count=len(cx), cx_median=median(cx_values) if cx_values else None,
                        cx_area_ratio=median(t.area for t in cx) / target.area if cx else None,
                        dong_count=len(dong), dong_median=dong_median, basis=basis)


CATEGORICAL = ("lawd", "dong", "complex")
BASE_NUMERIC = ("floor", "area", "age", "month", "direct", "index_level")
COMP_NUMERIC = ("a1_count", "a1_median", "a2_count", "a2_median", "last_days", "cx_count", "cx_median", "cx_area_ratio",
                "dong_count", "dong_median", "comp_estimate", "block_median")


def features(subject: Subject, evidence: Evidence, index: MarketIndex, origin: int, direct: bool = False,
             year_built: int | None = None) -> dict:
    """평가·운영이 같은 변수를 쓰도록 한 곳에서 만든다. block_median은 비교사례 기준선의 2순위(같은 동 유사 단지)다."""
    month = subject.day.year * 12 + subject.day.month - 1
    nz = lambda v: float("nan") if v is None else v
    year = subject.year_built or year_built
    return {
        "lawd": subject.lawd, "dong": subject.dong or "미상", "complex": subject.complex,
        "floor": nz(subject.floor), "area": subject.area, "age": (subject.day.year - year) if year else float("nan"),
        "month": month - origin, "direct": float(direct), "index_level": nz(index.at(subject.lawd, month - 1)),
        "a1_count": evidence.a1_count, "a1_median": nz(evidence.a1_median), "a2_count": evidence.a2_count,
        "a2_median": nz(evidence.a2_median), "last_days": nz(evidence.last_days), "cx_count": evidence.cx_count,
        "cx_median": nz(evidence.cx_median), "cx_area_ratio": nz(evidence.cx_area_ratio), "dong_count": evidence.dong_count,
        "dong_median": nz(evidence.dong_median), "comp_estimate": nz(evidence.estimate), "block_median": nz(evidence.dong_median),
    }
