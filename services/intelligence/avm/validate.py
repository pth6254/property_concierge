"""자체 검증: 학습에 쓰지 않은 이후 기간 실거래로 오차표를 만든다(시간 분할 홀드아웃).

python validate.py --train-start 202410 --validation-start 202605 --test-start 202607 --test-end 202609
python validate.py ... --model ridge     # 같은 분할로 다른 모델 평가 (모델 교체 전 비교)
- 학습 < 검증 < 평가. 반복 수·구간·신뢰도는 검증으로만 정하고, 평가 구간은 학습·보정에 쓰지 않는다.
- 평가 대상은 블라인드 입력처럼 거래 유형을 모른다고 보고 중개거래로 예측한다.
- 비교사례만 / 혼합형(비교사례+CatBoost)의 오차, 근거 버킷별 오차, 구간 적중률, 신뢰도와 실제 적중률, 20건 무작위 블라인드 분포를 기록한다.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median

from rh_avm.core import load_trades
from rh_avm.model import COLUMNS, build_records, interval, train

ROOT = Path(__file__).resolve().parent


def first_day(ym: str) -> date:
    return date(int(ym[:4]), int(ym[4:]), 1)


def last_day(ym: str) -> date:
    y, m = int(ym[:4]), int(ym[4:])
    return date.fromordinal(date(y + (m == 12), m % 12 + 1, 1).toordinal() - 1)


def metrics(errors: list[float]) -> dict:
    if not errors:
        return {"n": 0}
    ape = sorted(abs(e) for e in errors)
    return {"n": len(ape), "mape": round(mean(ape), 4), "median_ape": round(median(ape), 4),
            "hit10": round(sum(a <= .10 for a in ape) / len(ape), 4), "hit20": round(sum(a <= .20 for a in ape) / len(ape), 4),
            "p90_ape": round(ape[int(.9 * (len(ape) - 1))], 4)}


def main() -> None:
    parser = argparse.ArgumentParser(description="R-RH 자체 홀드아웃 검증")
    parser.add_argument("--data", default=str(ROOT / "data" / "rh_trades.csv"))
    parser.add_argument("--train-start", required=True)
    parser.add_argument("--validation-start", required=True)
    parser.add_argument("--test-start", required=True)
    parser.add_argument("--test-end", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", default="catboost", help="평가할 가격 모델 (catboost, ridge, comparables)")
    args = parser.parse_args()
    trades = load_trades(Path(args.data))
    test_start, test_end = first_day(args.test_start), last_day(args.test_end)
    final, meta, _, _ = train(trades, first_day(args.train_start), first_day(args.validation_start),
                              date.fromordinal(test_start.toordinal() - 1), seed=args.seed, model_name=args.model)
    test, _, _, _ = build_records(trades, test_start, test_end, blind_after=test_start)
    predicted = final.predict(test[COLUMNS])
    groups, rows = defaultdict(lambda: defaultdict(list)), []
    for i, rec in test.iterrows():
        estimate = math.exp(predicted[i]) * rec.area_value
        low, high, confidence = interval(predicted[i], rec.area_value, meta["calibration"], rec.bucket)
        error = estimate / rec.price - 1
        # 과제 권역: 강서구는 화곡동만, 관악·강남은 구 전체. 학습에는 강서구 전체 거래를 쓴다.
        in_scope = rec.lawd_code != "11500" or rec.dong == "화곡동"
        rows.append({"id": int(rec.id), "bucket": rec.bucket, "lawd": rec.lawd_code, "scope": bool(in_scope), "actual": int(rec.price), "estimate": round(estimate),
                     "low": round(low), "high": round(high), "inside": bool(low <= rec.price <= high), "confidence": confidence,
                     "error": round(error, 4), "basis": rec.basis})
        for key in ("all", rec.level, rec.bucket, f"region:{rec.lawd_code}") + (("scope",) if in_scope else ()):
            groups["hybrid"][key].append(error)
        if not math.isnan(rec.comp_estimate):
            groups["comparables"]["all"].append(math.exp(rec.comp_estimate) * rec.area_value / rec.price - 1)
            groups["comparables"][rec.level].append(math.exp(rec.comp_estimate) * rec.area_value / rec.price - 1)
    by_bucket = defaultdict(list)
    for row in rows:
        by_bucket[row["bucket"]].append(row)
    calibration = {name: {"n": len(items), "stated_confidence": items[0]["confidence"],
                          "observed_hit10": round(mean(abs(r["error"]) <= .10 for r in items), 3),
                          "interval_coverage": round(mean(r["inside"] for r in items), 3)} for name, items in sorted(by_bucket.items())}
    rng = random.Random(args.seed)
    scope_rows = [r for r in rows if r["scope"]]
    draws = sorted(mean(abs(r["error"]) for r in rng.sample(scope_rows, 20)) for _ in range(500))
    report = {"period": vars(args) | {"data": Path(args.data).name},
              "model": {"name": final.name, "training": final.training, "validation_mape": meta["validation_mape"]} | {k: meta[k] for k in ("train_rows", "validation_rows", "train_outliers_removed")},
              "metrics": {name: {key: metrics(values) for key, values in sorted(g.items())} for name, g in groups.items()},
              "interval_coverage_all": round(mean(r["inside"] for r in rows), 3),
              "interval_coverage_scope": round(mean(r["inside"] for r in scope_rows), 3), "calibration_by_bucket": calibration,
              "blind_20": {"population": "과제 권역", "draws": 500, "mape_median": round(median(draws), 4), "mape_p10": round(draws[50], 4), "mape_p90": round(draws[449], 4)},
              "worst_cases": sorted(rows, key=lambda r: -abs(r["error"]))[:10]}
    suffix = "" if args.model == "catboost" else f"_{args.model}"
    out = ROOT / "validation" / f"holdout_{args.test_start}_{args.test_end}{suffix}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    h, c = report["metrics"]["hybrid"]["all"], report["metrics"]["comparables"]["all"]
    print(f"평가 {args.test_start}~{args.test_end}: {h['n']}건 · 모델 {final.name} (검증 MAPE {meta['validation_mape']:.1%})")
    print(f"  혼합형   MAPE {h['mape']:.1%} · 중앙값 {h['median_ape']:.1%} · ±10% {h['hit10']:.1%} · ±20% {h['hit20']:.1%}")
    print(f"  비교사례 MAPE {c['mape']:.1%} · 중앙값 {c['median_ape']:.1%} · ±10% {c['hit10']:.1%} ({c['n']}건, 근거 있는 거래만)")
    sc = report["metrics"]["hybrid"]["scope"]
    print(f"  과제 권역 MAPE {sc['mape']:.1%} · 중앙값 {sc['median_ape']:.1%} · ±10% {sc['hit10']:.1%} ({sc['n']}건) · 구간 적중 {report['interval_coverage_scope']:.1%}")
    print(f"  전체 구간 적중 {report['interval_coverage_all']:.1%} · 과제 권역 20건 블라인드 MAPE 중앙값 {report['blind_20']['mape_median']:.1%} "
          f"({report['blind_20']['mape_p10']:.1%}~{report['blind_20']['mape_p90']:.1%})")
    for name, item in calibration.items():
        print(f"  {name}: {item['n']}건 · 신뢰도 {item['stated_confidence']} → 실제 ±10% {item['observed_hit10']} · 구간 적중 {item['interval_coverage']}")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
