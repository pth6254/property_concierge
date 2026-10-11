"""세그먼트 AVM 오프라인 평가 (현재 R-RH: 연립·다세대). 가격 모델은 교체 가능하다.

`--models catboost,catboost@base,ridge,comparables`처럼 등록된 모델(backend/valuation/models)을 같은 시간 분할·같은 보정 규칙으로
비교한다. `이름@base`는 비교사례 변수 없이 기본 변수만 쓰는 변형이다. 모델 선택(챔피언)은 **검증 구간 MAPE**로만 하고
최종 평가 구간은 보고만 한다. `--save-model DIR`은 선택된 모델을 manifest·보정값과 함께 저장한다(운영 연결은 별도 승인 사항).

시간 분할: 학습 < validation_start ≤ 검증 < test_start ≤ 평가 ≤ test_end.
블라인드 입력에는 거래 유형이 없으므로 평가 예측은 중개거래(direct=False)로 가정한다.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean, median

from backend.valuation import models as price_models
from backend.valuation.segments.row_house import ComparableIndex, MarketIndex, Trade, normalize

LEVELS = ("L1", "L2", "L3")
CATEGORICAL = ("lawd", "dong", "house_type")
BASE_NUMERIC = ("floor", "area", "age", "land_ratio", "month", "direct", "index_level")
COMP_NUMERIC = ("l1_count", "l1_median", "l1_area_gap", "l1_days", "l2_count", "l2_median", "block_count", "block_median", "comp_estimate")
FEATURE_SETS = {"full": price_models.FeatureSpec(CATEGORICAL, BASE_NUMERIC + COMP_NUMERIC),
                "base": price_models.FeatureSpec(CATEGORICAL, BASE_NUMERIC)}


@dataclass(frozen=True)
class SegmentConfig:
    regions: tuple[str, ...]
    train_start: str
    validation_start: str
    test_start: str
    test_end: str
    models: tuple[str, ...] = ("catboost", "catboost@base", "comparables")
    iterations: int = 800
    seed: int = 42
    interval: float = .80
    blind_draws: int = 500
    blind_size: int = 20
    # 학습에서만 비교사례 대비 크게 벗어난 거래(지분·특수관계 추정)를 뺀다. 평가 구간은 그대로 둔다.
    train_outlier_log: float = .5


def _ym(day: date) -> str:
    return f"{day.year:04d}{day.month:02d}"


def load_rows(regions: tuple[str, ...], start: str, end: str) -> list[dict]:
    from sqlalchemy import select, text
    from db.base import get_engine
    from db.models import Transaction
    columns = [Transaction.id, Transaction.lawd_cd, Transaction.deal_ym, Transaction.deal_year, Transaction.deal_month,
               Transaction.deal_day, Transaction.price, Transaction.area_sqm, Transaction.floor, Transaction.year_built,
               Transaction.dong, Transaction.jibun, Transaction.land_area_sqm, Transaction.building_use,
               Transaction.transaction_type, Transaction.is_cancelled]
    # 수집·마이그레이션·캐시 쓰기를 하지 않는다. 한 시점의 자료를 모든 모델에 같게 제공한다.
    with get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = connection.execute(select(*columns).where(Transaction.endpoint == "RTMSDataSvcRHTrade",
                Transaction.lawd_cd.in_(regions), Transaction.deal_ym >= start, Transaction.deal_ym <= end)
                .order_by(Transaction.deal_ym, Transaction.id)).mappings().all()
    return [dict(row) for row in rows]


def features(trade: Trade, evidence, index: MarketIndex, origin: int, direct: bool | None = None) -> dict:
    month = trade.day.year * 12 + trade.day.month - 1
    nz = lambda v: float("nan") if v is None else v
    return {
        "lawd": trade.lawd, "dong": trade.dong or "미상", "house_type": trade.house_type,
        "floor": nz(trade.floor), "area": trade.area,
        "age": (trade.day.year - trade.year_built) if trade.year_built else float("nan"),
        "land_ratio": (trade.land_area / trade.area) if trade.land_area else float("nan"),
        "month": month - origin, "direct": float(trade.direct if direct is None else direct),
        "index_level": nz(index.at(trade.lawd, month - 1)),
        "l1_count": evidence.l1_count, "l1_median": nz(evidence.l1_median), "l1_area_gap": nz(evidence.l1_area_gap),
        "l1_days": nz(evidence.l1_days), "l2_count": evidence.l2_count, "l2_median": nz(evidence.l2_median),
        "block_count": evidence.block_count, "block_median": nz(evidence.block_median), "comp_estimate": nz(evidence.estimate),
    }


def _metrics(errors: list[float]) -> dict:
    if not errors:
        return {"n": 0}
    ape = sorted(abs(e) for e in errors)
    return {"n": len(ape), "mape": round(mean(ape), 4), "median_ape": round(median(ape), 4),
            "hit10": round(sum(a <= .10 for a in ape) / len(ape), 4), "hit20": round(sum(a <= .20 for a in ape) / len(ape), 4),
            "p90_ape": round(ape[int(.9 * (len(ape) - 1))], 4)}


def build_parts(rows: list[dict], config: SegmentConfig):
    import pandas as pd
    trades = normalize(rows)
    index = MarketIndex(trades)
    comps = ComparableIndex(trades, index)
    origin = trades[0].day.year * 12 + trades[0].day.month - 1
    records = []
    for trade in trades:
        ym = _ym(trade.day)
        split = None if ym < config.train_start else "train" if ym < config.validation_start else \
            "validation" if ym < config.test_start else "test" if ym <= config.test_end else None
        if split is None:
            continue
        evidence = comps.evidence(trade)
        record = features(trade, evidence, index, origin, direct=False if split == "test" else None)
        record.update(split=split, level=evidence.level, target=trade.log_per_sqm, area_value=trade.area, price=trade.price,
                      id=trade.id, basis=evidence.basis)
        records.append(record)
    frame = pd.DataFrame(records)
    parts = {name: frame[frame.split == name].reset_index(drop=True) for name in ("train", "validation", "test")}
    if min(len(part) for part in parts.values()) < 100:
        raise ValueError(f"구간별 표본이 부족합니다: { {k: len(v) for k, v in parts.items()} }")
    return trades, parts


def assess(spec: str, train, validation, test, config: SegmentConfig) -> tuple[dict, object, dict]:
    """한 모델을 학습·보정·평가한다. 모든 모델이 같은 규칙을 거친다."""
    import numpy as np
    name, _, feature_set = spec.partition("@")
    features_spec = FEATURE_SETS.get(feature_set or "full")
    if features_spec is None:
        raise ValueError(f"알 수 없는 변수 묶음: {feature_set} (full 또는 base)")
    params = {"iterations": config.iterations, "seed": config.seed} if name == "catboost" else {}
    model = price_models.create(name, features_spec, **params).fit(train, validation)
    uses_comps = "comp_estimate" in features_spec.numeric
    # 검증 구간: 검증을 보지 않은 예측으로 단계별 비교사례 혼합 가중치와 잔차 분위수·신뢰도를 정한다.
    val_pred = np.asarray(model.predict_probe(validation), dtype=float)
    target = validation.target.to_numpy()
    weights, residuals = {}, {}
    for level in LEVELS:
        mask = (validation.level == level).to_numpy()
        if not mask.any():
            weights[level], residuals[level] = 0.0, np.array([]); continue
        comp = np.nan_to_num(validation.comp_estimate.to_numpy()[mask], nan=0.0)
        choices = [0.0] if level == "L3" or not uses_comps else [0, .25, .5, .75, 1.0]
        scored = {w: float(np.mean(np.abs(np.exp(target[mask] - (w * comp + (1 - w) * val_pred[mask])) - 1))) for w in choices}
        weights[level] = min(scored, key=scored.get)
        residuals[level] = target[mask] - (weights[level] * comp + (1 - weights[level]) * val_pred[mask])
    alpha = (1 - config.interval) / 2
    bands = {lv: (float(np.quantile(r, alpha)), float(np.quantile(r, 1 - alpha))) if len(r) >= 30 else None for lv, r in residuals.items()}
    confidence = {lv: round(float(np.mean(np.abs(np.exp(r) - 1) <= .10)), 3) if len(r) >= 30 else None for lv, r in residuals.items()}
    validation_mape = round(float(np.mean(np.abs(np.exp(target - val_pred) - 1))), 4)
    # 최종 평가: 학습+검증으로 다시 학습한 모델과 검증에서 정한 가중치·분위수를 그대로 쓴다.
    test_pred = np.asarray(model.predict(test), dtype=float)
    groups, rows_out = defaultdict(list), []
    for i, rec in test.iterrows():
        w, comp = weights[rec.level], rec.comp_estimate
        log_estimate = w * comp + (1 - w) * test_pred[i] if (w and not math.isnan(comp)) else test_pred[i]
        estimate = math.exp(log_estimate) * rec.area_value
        error = estimate / rec.price - 1
        for key in ("all", rec.level, f"region:{rec.lawd}"):
            groups[key].append(error)
        band = bands.get(rec.level)
        low = math.exp(log_estimate + band[0]) * rec.area_value if band else None
        high = math.exp(log_estimate + band[1]) * rec.area_value if band else None
        rows_out.append({"id": int(rec.id), "level": rec.level, "lawd": rec.lawd, "actual": int(rec.price), "estimate": round(estimate),
                         "low": None if low is None else round(low), "high": None if high is None else round(high),
                         "inside": None if low is None else bool(low <= rec.price <= high), "confidence": confidence.get(rec.level),
                         "error": error, "basis": rec.basis})
    coverage = {lv: round(mean(r["inside"] for r in rows_out if r["level"] == lv and r["inside"] is not None), 3)
                if any(r["level"] == lv and r["inside"] is not None for r in rows_out) else None for lv in LEVELS}
    calibration = {lv: {"stated": confidence.get(lv), "observed_hit10": round(mean(abs(r["error"]) <= .10 for r in rows_out if r["level"] == lv), 3)
                        if any(r["level"] == lv for r in rows_out) else None} for lv in LEVELS}
    rng = random.Random(config.seed)
    draws = sorted(mean(abs(r["error"]) for r in rng.sample(rows_out, config.blind_size)) for _ in range(config.blind_draws)) \
        if len(rows_out) >= config.blind_size else []
    result = {"model": spec, "model_name": name, "features": feature_set or "full", "training": model.training,
              "validation_mape": validation_mape, "weights": weights, "interval_log_quantiles": bands, "confidence_by_level": confidence,
              "metrics": {key: _metrics(values) for key, values in sorted(groups.items())},
              "interval_coverage": coverage, "calibration": calibration,
              "blind_simulation": {"draws": len(draws), "size": config.blind_size,
                                   "mape_median": round(median(draws), 4) if draws else None,
                                   "mape_p10": round(draws[int(.1 * (len(draws) - 1))], 4) if draws else None,
                                   "mape_p90": round(draws[int(.9 * (len(draws) - 1))], 4) if draws else None},
              "worst_cases": sorted(rows_out, key=lambda r: -abs(r["error"]))[:15]}
    return result, model, {"weights": weights, "interval_log_quantiles": bands, "confidence_by_level": confidence, "interval": config.interval}


def evaluate(rows: list[dict], config: SegmentConfig) -> tuple[dict, object, dict]:
    if not config.models:
        raise ValueError("비교할 모델을 하나 이상 지정해주세요")
    trades, parts = build_parts(rows, config)
    train = parts["train"]
    gap = (train.target - train.comp_estimate).abs()
    removed = int((gap > config.train_outlier_log).sum())
    train = train[~(gap > config.train_outlier_log)].reset_index(drop=True)
    results, fitted = [], {}
    for spec in config.models:
        result, model, calibration = assess(spec, train, parts["validation"], parts["test"], config)
        results.append(result); fitted[spec] = (model, calibration)
    # 챔피언은 검증 구간 MAPE로만 고른다. 평가 구간 성적으로 고르면 평가가 선택에 새어 들어간다.
    champion = min(results, key=lambda r: r["validation_mape"])["model"]
    report = {"segment": "R-RH", "config": asdict(config), "available_models": price_models.available(),
              "samples": {k: len(v) for k, v in parts.items()}, "level_share": {k: dict(Counter(v.level)) for k, v in parts.items()},
              "train_outliers_removed": removed, "champion_by_validation": champion,
              "comparison": [{"model": r["model"], "validation_mape": r["validation_mape"], **{k: r["metrics"]["all"][k] for k in ("n", "mape", "median_ape", "hit10")},
                              "interval_coverage": r["interval_coverage"], "blind_mape_median": r["blind_simulation"]["mape_median"]} for r in results],
              "results": results,
              "data_sha256": hashlib.sha256(json.dumps([t.id for t in trades]).encode()).hexdigest()}
    model, calibration = fitted[champion]
    return report, model, calibration


def run(args) -> int:
    from dotenv import load_dotenv
    from concierge_workspace import REPO_ROOT
    load_dotenv(REPO_ROOT / ".env", override=False)
    if args.segment != "row_house":
        raise ValueError("현재 오프라인 평가는 row_house(R-RH)만 지원합니다")
    if args.test_end >= datetime.now(timezone.utc).strftime("%Y%m"):
        raise ValueError("진행 중이거나 미래인 월을 최종 평가에 넣을 수 없습니다")
    if not (args.train_start < args.validation_start < args.test_start <= args.test_end):
        raise ValueError("학습 < 검증 < 평가 순서로 월을 지정해주세요")
    specs = tuple(spec.strip() for spec in args.models.split(",") if spec.strip())
    unknown = [spec for spec in specs if spec.partition("@")[0] not in price_models.available()]
    if unknown:
        raise ValueError(f"등록되지 않은 모델: {unknown} (사용 가능: {price_models.available()})")
    config = SegmentConfig(tuple(args.regions), args.train_start, args.validation_start, args.test_start, args.test_end,
                           models=specs, iterations=args.iterations, seed=args.seed)
    # 비교사례는 학습 시작 이전 거래도 근거로 써야 하므로 24개월 앞부터 읽는다.
    start_month = int(args.train_start[:4]) * 12 + int(args.train_start[4:]) - 1 - 24
    rows = load_rows(config.regions, f"{start_month // 12:04d}{start_month % 12 + 1:02d}", args.test_end)
    report, model, calibration = evaluate(rows, config)
    directory = Path(args.output) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-avm-segment-row_house")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if args.save_model:
        price_models.save(model, Path(args.save_model), {"segment": "R-RH", "calibration": calibration, "split": asdict(config),
                                                        "data_sha256": report["data_sha256"], "deployment": "evaluation_only"})
    print(json.dumps({"champion_by_validation": report["champion_by_validation"], "comparison": report["comparison"],
                      "report": str(directory / "result.json"), "saved_model": args.save_model or None, "deployment": "evaluation_only"},
                     ensure_ascii=False, indent=1))
    return 0
