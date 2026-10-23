"""공동주택 공시가격(호별)을 아파트 AVM 변수로 쓰기 위한 조회.

공시가격은 시장가격이 아니다. 같은 기준연도 안에서 **상대값**(같은 단지에서 층·위치 차이, 비교사례 단지와 대상 단지의 차이)만 쓴다.
- 공표 시점: 매년 1월 1일 기준가격이 4월 말에 공표된다. 거래일(또는 기준일)이 5월 이후면 그해, 아니면 전년 공시가격을 쓴다.
  미래에 공표된 값을 과거 거래에 붙이면 평가가 실제보다 좋아진다.
- 대상 호실: 동·호를 알면 그 호실, 모르면 같은 층·같은 면적(±2%) 호실의 중앙값, 그것도 없으면 같은 면적대(±3%) 단지 중앙값.
평가(segment_avm)와 운영(apartment_avm)이 이 모듈의 같은 규칙을 쓴다. 금액은 원, 면적은 ㎡, 값은 ㎡당 공시가격의 로그다.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date
from statistics import median

UNIT_AREA_TOLERANCE = .02
AREA_TOLERANCE = .03


def available_year(day: date) -> int:
    return day.year if day.month >= 5 else day.year - 1


def _digits(text: str | None) -> str:
    return "".join(re.findall(r"\d+", text or ""))


def _floor(text) -> int | None:
    match = re.search(r"-?\d+", str(text or ""))
    if not match:
        return None
    value = int(match.group())
    return -value if str(text).strip().upper().startswith("B") and value > 0 else value


class OfficialPrices:
    """(PNU, 기준연도)별 호실 공시가격. rows: (pnu, stdr_year, dong_name, ho_name, floor_name, exclusive_area, official_price)."""

    def __init__(self, rows):
        self.cells: dict[tuple[str, int], list[tuple[int | None, float, float]]] = defaultdict(list)
        self.units: dict[tuple[str, int, str, str], float] = {}
        for pnu, year, dong, ho, floor, area, price in rows:
            if not area or area <= 0 or not price or price <= 0:
                continue
            value = math.log(price / area)
            self.cells[(pnu, int(year))].append((_floor(floor), float(area), value))
            if dong is not None or ho is not None:
                self.units[(pnu, int(year), _digits(dong), _digits(ho))] = value

    def year_for(self, pnu: str, day: date) -> int | None:
        # 공표된 연도가 아직 수집되지 않았으면 그 전 연도까지만 내려간다(미래 연도는 쓰지 않는다).
        year = available_year(day)
        for candidate in (year, year - 1):
            if (pnu, candidate) in self.cells:
                return candidate
        return None

    def area_level(self, pnu: str, year: int, area: float) -> float | None:
        values = [v for _, a, v in self.cells.get((pnu, year), ()) if abs(a / area - 1) <= AREA_TOLERANCE]
        return median(values) if values else None

    def unit_level(self, pnu: str, year: int, floor: int | None, area: float, dong: str = "", ho: str = "") -> float | None:
        if dong and ho:
            exact = self.units.get((pnu, year, _digits(dong), _digits(ho)))
            if exact is not None:
                return exact
        if floor is None:
            return None
        values = [v for f, a, v in self.cells.get((pnu, year), ()) if f == floor and abs(a / area - 1) <= UNIT_AREA_TOLERANCE]
        return median(values) if values else None

    def describe(self, pnu: str | None, day: date, floor: int | None, area: float, dong: str = "", ho: str = "") -> tuple[float | None, float | None, int | None]:
        """(호실 수준, 같은 면적대 단지 수준, 기준연도). 자료가 없으면 None."""
        if not pnu:
            return None, None, None
        year = self.year_for(pnu, day)
        if year is None:
            return None, None, None
        return self.unit_level(pnu, year, floor, area, dong, ho), self.area_level(pnu, year, area), year


def official_features(official: OfficialPrices | None, pnu_of, target_pnu: str | None, day: date, floor: int | None, area: float,
                      comps=(), dong: str = "", ho: str = "") -> dict:
    """대상과 비교사례의 공시가격 차이. 같은 기준연도(대상 날짜 기준)로 비교해 연도별 공시 변화가 섞이지 않게 한다.

    - official_premium: 대상 호실 수준 − 같은 면적대 단지 수준 (층·위치 프리미엄)
    - official_level: 같은 면적대 단지 수준 (단지 간 차이)
    - official_gap: 대상 기준값 − 비교사례 기준값 평균 (기준값 = 호실 수준, 없으면 면적대 수준)
    """
    out = {"official_premium": float("nan"), "official_level": float("nan"), "official_gap": float("nan")}
    if official is None or not target_pnu:
        return out
    unit, level, year = official.describe(target_pnu, day, floor, area, dong, ho)
    if year is None:
        return out
    if level is not None:
        out["official_level"] = level
        if unit is not None:
            out["official_premium"] = unit - level
    target_ref = unit if unit is not None else level
    refs = []
    for comp in comps:
        pnu = pnu_of(comp)
        if not pnu:
            continue
        comp_year = official.year_for(pnu, day)
        if comp_year != year:
            continue
        ref = official.unit_level(pnu, year, comp.floor, comp.area)
        refs.append(ref if ref is not None else official.area_level(pnu, year, comp.area))
    refs = [r for r in refs if r is not None]
    if target_ref is not None and refs:
        out["official_gap"] = target_ref - sum(refs) / len(refs)
    return out


def dong_codes(lawds) -> dict[tuple[str, str], str]:
    """(시군구 코드, 법정동 이름) → 법정동 코드(10)."""
    from sqlalchemy import text
    from db.base import get_engine
    with get_engine().connect() as connection:
        rows = connection.execute(text("SELECT lawd_code, name, code FROM legal_regions WHERE level='eup_myeon_dong' AND is_active "
                                       "AND lawd_code = ANY(:codes)"), {"codes": list(lawds)}).all()
    return {(lawd, name): code for lawd, name, code in rows}


def make_pnu_of(codes: dict[tuple[str, str], str]):
    from backend.tools.ingest_apartment_unit_prices import to_pnu
    cache: dict[tuple[str, str, str], str | None] = {}
    def pnu_of(trade) -> str | None:
        key = (trade.lawd, trade.dong, getattr(trade, "jibun", ""))
        if key not in cache:
            code = codes.get((trade.lawd, trade.dong))
            cache[key] = to_pnu(code, key[2]) if code and key[2] else None
        return cache[key]
    return pnu_of


def load(pnus=None, lawds=None, aggregate: bool = True) -> OfficialPrices:
    """평가는 PNU·연도·층·면적별 중앙값으로 줄여 읽고(aggregate), 운영은 한 필지의 호실 단위로 읽는다."""
    from sqlalchemy import text
    from db.base import get_engine
    where, params = [], {}
    if pnus is not None:
        where.append("pnu = ANY(:pnus)"); params["pnus"] = list(pnus)
    if lawds is not None:
        where.append("left(pnu, 5) = ANY(:lawds)"); params["lawds"] = list(lawds)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    if aggregate:
        sql = (f"SELECT pnu, stdr_year, NULL, NULL, floor_name, round(exclusive_area::numeric, 2)::float AS area, "
               f"percentile_cont(0.5) WITHIN GROUP (ORDER BY official_price) AS price FROM apartment_unit_prices {clause} "
               f"GROUP BY pnu, stdr_year, floor_name, round(exclusive_area::numeric, 2)")
    else:
        sql = f"SELECT pnu, stdr_year, dong_name, ho_name, floor_name, exclusive_area, official_price FROM apartment_unit_prices {clause}"
    with get_engine().connect() as connection:
        return OfficialPrices(connection.execute(text(sql), params).all())
