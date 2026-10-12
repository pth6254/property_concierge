"""비교사례를 변수로 넣은 가격 모델(기본 CatBoost, 교체 가능) 학습·보정·예측.

- 타깃: ㎡당 가격의 자연로그. 가격 = exp(예측) × 전용면적.
- 학습 이상치: 학습 구간에서만 비교사례 대비 로그 0.5(약 ±40~65%) 이상 벗어난 거래를 뺀다(지분·특수관계 추정).
- 반복 수: 마지막 검증 구간으로 조기 종료해 정하고, 학습+검증 전체로 다시 학습한다.
- 구간·신뢰도: 검증 구간 잔차를 근거 버킷(L1a/L1b/L2/L3)별로 집계한다. 표본 30건 미만 버킷은 상위 버킷 값을 쓴다.
  구간은 85% 명목 분위수(7.5%~92.5%)로 잡는다. 이전 기간 점검에서 80% 명목 구간의 실제 적중이 72~77%로 낮았기 때문이다.
  신뢰도 = 해당 버킷의 검증 구간 ±10% 적중률(모델이 스스로 매기는 값, 0~1).
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path

import numpy as np

from rh_avm.price_models import registry as price_models
from rh_avm.core import ComparableIndex, Evidence, MarketIndex, Trade, month_of

CATEGORICAL = ["lawd", "dong", "house_type"]
NUMERIC = ["floor", "area", "age", "land_ratio", "month", "direct", "index_level",
           "l1_count", "l1_median", "l1_area_gap", "l1_days", "l2_count", "l2_median", "block_count", "block_median", "comp_estimate"]
COLUMNS = CATEGORICAL + NUMERIC
FEATURES = price_models.FeatureSpec(tuple(CATEGORICAL), tuple(NUMERIC))
NAN = float("nan")
OUTLIER_LOG = .5
INTERVAL = (.075, .925)
# L3는 검증 표본이 적어 ALL보다 보수적인 L2 값을 빌린다(근거가 가장 약한 단계가 평균보다 높은 신뢰도를 받지 않게).
PARENT = {"L1a": "L1", "L1b": "L1", "L1": "ALL", "L2": "ALL", "L3": "L2"}


def bucket(evidence: Evidence) -> str:
    if evidence.level == "L1":
        return "L1a" if evidence.l1_count >= 3 else "L1b"
    return evidence.level


def features(trade: Trade, evidence: Evidence, index: MarketIndex, origin: int, month: int, direct: bool) -> dict:
    nz = lambda v: NAN if v is None else v
    return {"lawd": trade.lawd, "dong": trade.dong or "미상", "house_type": trade.house_type,
            "floor": nz(trade.floor), "area": trade.area,
            "age": NAN if not trade.year_built else (month // 12) - trade.year_built,
            "land_ratio": NAN if not trade.land_area else trade.land_area / trade.area,
            "month": month - origin, "direct": float(direct), "index_level": nz(index.at(trade.lawd, month - 1)),
            "l1_count": evidence.l1_count, "l1_median": nz(evidence.l1_median), "l1_area_gap": nz(evidence.l1_area_gap),
            "l1_days": nz(evidence.l1_days), "l2_count": evidence.l2_count, "l2_median": nz(evidence.l2_median),
            "block_count": evidence.block_count, "block_median": nz(evidence.block_median), "comp_estimate": nz(evidence.estimate)}


def build_records(trades: list[Trade], start: date, end: date, *, blind_after: date | None = None):
    """start~end 거래마다 '그 거래일 이전 자료만으로' 근거와 변수를 만든다. blind_after 이후 거래는 중개거래로 가정한다."""
    import pandas as pd
    index = MarketIndex(trades)
    comps = ComparableIndex(trades, index)
    origin = month_of(trades[0].day)
    rows = []
    for t in trades:
        if not (start <= t.day <= end):
            continue
        evidence = comps.evidence(t, t.day)
        direct = False if blind_after and t.day >= blind_after else t.direct
        record = features(t, evidence, index, origin, month_of(t.day), direct)
        record.update(target=t.log_per_sqm, price=t.price, area_value=t.area, day=t.day, level=evidence.level,
                      bucket=bucket(evidence), basis=evidence.basis, id=t.id, lawd_code=t.lawd)
        rows.append(record)
    return pd.DataFrame(rows), index, comps, origin


def calibrate(validation, predicted) -> dict:
    import numpy as np
    residual = validation["target"].to_numpy() - predicted
    groups = {"ALL": residual}
    groups["L1"] = residual[(validation["level"] == "L1").to_numpy()]
    for name in ("L1a", "L1b", "L2", "L3"):
        groups[name] = residual[(validation["bucket"] == name).to_numpy()]
    out = {}
    for name in ("ALL", "L1", "L1a", "L1b", "L2", "L3"):
        values, source = groups[name], name
        while len(values) < 30 and source != "ALL":
            source = PARENT[source]; values = groups[source]
        out[name] = {"n": int(len(groups[name])), "source": source,
                     "low": float(np.quantile(values, INTERVAL[0])), "high": float(np.quantile(values, INTERVAL[1])),
                     "confidence": round(float(np.mean(np.abs(np.exp(values) - 1) <= .10)), 3)}
    return out


def train(trades: list[Trade], train_start: date, validation_start: date, end: date, seed: int = 42,
          model_name: str = "catboost", model_params: dict | None = None):
    """train_start~validation_start 전날 학습, validation_start~end 검증. 가격 모델은 이름으로 고른다(rh_avm.price_models 등록표).

    모델은 학습 이상치를 뺀 학습·검증 자료로 학습하고(검증은 조기 종료·선택용), 구간·신뢰도는
    검증 자료 전체에 대한 '검증을 보지 않은 예측'(predict_probe)의 잔차로 보정한다.
    """
    frame, _, _, origin = build_records(trades, train_start, end)
    train_part = frame[frame.day < validation_start]
    validation = frame[frame.day >= validation_start].reset_index(drop=True)
    gap = (train_part.target - train_part.comp_estimate).abs()
    removed = int((gap > OUTLIER_LOG).sum())
    train_part = train_part[~(gap > OUTLIER_LOG)].reset_index(drop=True)
    val_gap = (validation.target - validation.comp_estimate).abs()
    params = ({"seed": seed} if model_name == "catboost" else {}) | (model_params or {})
    model = price_models.create(model_name, FEATURES, **params)
    model.fit(train_part, validation[~(val_gap > OUTLIER_LOG)].reset_index(drop=True))
    predicted = model.predict_probe(validation)
    calibration = calibrate(validation, predicted)
    meta = {"origin_month": origin, "calibration": calibration, "interval_quantiles": INTERVAL,
            "train_rows": int(len(train_part)), "validation_rows": int(len(validation)), "train_outliers_removed": removed,
            "train_start": train_start.isoformat(), "validation_start": validation_start.isoformat(), "end": end.isoformat(),
            "seed": seed, "validation_mape": round(float(abs(np.exp(validation.target.to_numpy() - predicted) - 1).mean()), 4)}
    return model, meta, validation, predicted


def save(model, meta: dict, directory: Path, data_path: Path) -> None:
    """모델 파일과 manifest(model/model.json)를 저장한다. manifest에 모델 이름이 있어 predict가 같은 구현으로 읽는다."""
    for old in directory.glob("*") if directory.exists() else []:
        old.unlink()  # 이전 모델 파일이 남아 다른 구현과 섞이지 않게 비운다
    price_models.save(model, directory, {"avm": meta, "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest()})


def load(directory: Path):
    model, manifest = price_models.load(directory)
    return model, manifest["avm"] | {"model": manifest["model"], "model_version": manifest["model_version"], "training": manifest["training"]}


def interval(log_estimate: float, area: float, calibration: dict, name: str, widen: float = 0.0):
    band = calibration.get(name) or calibration["ALL"]
    low = math.exp(log_estimate + band["low"] - widen) * area
    high = math.exp(log_estimate + band["high"] + widen) * area
    return low, high, band["confidence"]
