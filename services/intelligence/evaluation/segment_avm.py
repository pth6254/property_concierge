"""세그먼트 AVM 오프라인 평가 (현재 R-RH: 연립·다세대).

같은 시간 분할에서 ① 비교사례만 ② CatBoost만 ③ 혼합형을 비교하고, 근거 단계(L1~L3)별 상·하한과 신뢰도를
검증 구간 잔차로 보정한 뒤 최종 평가 구간에서 측정한다. 저장소는 읽기 전용이며 서비스 모델을 바꾸지 않는다.

시간 분할: 학습 < validation_start ≤ 검증 < test_start ≤ 평가 ≤ test_end. 보정·가중치·반복 수는 검증으로만 정한다.
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
from statistics import mean, median

from backend.valuation.segments.row_house import ComparableIndex, MarketIndex, Trade, normalize

LEVELS = ("L1", "L2", "L3")
CATEGORICAL = ["lawd", "dong", "house_type"]
BASE_NUMERIC = ["floor", "area", "age", "land_ratio", "month", "direct", "index_level"]
COMP_NUMERIC = ["l1_count", "l1_median", "l1_area_gap", "l1_days", "l2_count", "l2_median", "block_count", "block_median", "comp_estimate"]


@dataclass(frozen=True)
class SegmentConfig:
    regions: tuple[str, ...]
    train_start: str
    validation_start: str
    test_start: str
    test_end: str
    iterations: int = 800
    seed: int = 42
    interval: float = .80
    blind_draws: int = 500
    blind_size: int = 20
    # 학습에서만 비교사례 대비 크게 벗어난 거래(지분·특수관계 추정)를 뺀다. 평가 구간은 그대로 둔다.
    train_outlier_log: float = .5
    losses: tuple[str, ...] = ("RMSE", "MAE")


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
    # 수집·마이그레이션·캐시 쓰기를 하지 않는다. 한 시점의 자료를 모든 방식에 같게 제공한다.
    with get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = connection.execute(select(*columns).where(Transaction.endpoint == "RTMSDataSvcRHTrade",
                Transaction.lawd_cd.in_(regions), Transaction.deal_ym >= start, Transaction.deal_ym <= end)
                .order_by(Transaction.deal_ym, Transaction.id)).mappings().all()
    return [dict(row) for row in rows]


def features(trade: Trade, evidence, index: MarketIndex, origin: int, direct: bool | None = None) -> dict:
    month = trade.day.year * 12 + trade.day.month - 1
    return {
        "lawd": trade.lawd, "dong": trade.dong or "미상", "house_type": trade.house_type,
        "floor": trade.floor if trade.floor is not None else float("nan"), "area": trade.area,
        "age": (trade.day.year - trade.year_built) if trade.year_built else float("nan"),
        "land_ratio": (trade.land_area / trade.area) if trade.land_area else float("nan"),
        "month": month - origin, "direct": float(trade.direct if direct is None else direct),
        "index_level": index.at(trade.lawd, month - 1) or float("nan"),
        "l1_count": evidence.l1_count, "l1_median": evidence.l1_median if evidence.l1_median is not None else float("nan"),
        "l1_area_gap": evidence.l1_area_gap if evidence.l1_area_gap is not None else float("nan"),
        "l1_days": evidence.l1_days if evidence.l1_days is not None else float("nan"),
        "l2_count": evidence.l2_count, "l2_median": evidence.l2_median if evidence.l2_median is not None else float("nan"),
        "block_count": evidence.block_count, "block_median": evidence.block_median if evidence.block_median is not None else float("nan"),
        "comp_estimate": evidence.estimate if evidence.estimate is not None else float("nan"),
    }


def _fit(frame, target, columns, valid_frame, valid_target, config, loss="RMSE"):
    from catboost import CatBoostRegressor, Pool
    cats = [c for c in CATEGORICAL if c in columns]
    model = CatBoostRegressor(iterations=config.iterations, depth=6, learning_rate=.05, loss_function=loss, eval_metric="MAE",
                              random_seed=config.seed, verbose=False, allow_writing_files=False, od_type="Iter", od_wait=60)
    model.fit(Pool(frame[columns], target, cat_features=cats), eval_set=Pool(valid_frame[columns], valid_target, cat_features=cats),
              use_best_model=True)
    best = max(model.get_best_iteration() or 0, 50)
    # 반복 수만 검증으로 정하고, 학습+검증 자료로 다시 학습한다. 평가 구간은 전달하지 않는다.
    import pandas as pd
    final = CatBoostRegressor(iterations=best + 1, depth=6, learning_rate=.05, loss_function=loss,
                              random_seed=config.seed, verbose=False, allow_writing_files=False)
    joined = pd.concat([frame[columns], valid_frame[columns]])
    final.fit(Pool(joined, pd.concat([target, valid_target]), cat_features=cats))
    return model, final, best


def _metrics(errors: list[float]) -> dict:
    if not errors:
        return {"n": 0}
    ape = [abs(e) for e in errors]
    return {"n": len(ape), "mape": round(mean(ape), 4), "median_ape": round(median(ape), 4),
            "hit10": round(sum(a <= .10 for a in ape) / len(ape), 4), "hit20": round(sum(a <= .20 for a in ape) / len(ape), 4),
            "p90_ape": round(sorted(ape)[int(.9 * (len(ape) - 1))], 4)}


def evaluate(rows: list[dict], config: SegmentConfig) -> dict:
    import numpy as np
    import pandas as pd
    trades = normalize(rows)
    index = MarketIndex(trades)
    comps = ComparableIndex(trades, index)
    first = trades[0].day
    origin = first.year * 12 + first.month - 1
    records = []
    for trade in trades:
        ym = _ym(trade.day)
        if ym < config.train_start:
            continue
        split = "train" if ym < config.validation_start else "validation" if ym < config.test_start else "test" if ym <= config.test_end else None
        if split is None:
            continue
        evidence = comps.evidence(trade)
        # 평가 구간은 블라인드 입력처럼 거래 유형을 모른다고 보고 중개거래로 예측한다.
        record = features(trade, evidence, index, origin, direct=False if split == "test" else None)
        record.update(split=split, level=evidence.level, target=trade.log_per_sqm, area_value=trade.area, price=trade.price,
                      id=trade.id, basis=evidence.basis)
        records.append(record)
    frame = pd.DataFrame(records)
    parts = {name: frame[frame.split == name].reset_index(drop=True) for name in ("train", "validation", "test")}
    if min(len(parts["train"]), len(parts["validation"]), len(parts["test"])) < 100:
        raise ValueError(f"구간별 표본이 부족합니다: { {k: len(v) for k, v in parts.items()} }")
    base_cols, full_cols = CATEGORICAL + BASE_NUMERIC, CATEGORICAL + BASE_NUMERIC + COMP_NUMERIC
    train = parts["train"]
    gap = (train.target - train.comp_estimate).abs()
    removed = int((gap > config.train_outlier_log).sum())
    train = train[~(gap > config.train_outlier_log)].reset_index(drop=True)
    val_part = parts["validation"]
    def val_mape(probe, cols):
        return float(np.mean(np.abs(np.exp(val_part.target.to_numpy() - probe.predict(val_part[cols])) - 1)))
    # 손실 함수는 검증 MAPE로만 고른다.
    selection = {}
    for loss in config.losses:
        probe, model, iters = _fit(train, train.target, full_cols, val_part, val_part.target, config, loss)
        selection[loss] = (val_mape(probe, full_cols), probe, model, iters)
    chosen = min(selection, key=lambda k: selection[k][0])
    _, hy_probe, hy_model, hy_iter = selection[chosen]
    ml_probe, ml_model, ml_iter = _fit(train, train.target, base_cols, val_part, val_part.target, config, chosen)
    validation_report = {"loss_validation_mape": {k: round(v[0], 4) for k, v in selection.items()}, "chosen_loss": chosen,
                         "train_outliers_removed": removed, "ml_only_validation_mape": round(val_mape(ml_probe, base_cols), 4)}

    def predictions(part, probe: bool):
        ml = (ml_probe if probe else ml_model).predict(part[base_cols])
        hy = (hy_probe if probe else hy_model).predict(part[full_cols])
        return np.asarray(ml), np.asarray(hy)

    # 검증 구간: 학습만으로 학습한 모델(probe)의 예측으로 단계별 혼합 가중치와 잔차 분위수를 정한다.
    val = parts["validation"]
    val_ml, val_hy = predictions(val, probe=True)
    weights, residuals = {}, {}
    for level in LEVELS:
        mask = (val.level == level).to_numpy()
        if not mask.any():
            weights[level] = 0.0; residuals[level] = np.array([]); continue
        comp = val.comp_estimate.to_numpy()[mask]
        best, best_err = 0.0, math.inf
        for w in ([0.0] if level == "L3" else [0, .25, .5, .75, 1.0]):
            est = w * np.nan_to_num(comp, nan=0) + (1 - w) * val_hy[mask] if w else val_hy[mask]
            err = np.mean(np.abs(np.exp(val.target.to_numpy()[mask] - est) - 1))
            if err < best_err:
                best, best_err = w, err
        weights[level] = best
        est = best * np.nan_to_num(comp, nan=0) + (1 - best) * val_hy[mask] if best else val_hy[mask]
        residuals[level] = val.target.to_numpy()[mask] - est
    alpha = (1 - config.interval) / 2
    bands = {level: (float(np.quantile(r, alpha)), float(np.quantile(r, 1 - alpha))) if len(r) >= 30 else None for level, r in residuals.items()}
    confidence = {level: round(float(np.mean(np.abs(np.exp(r) - 1) <= .10)), 3) if len(r) >= 30 else None for level, r in residuals.items()}

    # 최종 평가: 학습+검증으로 다시 학습한 모델과 검증에서 정한 가중치·분위수를 그대로 쓴다.
    test = parts["test"]
    test_ml, test_hy = predictions(test, probe=False)
    rows_out, by = [], defaultdict(lambda: defaultdict(list))
    for i, rec in test.iterrows():
        level, actual = rec.level, rec.price
        comp = rec.comp_estimate
        w = weights[level]
        hybrid_log = (w * comp + (1 - w) * test_hy[i]) if (w and not math.isnan(comp)) else test_hy[i]
        estimates = {"comparables": None if math.isnan(comp) else math.exp(comp) * rec.area_value,
                     "ml_only": math.exp(test_ml[i]) * rec.area_value, "hybrid": math.exp(hybrid_log) * rec.area_value}
        for name, value in estimates.items():
            if value is not None:
                by[name]["all"].append(value / actual - 1); by[name][level].append(value / actual - 1)
                by[name][f"region:{rec.lawd}"].append(value / actual - 1)
        band = bands.get(level)
        low = math.exp(hybrid_log + band[0]) * rec.area_value if band else None
        high = math.exp(hybrid_log + band[1]) * rec.area_value if band else None
        rows_out.append({"id": int(rec.id), "level": level, "lawd": rec.lawd, "actual": int(actual), "estimate": round(estimates["hybrid"]),
                         "low": None if low is None else round(low), "high": None if high is None else round(high),
                         "inside": None if low is None else bool(low <= actual <= high), "confidence": confidence.get(level),
                         "error": estimates["hybrid"] / actual - 1, "basis": rec.basis})
    metrics = {name: {key: _metrics(values) for key, values in sorted(groups.items())} for name, groups in by.items()}
    coverage = {level: round(mean(r["inside"] for r in rows_out if r["level"] == level and r["inside"] is not None), 3)
                if any(r["level"] == level and r["inside"] is not None for r in rows_out) else None for level in LEVELS}
    calibration = {level: {"stated": confidence.get(level),
                           "observed_hit10": round(mean(abs(r["error"]) <= .10 for r in rows_out if r["level"] == level), 3)
                           if any(r["level"] == level for r in rows_out) else None} for level in LEVELS}
    # 과제처럼 평가 구간에서 20건을 무작위로 여러 번 뽑아 MAPE 분포를 본다.
    rng = random.Random(config.seed)
    draws = [mean(abs(r["error"]) for r in rng.sample(rows_out, config.blind_size)) for _ in range(config.blind_draws)] if len(rows_out) >= config.blind_size else []
    blind = {"draws": len(draws), "size": config.blind_size,
             "mape_median": round(median(draws), 4) if draws else None,
             "mape_p10": round(sorted(draws)[int(.1 * (len(draws) - 1))], 4) if draws else None,
             "mape_p90": round(sorted(draws)[int(.9 * (len(draws) - 1))], 4) if draws else None}
    importance = dict(sorted(zip(full_cols, (round(float(v), 2) for v in hy_model.get_feature_importance())), key=lambda kv: -kv[1]))
    return {
        "segment": "R-RH", "config": asdict(config),
        "samples": {k: len(v) for k, v in parts.items()}, "level_share": {k: dict(Counter(v.level)) for k, v in parts.items()},
        "weights": weights, "interval_log_quantiles": bands, "confidence_by_level": confidence,
        "iterations": {"ml_only": ml_iter, "hybrid": hy_iter}, "validation": validation_report,
        "metrics": metrics, "interval_coverage": coverage, "calibration": calibration, "blind_simulation": blind,
        "feature_importance": importance,
        "worst_cases": sorted(rows_out, key=lambda r: -abs(r["error"]))[:15],
        "data_sha256": hashlib.sha256(json.dumps([t.id for t in trades]).encode()).hexdigest(),
    }


def run(args) -> int:
    from pathlib import Path
    from dotenv import load_dotenv
    from concierge_workspace import REPO_ROOT
    load_dotenv(REPO_ROOT / ".env", override=False)
    if args.segment != "row_house":
        raise ValueError("현재 오프라인 평가는 row_house(R-RH)만 지원합니다")
    if args.test_end >= datetime.now(timezone.utc).strftime("%Y%m"):
        raise ValueError("진행 중이거나 미래인 월을 최종 평가에 넣을 수 없습니다")
    if not (args.train_start < args.validation_start < args.test_start <= args.test_end):
        raise ValueError("학습 < 검증 < 평가 순서로 월을 지정해주세요")
    config = SegmentConfig(tuple(args.regions), args.train_start, args.validation_start, args.test_start, args.test_end,
                           iterations=args.iterations, seed=args.seed)
    # 비교사례는 학습 시작 이전 거래도 근거로 써야 하므로 24개월 앞부터 읽는다.
    start_month = int(args.train_start[:4]) * 12 + int(args.train_start[4:]) - 1 - 24
    rows = load_rows(config.regions, f"{start_month // 12:04d}{start_month % 12 + 1:02d}", args.test_end)
    result = evaluate(rows, config)
    directory = Path(args.output) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-avm-segment-row_house")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("samples", "level_share", "weights", "validation", "interval_coverage", "calibration", "blind_simulation")}
                     | {"metrics_all": {name: groups.get("all") for name, groups in result["metrics"].items()},
                        "metrics_hybrid_by_level": {lv: result["metrics"]["hybrid"].get(lv) for lv in LEVELS},
                        "report": str(directory / "result.json"), "deployment": "evaluation_only"}, ensure_ascii=False, indent=1))
    return 0
