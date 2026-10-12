"""세그먼트 AVM 월별 롤링 평가 (현재 R-APT 아파트).

평가 월 M마다 학습 < M-2, 검증(조기 종료·혼합 가중치·구간·신뢰도) = M-2~M-1, 평가 = M 으로 다시 학습한다.
두 기간 평가로는 결론이 기간마다 바뀌었다(2026-04~06과 07~09). 12개월을 한 달씩 굴려 같은 규칙으로 쌓아 보고,
**결과를 보기 전에 정한 기준**(ACCEPTANCE)으로만 판정한다. 기준을 결과를 본 뒤 바꾸면 그 사실을 문서에 남겨야 한다.

근거·변수는 각 거래일 이전 거래만 쓰므로 한 번만 계산하고(build_frame) 월마다 학습만 다시 한다.
현재 서비스 규칙(A1만 산출)과 같은 평가 거래로 비교한다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from evaluation.segment_avm import SEGMENTS, SegmentConfig, _metrics, assess, build_frame, load_rows, split_parts

# 2026-10-12, 롤링 결과를 보기 전에 정한 판정 기준.
ACCEPTANCE = {
    "a1_hybrid": {
        "pooled_mape_relative_improvement": .05,   # 같은 A1 거래에서 기존 규칙 대비 MAPE 5% 이상 개선
        "month_margin_pp": .003,                     # 월별로 기존 규칙보다 0.3%p 넘게 나쁜 달이
        "max_worse_months": 2,                       # 2개월 이하
        "region_min_n": 100, "region_margin_pp": .01,  # 표본 100건 이상 구에서 1.0%p 넘게 나쁜 구가 없음
        "max_abs_bias": .02,                         # 전체 평균 편향 ±2% 이내
    },
    "model_estimate": {
        "coverage_low": .80, "coverage_high": .90,   # 85% 명목 구간의 단계별 실제 적중
        "min_price_band_coverage": .75,             # 실제 가격 5분위 어느 칸도 75% 미만이면 안 됨
        "confidence_tolerance": .05,                # 표시 신뢰도와 실제 ±10% 적중의 차이
        "a3_min_hit10": .35,                         # A3 실제 ±10% 적중이 이보다 낮으면 A3 보류 권고
    },
}


def months_between(start: str, end: str) -> list[str]:
    index, last, out = int(start[:4]) * 12 + int(start[4:]) - 1, int(end[:4]) * 12 + int(end[4:]) - 1, []
    while index <= last:
        out.append(f"{index // 12:04d}{index % 12 + 1:02d}")
        index += 1
    return out


def shift(ym: str, months: int) -> str:
    index = int(ym[:4]) * 12 + int(ym[4:]) - 1 + months
    return f"{index // 12:04d}{index % 12 + 1:02d}"


def _rule_rows(test, column: str = "service_rule") -> list[dict]:
    produced = test[test[column].notna()] if column in test else test.iloc[0:0]
    return [{"id": int(r.id), "ym": r.ym, "level": r.level, "lawd": r.lawd, "actual": int(r.price), "estimate": float(getattr(r, column)),
             "error": getattr(r, column) / r.price - 1} for r in produced.itertuples()]


def _price_quintile(rows: list[dict], edges: list[float]) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[f"price_q{sum(r['actual'] > e for e in edges) + 1}"].append(r)
    return groups


def summarize(model_rows: list[dict], rule_rows: list[dict], edges: list[float], levels: list[str]) -> dict:
    """모델·규칙의 단계·월·구·가격대별 지표와 구간 적중, 신뢰도 보정."""
    out = {"model": {}, "rule": {}}
    for name, rows in (("model", model_rows), ("rule", rule_rows)):
        groups = defaultdict(list)
        for r in rows:
            for key in ("all", r["level"], f"month:{r['ym']}", f"region:{r['lawd']}", f"{r['level']}|month:{r['ym']}", f"{r['level']}|region:{r['lawd']}"):
                groups[key].append(r["error"])
        for key, part in _price_quintile(rows, edges).items():
            groups[key] = [r["error"] for r in part]
            for level in levels:
                groups[f"{level}|{key}"] = [r["error"] for r in part if r["level"] == level]
        out[name] = {key: _metrics(values) for key, values in sorted(groups.items()) if values}
    coverage = {}
    for variant in ("level", "price"):
        flag = f"inside_{variant}"
        cov = {lv: [r[flag] for r in model_rows if r["level"] == lv and r[flag] is not None] for lv in levels}
        coverage[variant] = {lv: round(mean(v), 3) if v else None for lv, v in cov.items()}
        for key, part in _price_quintile(model_rows, edges).items():
            flags = [r[flag] for r in part if r[flag] is not None]
            coverage[variant][key] = round(mean(flags), 3) if flags else None
    calibration = {}
    for variant in ("level", "price"):
        flag = f"confidence_{variant}"
        calibration[variant] = {}
        for lv in levels:
            rows = [r for r in model_rows if r["level"] == lv and r[flag] is not None]
            if rows:
                calibration[variant][lv] = {"stated": round(mean(r[flag] for r in rows), 3),
                                            "observed_hit10": round(mean(abs(r["error"]) <= .10 for r in rows), 3)}
    out["coverage"], out["calibration"] = coverage, calibration
    return out


def judge(summary: dict, months: list[str], levels: list[str]) -> dict:
    """ACCEPTANCE 기준 판정. 각 항목의 값과 통과 여부를 남긴다."""
    a1, est = ACCEPTANCE["a1_hybrid"], ACCEPTANCE["model_estimate"]
    model, rule = summary["model"], summary["rule"]
    checks = {}
    if "A1" in model and "all" in rule:
        m, r = model["A1"]["mape"], rule["all"]["mape"]
        checks["a1_pooled_improvement"] = {"model": m, "rule": r, "relative": round(1 - m / r, 4), "pass": 1 - m / r >= a1["pooled_mape_relative_improvement"]}
        worse = [ym for ym in months if f"A1|month:{ym}" in model and f"month:{ym}" in rule
                 and model[f"A1|month:{ym}"]["mape"] > rule[f"month:{ym}"]["mape"] + a1["month_margin_pp"]]
        checks["a1_worse_months"] = {"months": worse, "pass": len(worse) <= a1["max_worse_months"]}
        regions = [k.split(":", 1)[1] for k in rule if k.startswith("region:") and rule[k]["n"] >= a1["region_min_n"]]
        bad = {g: (model[f"A1|region:{g}"]["mape"], rule[f"region:{g}"]["mape"]) for g in regions
               if f"A1|region:{g}" in model and model[f"A1|region:{g}"]["mape"] > rule[f"region:{g}"]["mape"] + a1["region_margin_pp"]}
        checks["a1_regions"] = {"worse": bad, "pass": not bad}
        checks["a1_bias"] = {"bias": model["A1"]["bias"], "pass": abs(model["A1"]["bias"]) <= a1["max_abs_bias"]}
    a1_pass = all(checks[k]["pass"] for k in ("a1_pooled_improvement", "a1_worse_months", "a1_regions", "a1_bias") if k in checks)
    estimate = {}
    for variant in ("level", "price"):
        cov, cal = summary["coverage"][variant], summary["calibration"][variant]
        per_level = {lv: cov.get(lv) for lv in levels if lv != "A1"}
        bands = {k: v for k, v in cov.items() if k.startswith("price_q")}
        estimate[variant] = {
            "coverage": {lv: {"value": v, "pass": v is not None and est["coverage_low"] <= v <= est["coverage_high"]} for lv, v in per_level.items()},
            "price_band_coverage": {"min": min((v for v in bands.values() if v is not None), default=None),
                                    "pass": all(v is None or v >= est["min_price_band_coverage"] for v in bands.values())},
            "calibration": {lv: {**c, "pass": abs(c["stated"] - c["observed_hit10"]) <= est["confidence_tolerance"]} for lv, c in cal.items() if lv != "A1"},
        }
    a3 = model.get("A3", {}).get("hit10")
    return {"a1_hybrid": {"checks": checks, "approve": bool(checks) and a1_pass},
            "model_estimate": estimate,
            "a3": {"hit10": a3, "keep": a3 is None or a3 >= est["a3_min_hit10"]}}


def evaluate(rows: list[dict], segment: str, test_months: list[str], train_start: str, models: tuple[str, ...],
             base: SegmentConfig, progress=print, reb: dict | None = None) -> dict:
    spec_segment = SEGMENTS[segment]
    levels = [lv for lv in spec_segment.levels if lv not in spec_segment.withheld_levels]
    trades, frame = build_frame(rows, segment, train_start, reb=reb)
    per_model = {spec: [] for spec in models}
    rules, rules_reb, monthly = [], [], []
    for ym in test_months:
        config = replace(base, segment=segment, train_start=train_start, validation_start=shift(ym, -2), test_start=ym, test_end=ym,
                         keep_rows=True)
        parts = split_parts(frame, config)
        train = parts["train"]
        gap = (train.target - train.comp_estimate).abs()
        train = train[~(gap > config.train_outlier_log)].reset_index(drop=True)
        rules += _rule_rows(parts["test"])
        rules_reb += _rule_rows(parts["test"], "service_rule_reb")
        for spec in models:
            result, _, _ = assess(spec, train, parts["validation"], parts["test"], config)
            per_model[spec] += result["rows"]
            monthly.append({"month": ym, "model": spec, "train_rows": len(train), "validation_mape": result["validation_mape"],
                            "test_rows": len(parts["test"]), "produced_rate": result["produced_rate"], "weights": result["weights"]})
            progress(f"{ym} {spec}: 평가 {len(parts['test'])}건 · MAPE {result['metrics']['all'].get('mape')}")
    import numpy as np
    all_prices = [r["actual"] for r in rules] + [r["actual"] for spec in models for r in per_model[spec]]
    edges = [float(np.quantile(all_prices, q)) for q in (.2, .4, .6, .8)] if all_prices else []
    report = {"segment": spec_segment.id, "test_months": test_months, "train_start": train_start, "config": asdict(base),
              "acceptance": ACCEPTANCE, "price_quintile_edges": edges, "monthly": monthly, "models": {}}
    for spec in models:
        summary = summarize(per_model[spec], rules, edges, levels)
        report["models"][spec] = {"summary": summary, "verdict": judge(summary, test_months, levels),
                                  "produced_rate": round(len(per_model[spec]) / max(sum(m["test_rows"] for m in monthly if m["model"] == spec), 1), 4)}
    report["rule_produced_rate"] = round(len(rules) / max(sum(m["test_rows"] for m in monthly if m["model"] == models[0]), 1), 4)
    # 비교 기준선은 현재 운영 규칙(V4 지수)이다. 이전 운영(부동산원 지수 + 월 0.3%) 성적은 참고로만 남긴다.
    report["rule_reb_reference"] = {"all": _metrics([r["error"] for r in rules_reb])} if rules_reb else None
    report["rows"] = {"rule": rules, "rule_reb": rules_reb, **per_model}
    return report


def run(args) -> int:
    from dotenv import load_dotenv
    from concierge_workspace import REPO_ROOT
    load_dotenv(REPO_ROOT / ".env", override=False)
    segment = SEGMENTS[args.segment]
    if args.to_month >= datetime.now(timezone.utc).strftime("%Y%m"):
        raise ValueError("진행 중이거나 미래인 월을 평가에 넣을 수 없습니다")
    test_months = months_between(args.from_month, args.to_month)
    if shift(test_months[0], -2) <= args.train_start:
        raise ValueError("첫 평가 월의 검증 구간(2개월 전)이 학습 시작보다 뒤여야 합니다")
    models = tuple(s.strip() for s in args.models.split(",") if s.strip())
    base = SegmentConfig(tuple(args.regions), args.train_start, args.train_start, args.train_start, args.train_start,
                         models=models, iterations=args.iterations, seed=args.seed, segment=args.segment, interval=args.interval)
    start_month = shift(args.train_start, -segment.history_months)
    rows = load_rows(base.regions, start_month, args.to_month, segment.endpoint)
    reb = None
    try:
        import reb_index
        if reb_index.is_enabled():
            from evaluation.time_index_eval import reb_levels
            reb = reb_levels(set(base.regions), months_between(start_month, args.to_month))
    except Exception as exc:  # 참고 기준선만 빠진다. 판정은 현재 운영 규칙으로 한다.
        print(f"부동산원 지수 참고 기준선 생략: {type(exc).__name__}")
    report = evaluate(rows, args.segment, test_months, args.train_start, models, base, reb=reb)
    directory = Path(args.output) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-avm-rolling-{args.segment}")
    directory.mkdir(parents=True, exist_ok=True)
    rows_out = report.pop("rows")
    (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with (directory / "rows.jsonl").open("w", encoding="utf-8") as handle:
        for name, items in rows_out.items():
            for item in items:
                handle.write(json.dumps({"source": name, **{k: v for k, v in item.items() if k != "basis"}}, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({spec: {"produced_rate": value["produced_rate"], "verdict": value["verdict"]} for spec, value in report["models"].items()}
                     | {"rule_produced_rate": report["rule_produced_rate"], "report": str(directory / "result.json")}, ensure_ascii=False, indent=1, default=str))
    return 0
