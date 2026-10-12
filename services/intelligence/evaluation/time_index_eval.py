"""아파트 비교사례 시점 보정 방식 비교 (운영 A1 규칙: 같은 단지·전용 ±10%·6개월 5건, 보정 ㎡당 가격 평균 × 면적).

비교 방식
- V0 보정 없음
- V1 운영 재현: 부동산원 월간 지수(거래일 15일 이후면 전월, 아니면 전전월까지 공표됐다고 본다) + 미공표 구간 월 0.3%
- V2 시군구 거래 중앙값 지수(MarketIndex, 현재 ML 변수)
- V3 단지·면적대 고정효과 지수(ChainIndex), 마지막 완결 월 이후 연장 없음
- V4 V3 + 최근 3개월 기울기로 기준일까지 연장
- V5 부동산원 지수 + 미공표 구간을 지수의 최근 3개월 추세로 연장

판정 기준(SELECTION)은 결과를 보기 전에 정했다. 앞 6개월로 고르고 뒤 6개월로만 운영 반영 여부를 판정한다.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean

from backend.valuation.segments import apartment as apt
from backend.valuation.segments.row_house import MarketIndex
from backend.valuation.time_index import ChainIndex, month_index
from evaluation.segment_avm import _metrics, load_rows

VARIANTS = ("V0", "V1", "V2", "V3", "V4", "V5")
APPROX_RATE = .003  # 운영 price_engine._TIME_ADJ_MONTHLY_RATE["주거용"]
# 2026-10-12, 결과를 보기 전에 정한 선택·반영 기준.
SELECTION = {
    "select_months": ("202510", "202603"),      # 이 기간 MAPE 최저 방식을 고른다
    "confirm_months": ("202604", "202609"),     # 이 기간으로만 운영 반영 여부를 판정한다
    "min_relative_improvement": .03,             # V1 대비 MAPE 3% 이상 개선
    "region_min_n": 100, "region_margin_pp": .01,  # 표본 100건 이상 구 중 1.0%p 넘게 나쁜 구 없음
}


def _ym(index: int) -> str:
    return f"{index // 12:04d}{index % 12 + 1:02d}"


def _six_months_before(day: date) -> date:
    index = month_index(day) - 6
    year, month = index // 12, index % 12 + 1
    from calendar import monthrange
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def region_names(lawds) -> dict[str, tuple[str, str]]:
    from sqlalchemy import text
    from db.base import get_engine
    with get_engine().connect() as connection:
        rows = connection.execute(text("SELECT lawd_code, full_name FROM legal_regions WHERE level='sigungu' AND lawd_code = ANY(:codes)"),
                                  {"codes": list(lawds)}).all()
    out = {}
    for code, full in rows:
        parts = full.split()
        out[code] = (parts[-1], parts[0])
    return out


def reb_levels(lawds, months: list[str]) -> dict[str, dict[int, float]]:
    """부동산원 아파트 매매가격지수(운영과 같은 통계표). 캐시에 쓰지 않고 직접 조회한다."""
    import reb_index
    names = region_names(lawds)
    statbl = reb_index._CATEGORY_STATBL["주거용"]
    out = defaultdict(dict)
    for ym in months:
        rows = reb_index._fetch_month_rows(statbl, ym) or {}
        for lawd, (region, sido) in names.items():
            value = reb_index._match_region(rows, region, sido) if rows else None
            if value:
                out[lawd][int(ym[:4]) * 12 + int(ym[4:]) - 1] = float(value)
    return out


def _reb_factor(levels: dict[int, float], deal: date, as_of: date, trend: bool) -> float:
    m_deal, m_as_of = month_index(deal), month_index(as_of)
    published = m_as_of - (1 if as_of.day >= 15 else 2)
    available = [m for m in levels if m <= published]
    if not available or m_deal not in levels or m_deal >= max(available):
        return (1 + APPROX_RATE) ** max(m_as_of - m_deal, 0)
    reached = max(available)
    factor = levels[reached] / levels[m_deal]
    remain = m_as_of - reached
    if remain <= 0:
        return factor
    if trend and reached - 3 in levels:
        monthly = (levels[reached] / levels[reached - 3]) ** (1 / 3)
    else:
        monthly = 1 + APPROX_RATE
    return factor * monthly ** remain


def evaluate(trades: list, reb: dict, test_months: list[str]) -> dict:
    market = MarketIndex(trades)
    by_complex = defaultdict(list)
    for t in trades:
        by_complex[t.complex].append(t)
    errors = {v: defaultdict(list) for v in VARIANTS}
    for ym in test_months:
        m = int(ym[:4]) * 12 + int(ym[4:]) - 1
        chain = ChainIndex(trades, m)
        targets = [t for t in trades if month_index(t.day) == m]
        for target in targets:
            start = _six_months_before(target.day)
            seen, comps = set(), []
            for c in by_complex[target.complex]:
                if c.id == target.id or not start <= c.day <= target.day or abs(c.area / target.area - 1) > .100001:
                    continue
                identity = (c.day, c.floor, c.area, c.price)
                if identity not in seen:
                    seen.add(identity); comps.append(c)
            if len(comps) < 5:
                continue
            per_sqm = [c.price / c.area for c in comps]
            factors = {
                "V0": [1.0] * len(comps),
                "V1": [_reb_factor(reb.get(target.lawd, {}), c.day, target.day, False) for c in comps],
                "V2": [math.exp(market.adjust(c.lawd, c.day, target.day)) for c in comps],
                "V3": [math.exp(chain.adjust(c.lawd, c.day, target.day, False)) for c in comps],
                "V4": [math.exp(chain.adjust(c.lawd, c.day, target.day, True)) for c in comps],
                "V5": [_reb_factor(reb.get(target.lawd, {}), c.day, target.day, True) for c in comps],
            }
            for variant, fs in factors.items():
                estimate = mean(p * f for p, f in zip(per_sqm, fs)) * target.area
                error = estimate / target.price - 1
                for key in ("all", f"month:{ym}", f"region:{target.lawd}"):
                    errors[variant][key].append(error)
    return errors


def evaluate_with_regions(trades, reb, months):
    """판정은 확인 기간(뒤 6개월)의 구별 성적으로 한다. 기간별로 따로 모은다."""
    conf_months = [ym for ym in months if SELECTION["confirm_months"][0] <= ym <= SELECTION["confirm_months"][1]]
    sel_months = [ym for ym in months if SELECTION["select_months"][0] <= ym <= SELECTION["select_months"][1]]
    return evaluate(trades, reb, sel_months), evaluate(trades, reb, conf_months)


def verdict(select: dict, confirm: dict) -> dict:
    chosen = min(VARIANTS, key=lambda v: _metrics(select[v]["all"])["mape"])
    base, new = _metrics(confirm["V1"]["all"]), _metrics(confirm[chosen]["all"])
    regions = [k for k in confirm["V1"] if k.startswith("region:") and len(confirm["V1"][k]) >= SELECTION["region_min_n"]]
    worse = {k[7:]: (_metrics(confirm[chosen][k])["mape"], _metrics(confirm["V1"][k])["mape"]) for k in regions
             if _metrics(confirm[chosen][k])["mape"] > _metrics(confirm["V1"][k])["mape"] + SELECTION["region_margin_pp"]}
    improvement = 1 - new["mape"] / base["mape"]
    checks = {"relative_improvement": {"value": round(improvement, 4), "pass": improvement >= SELECTION["min_relative_improvement"]},
              "bias": {"chosen": new["bias"], "production": base["bias"], "pass": abs(new["bias"]) < abs(base["bias"])},
              "regions": {"worse": worse, "pass": not worse}}
    return {"chosen_by_select_period": chosen, "checks": checks, "apply_to_production": chosen != "V1" and all(c["pass"] for c in checks.values())}


def run(args) -> int:
    from dotenv import load_dotenv
    from concierge_workspace import REPO_ROOT
    load_dotenv(REPO_ROOT / ".env", override=False)
    import reb_index
    if not reb_index.is_enabled():
        raise ValueError("운영 재현(V1)에 부동산원 API 키가 필요합니다")
    months = []
    index, last = int(args.from_month[:4]) * 12 + int(args.from_month[4:]) - 1, int(args.to_month[:4]) * 12 + int(args.to_month[4:]) - 1
    while index <= last:
        months.append(_ym(index)); index += 1
    first = int(args.from_month[:4]) * 12 + int(args.from_month[4:]) - 1 - 24
    rows = load_rows(tuple(args.regions), _ym(first), args.to_month, "RTMSDataSvcAptTrade")
    trades = apt.normalize(rows)
    reb = reb_levels(set(args.regions), [_ym(i) for i in range(first, last + 1)])
    select, confirm = evaluate_with_regions(trades, reb, months)
    def table(errors):
        return {v: {"all": _metrics(errors[v]["all"]),
                    "months": {k[6:]: _metrics(e) for k, e in sorted(errors[v].items()) if k.startswith("month:")},
                    "regions": {k[7:]: _metrics(e) for k, e in sorted(errors[v].items()) if k.startswith("region:")}} for v in VARIANTS}
    report = {"selection": SELECTION, "regions": args.regions, "reb_regions_found": sorted(reb), "select": table(select), "confirm": table(confirm),
              "verdict": verdict(select, confirm)}
    directory = Path(args.output) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-avm-time-index")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"select": {v: report["select"][v]["all"] for v in VARIANTS}, "confirm": {v: report["confirm"][v]["all"] for v in VARIANTS},
                      "verdict": report["verdict"], "reb_regions_found": len(reb), "report": str(directory / "result.json")}, ensure_ascii=False, indent=1))
    return 0
