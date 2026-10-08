"""저장 실거래를 과거 시점으로 재생해 실제 주거용 에이전트의 가격 계산을 검증한다."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from statistics import mean
from types import SimpleNamespace
from unittest.mock import patch

from evaluation.schema import Check
from evaluation.suites import finish
from time import perf_counter


def _integer(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _month_index(ym: str) -> int:
    return int(ym[:4]) * 12 + int(ym[4:]) - 1


def _withheld_reason(plan: dict, captured: dict, target_ym: str) -> str:
    """보류를 단지 식별·거래 신선도·표본 부족·입력 조건으로 나눈다. 가격 계산에는 쓰지 않는다."""
    missing = [c["code"] for c in plan["checks"] if c["status"] != "available" and c["code"] != "comparables"]
    # 비교사례 부족이면 eligible_comparables가 방법을 blocked로 바꾸므로 방법 상태는 입력 부족 판단에 쓰지 않는다.
    if missing:
        return "input_" + missing[0]
    price_data = captured.get("price_data") or {}
    if not price_data.get("apt_name_matched"):
        return "complex_not_matched"
    recent = [row for row in price_data.get("samples") or []
              if row.get("deal_year") and row.get("deal_month")
              and 0 <= _month_index(target_ym) - (int(row["deal_year"]) * 12 + int(row["deal_month"]) - 1) <= 6]
    return "no_recent_trades" if not recent else "insufficient_samples"


def replay_one(target: dict, months: dict[str, list[dict]], lawd_code: str, region: str, policy: bool = False) -> dict:
    """policy=True면 공개 실행과 같은 PC-AVM 공통 정책(`valuation_plan`)을 거친다. 보류는 오차 계산에서 제외한다."""
    # 런타임 그래프와 같은 모듈을 가져와 평가용 축약 추정기와 계산이 갈라지지 않게 한다.
    import backend.router  # noqa: F401
    import agents
    import price_engine
    import reb_index
    target_ym = target["deal_ym"]
    used_months = set()

    def historical_source(url, key, lawd, requested, category):
        rows = []
        if lawd != lawd_code:
            return rows
        for ym in requested:
            if ym < target_ym and ym in months:
                used_months.add(ym)
                rows.extend(dict(row) for row in months.get(ym, []) if not row.get("is_cancelled"))
        return rows

    intent = SimpleNamespace(category="주거용", category_detail="아파트", area_min=target["area_sqm"],
        area_max=target["area_sqm"], area_raw="", appraisal_date=target_ym + "01",
        location_normalized=region, floor_inferred=_integer(target.get("floor")))
    state = {"intent": intent, "building_name": target.get("apt_name") or "",
        "geocoding_result": {"region_2depth": region, "region_3depth": target.get("dong") or "", "sigungu_cd": lawd_code}}
    captured: dict = {}
    if policy:
        from backend.valuation.policy import plan
        state["raw_inputs"] = {"property_category": "주거용", "property_detail": "아파트", "address": region,
            "area_sqm": target["area_sqm"], "appraisal_date": target_ym + "01",
            "valuation_context": {"scope": "single_unit", "area_basis": "exclusive", "transaction_type": "sale"}}
        state["appraisal_purpose"] = "매매"
        state["valuation_plan"] = plan(state)
        real_fetch = agents.fetch_real_transaction_prices

        def capture(*args, **kwargs):
            captured["price_data"] = real_fetch(*args, **kwargs)
            return captured["price_data"]
    # 당시 시설·건축물·웹 자료가 없다. 현재 외부 정보를 주입하지 않고 그 한계를 결과에 남긴다.
    with contextlib.ExitStack() as stack:
        for obj, name, replacement in [
            (price_engine, "MOLIT_API_KEY", "historical-replay"),
            (price_engine, "_fetch_by_ymds", historical_source),
            (price_engine, "_fetch_by_official_price", lambda **kwargs: price_engine._empty_price_data("과거 공시가격 미보유")),
            (reb_index, "is_enabled", lambda: False),
            (agents, "_fetch_build_year", lambda state: (_integer(target.get("year_built")), "")),
            (agents, "search_nearby_facilities", lambda *args, **kwargs: {}),
            (agents, "search_web_tavily", lambda *args, **kwargs: ""),
            (agents, "generate_appraisal_opinion", lambda *args, **kwargs: {}),
        ] + ([(agents, "fetch_real_transaction_prices", capture)] if policy else []):
            stack.enter_context(patch.object(obj, name, replacement))
        with contextlib.redirect_stdout(io.StringIO()):
            analysis = agents.residential_agent(state)["analysis_result"]
    estimated = analysis.get("estimated_value") or 0
    kind = analysis.get("result_kind") or ("market_reference" if estimated > 0 else "withheld")
    reason = "" if estimated > 0 else (_withheld_reason(state["valuation_plan"], captured, target_ym) if policy else "")
    comparables = analysis.get("comparables") or []
    from backend.comparable_matching import comparable_match_level
    levels = [comparable_match_level(row) for row in comparables]
    # 구 대체 사례의 단지 이름이 우연히 같아도 동일 단지로 승격하지 않는다.
    order = ["same_complex", "same_dong", "same_gu", "nearby", "fallback"]
    match = max(levels, key=order.index) if levels else "fallback"
    area = target["area_sqm"]
    year = _integer(target.get("year_built"))
    return {"target_month": target_ym, "actual_manwon": target["price"], "estimated_manwon": estimated,
        "ape": abs(estimated - target["price"]) / target["price"] if estimated > 0 else None,
        "estimated": estimated > 0, "match_level": match, "comparable_count": len(comparables),
        "area_band": "under60" if area < 60 else "60to85" if area <= 85 else "over85",
        "build_year_band": "unknown" if not year else "before2000" if year < 2000 else "2000to2014" if year < 2015 else "2015plus",
        "prior_months": sorted(used_months), "result_kind": kind, "withheld_reason": reason,
        "value_min": analysis.get("value_min"), "value_max": analysis.get("value_max")}


def _summary(rows):
    measured = [row for row in rows if row["ape"] is not None]
    return {"targets": len(rows), "estimated": len(measured), "unestimated": len(rows)-len(measured),
        "coverage": len(measured)/len(rows) if rows else 0,
        "mape": mean(row["ape"] for row in measured) if measured else None,
        "hit10": mean(row["ape"] <= .1 for row in measured) if measured else None,
        "range_hit": mean(row["value_min"] <= row["actual_manwon"] <= row["value_max"] for row in measured) if measured else None}


def evaluate(regions, target_months=3, max_cases=30, min_coverage=.8, max_mape=.25, policy=False):
    from sqlalchemy import select
    from db.base import session_scope
    from db.models import Transaction, LegalRegion
    started = perf_counter()
    pools, source_data = [], {}
    with session_scope() as session:
        for code in regions:
            region = session.scalar(select(LegalRegion.full_name).where(LegalRegion.lawd_code == code, LegalRegion.level == "sigungu")) or code
            latest = session.scalar(select(Transaction.deal_ym).where(Transaction.lawd_cd == code,
                Transaction.endpoint == "RTMSDataSvcAptTrade", Transaction.is_cancelled.is_(False)).order_by(Transaction.deal_ym.desc()).limit(1))
            if not latest:
                pools.append([])
                continue
            absolute = int(latest[:4])*12 + int(latest[4:])-1
            lower = absolute-target_months-11
            lower_ym = f"{lower//12:04d}{lower%12+1:02d}"
            rows = session.scalars(select(Transaction).where(Transaction.lawd_cd == code,
                Transaction.endpoint == "RTMSDataSvcAptTrade", Transaction.deal_ym >= lower_ym,
                Transaction.is_cancelled.is_(False), Transaction.price > 0, Transaction.area_sqm > 0).order_by(Transaction.deal_ym, Transaction.id)).all()
            months = {}
            for row in rows:
                months.setdefault(row.deal_ym, []).append({"apt_name": row.apt_name or "", "dong": row.dong or "",
                    "area_sqm": row.area_sqm, "price": row.price, "per_sqm": row.per_sqm or row.price/row.area_sqm,
                    "floor": row.floor or "0", "year_built": row.year_built or "0", "deal_ym": row.deal_ym,
                    "deal_year": int(row.deal_ym[:4]), "deal_month": int(row.deal_ym[4:]), "deal_day": row.deal_day or "",
                    "is_cancelled": False})
            source_data[code] = months
            target_yms = sorted(months)[-target_months:]
            # 면적·연식별 첫 표본을 번갈아 뽑아 특정 대단지에 표본이 몰리는 것을 줄인다.
            groups = {}
            for ym in target_yms:
                for row in months[ym]:
                    area = row["area_sqm"]
                    key = (ym, "small" if area < 60 else "medium" if area <= 85 else "large", str(row["year_built"])[:3])
                    groups.setdefault(key, []).append(row)
            pool = []
            while any(groups.values()):
                for key in sorted(groups):
                    if groups[key]: pool.append((code, region, groups[key].pop(0)))
            pools.append(pool)
    records = []
    while len(records) < max_cases and any(pools):
        for pool in pools:
            if pool and len(records) < max_cases:
                code, region, target = pool.pop(0)
                record = {"lawd_code": code, "region": region, **replay_one(target, source_data[code], code, region, policy)}
                if policy:
                    # 같은 대상·같은 과거 자료로 정책 이전 기준선을 함께 재생해 비교한다.
                    base = replay_one(target, source_data[code], code, region)
                    record.update(baseline_estimated_manwon=base["estimated_manwon"], baseline_ape=base["ape"])
                records.append(record)
    metrics = _summary(records)
    if policy:
        metrics["withheld_rate"] = metrics["unestimated"] / len(records) if records else 0
        # 정책이 가격을 낸 표본만으로 기준선과 비교한다. 기준선의 전체 표본 수치와 구분한다.
        shared = [r for r in records if r["ape"] is not None and r["baseline_ape"] is not None]
        metrics["baseline_mape_on_policy_estimated"] = mean(r["baseline_ape"] for r in shared) if shared else None
        metrics["baseline_mape_all"] = mean(r["baseline_ape"] for r in records if r["baseline_ape"] is not None) if any(r["baseline_ape"] is not None for r in records) else None
    checks = [Check(name="data_present", passed=bool(records)).model_dump(),
        Check(name="regions_present", passed=all(any(row["lawd_code"]==code for row in records) for code in regions)).model_dump(),
        # 정책 모드의 보류는 의도된 결과다. 산출률은 기준 미달로 판정하지 않고 보고만 한다.
        Check(name="coverage", passed=policy or metrics["coverage"] >= min_coverage, expected=min_coverage, actual=metrics["coverage"]).model_dump(),
        Check(name="mape", passed=metrics["mape"] is not None and metrics["mape"] <= max_mape, expected=max_mape, actual=metrics["mape"]).model_dump(),
        Check(name="no_future_comparables", passed=all(all(ym < row["target_month"] for ym in row["prior_months"]) for row in records)).model_dump()]
    by = {}
    for axis in ("region", "area_band", "build_year_band", "match_level", "withheld_reason"):
        by[axis] = {value:_summary([r for r in records if r[axis]==value]) for value in sorted({r[axis] for r in records})}
    return finish("residential-agent-replay", "avm_service", started, checks,
        {"records": records, "by_group": by, "data_sha256": hashlib.sha256(json.dumps(source_data,sort_keys=True).encode()).hexdigest(),
         "policy": policy, "scope": "실제 residential_agent·실거래 매칭·시세 계산 재생. 당월 거래 제외. 현재 시설·웹·LLM·공시가격을 사용하지 않고 시점수정은 서비스의 근사율 경로. 당시 발표 지연·시설 정보와 전체 브라우저 품질은 미검증. 추정 범위 적중률은 신뢰구간 보장 아님."}, metrics)
