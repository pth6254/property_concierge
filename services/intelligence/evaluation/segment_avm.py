"""세그먼트 AVM 오프라인 평가 (R-RH 연립·다세대, R-APT 아파트). 가격 모델은 교체 가능하다.

`--models catboost,catboost@base,ridge,comparables`처럼 등록된 모델(backend/valuation/models)을 같은 시간 분할·같은 보정 규칙으로
비교한다. `이름@base`는 비교사례 변수 없이 기본 변수만 쓰는 변형이다. 모델 선택(챔피언)은 **검증 구간 MAPE**로만 하고
최종 평가 구간은 보고만 한다. `--save-model DIR`은 선택된 모델을 manifest·보정값과 함께 저장한다(운영 연결은 별도 승인 사항).

시간 분할: 학습 < validation_start ≤ 검증 < test_start ≤ 평가 ≤ test_end.
블라인드 입력에는 거래 유형이 없으므로 평가 예측은 중개거래(direct=False)로 가정한다.
세그먼트마다 근거 단계가 다르다. 가격을 내지 않는 단계(아파트 A4)는 오차가 아니라 **보류율**로 따로 보고한다.
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
from typing import Callable

from backend.valuation import models as price_models
from backend.valuation.segments import apartment as apt
from backend.valuation.segments import row_house as rh


@dataclass(frozen=True)
class SegmentSpec:
    id: str
    endpoint: str
    levels: tuple[str, ...]
    no_comp_levels: frozenset[str]       # 비교사례 혼합 가중치를 쓰지 않는 단계
    withheld_levels: frozenset[str]      # 가격을 내지 않는 단계(보류율로 보고)
    feature_sets: dict
    history_months: int                  # 학습 시작 전 비교사례용으로 더 읽는 기간
    prepare: Callable                    # rows -> (trades, records_fn)


def _rh_prepare(rows):
    trades = rh.normalize(rows)
    index = rh.MarketIndex(trades)
    comps = rh.ComparableIndex(trades, index)
    origin = trades[0].day.year * 12 + trades[0].day.month - 1
    def record(trade, direct):
        evidence = comps.evidence(trade)
        return evidence, _rh_features(trade, evidence, index, origin, direct), {}
    return trades, record


def _rh_features(trade, evidence, index, origin, direct=None) -> dict:
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


def _apt_prepare(rows):
    trades = apt.normalize(rows)
    index = rh.MarketIndex(trades)
    comps = apt.ComparableIndex(trades, index)
    origin = trades[0].day.year * 12 + trades[0].day.month - 1
    def record(trade, direct):
        subject = apt.Subject(trade.lawd, trade.dong, trade.complex, trade.area, trade.floor, trade.year_built, trade.day, trade.id)
        evidence = comps.evidence(subject)
        values = apt.features(subject, evidence, index, origin, direct=trade.direct if direct is None else direct,
                              year_built=comps.complex_year(trade.complex))
        # 현재 서비스 규칙 재현용: A1 사례의 시점 보정 ㎡당 가격 산술평균 × 면적 (calc_estimated_value와 같은 방식)
        extra = {}
        if evidence.level == "A1":
            cutoff = trade.day
            a1 = [t for t in comps.by_complex[trade.complex] if t.id != trade.id and cutoff.toordinal() - apt.A1_DAYS <= t.day.toordinal() < cutoff.toordinal()
                  and abs(t.area / trade.area - 1) <= apt.A1_AREA + 1e-6]
            extra["service_rule"] = mean(math.exp(t.log_per_sqm + index.adjust(t.lawd, t.day, cutoff)) for t in a1) * trade.area
        return evidence, values, extra
    return trades, record


SEGMENTS = {
    "row_house": SegmentSpec("R-RH", "RTMSDataSvcRHTrade", ("L1", "L2", "L3"), frozenset({"L3"}), frozenset(),
        {"full": price_models.FeatureSpec(("lawd", "dong", "house_type"), ("floor", "area", "age", "land_ratio", "month", "direct", "index_level",
                                          "l1_count", "l1_median", "l1_area_gap", "l1_days", "l2_count", "l2_median", "block_count", "block_median", "comp_estimate")),
         "base": price_models.FeatureSpec(("lawd", "dong", "house_type"), ("floor", "area", "age", "land_ratio", "month", "direct", "index_level"))},
        24, _rh_prepare),
    "apartment": SegmentSpec("R-APT", "RTMSDataSvcAptTrade", apt.LEVELS, frozenset({"A4"}), frozenset({"A4"}),
        {"full": price_models.FeatureSpec(apt.CATEGORICAL, apt.BASE_NUMERIC + apt.COMP_NUMERIC),
         "base": price_models.FeatureSpec(apt.CATEGORICAL, apt.BASE_NUMERIC)},
        12, _apt_prepare),
}
# 기존 호출(테스트 포함)의 기본값은 연립·다세대다.
LEVELS = SEGMENTS["row_house"].levels
FEATURE_SETS = SEGMENTS["row_house"].feature_sets


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
    segment: str = "row_house"
    # 구간 보정 단위: level(근거 단계별) 또는 price(근거 단계 × 추정가 5분위, 30건 미만 칸은 근거 단계 값)
    band_by: str = "level"
    keep_rows: bool = False


def _ym(day: date) -> str:
    return f"{day.year:04d}{day.month:02d}"


def load_rows(regions: tuple[str, ...], start: str, end: str, endpoint: str = "RTMSDataSvcRHTrade") -> list[dict]:
    from sqlalchemy import select, text
    from db.base import get_engine
    from db.models import Transaction
    columns = [Transaction.id, Transaction.lawd_cd, Transaction.deal_ym, Transaction.deal_year, Transaction.deal_month,
               Transaction.deal_day, Transaction.price, Transaction.area_sqm, Transaction.floor, Transaction.year_built,
               Transaction.dong, Transaction.jibun, Transaction.land_area_sqm, Transaction.building_use,
               Transaction.transaction_type, Transaction.is_cancelled, Transaction.apt_name]
    # 수집·마이그레이션·캐시 쓰기를 하지 않는다. 한 시점의 자료를 모든 모델에 같게 제공한다.
    with get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = connection.execute(select(*columns).where(Transaction.endpoint == endpoint,
                Transaction.lawd_cd.in_(regions), Transaction.deal_ym >= start, Transaction.deal_ym <= end)
                .order_by(Transaction.deal_ym, Transaction.id)).mappings().all()
    return [dict(row) for row in rows]


def features(trade, evidence, index, origin: int, direct: bool | None = None) -> dict:
    """연립·다세대 변수(이전 호출 호환)."""
    return _rh_features(trade, evidence, index, origin, direct)


def _metrics(errors: list[float]) -> dict:
    if not errors:
        return {"n": 0}
    ape = sorted(abs(e) for e in errors)
    # bias: 부호 있는 평균 오차. 음수면 실제보다 낮게 추정한다(고가 단지 하향 편향 확인용).
    return {"n": len(ape), "mape": round(mean(ape), 4), "median_ape": round(median(ape), 4), "bias": round(mean(errors), 4),
            "hit10": round(sum(a <= .10 for a in ape) / len(ape), 4), "hit20": round(sum(a <= .20 for a in ape) / len(ape), 4),
            "p90_ape": round(ape[int(.9 * (len(ape) - 1))], 4)}


def build_frame(rows: list[dict], segment_name: str, start: str = "000000"):
    """모든 거래의 근거·변수를 한 번만 계산한다. 근거는 각 거래일 이전 거래만 쓰므로 기간 분할과 무관하다."""
    import pandas as pd
    trades, record_for = SEGMENTS[segment_name].prepare(rows)
    records = []
    for trade in trades:
        ym = _ym(trade.day)
        if ym < start:
            continue
        evidence, record, extra = record_for(trade, None)
        record.update(ym=ym, level=evidence.level, target=trade.log_per_sqm, area_value=trade.area, price=trade.price,
                      id=trade.id, basis=evidence.basis, **extra)
        records.append(record)
    return trades, pd.DataFrame(records)


def split_parts(frame, config: SegmentConfig) -> dict:
    """학습 < 검증 < 평가 월로 나눈다. 블라인드 입력에는 거래 유형이 없으므로 평가 구간은 중개거래로 둔다."""
    ym = frame.ym
    parts = {"train": frame[(ym >= config.train_start) & (ym < config.validation_start)],
             "validation": frame[(ym >= config.validation_start) & (ym < config.test_start)],
             "test": frame[(ym >= config.test_start) & (ym <= config.test_end)].assign(direct=0.0)}
    parts = {name: part.reset_index(drop=True) for name, part in parts.items()}
    required = ("train", "validation") if config.test_start > config.test_end else ("train", "validation", "test")
    if min(len(parts[name]) for name in required) < 100:
        raise ValueError(f"구간별 표본이 부족합니다: { {k: len(v) for k, v in parts.items()} }")
    return parts


def build_parts(rows: list[dict], config: SegmentConfig):
    trades, frame = build_frame(rows, config.segment, config.train_start)
    return trades, split_parts(frame, config)


def train_final(rows: list[dict], config: SegmentConfig, spec: str) -> tuple[object, dict]:
    """서비스용 최종 학습. 평가 구간 없이 마지막 완료월(검증)로 반복 수·혼합 가중치·구간·신뢰도를 정하고 학습+검증으로 다시 학습한다.

    성능 판단은 같은 규칙의 시간 분할 평가(evaluate)로 따로 끝낸 뒤에만 이 산출물을 쓴다.
    """
    import numpy as np
    segment = SEGMENTS[config.segment]
    trades, parts = build_parts(rows, config)
    train = parts["train"]
    gap = (train.target - train.comp_estimate).abs()
    train = train[~(gap > config.train_outlier_log)].reset_index(drop=True)
    empty = parts["validation"].iloc[0:0]
    result, model, calibration = assess(spec, train, parts["validation"], empty, config)
    origin = trades[0].day.year * 12 + trades[0].day.month - 1
    last = max(t.day for t in trades)
    return model, {"segment": segment.id, "calibration": calibration, "feature_origin_month": origin,
                   "history_months": segment.history_months, "trained_through": last.isoformat(),
                   "validation_mape": result["validation_mape"], "levels": list(segment.levels),
                   "withheld_levels": sorted(segment.withheld_levels), "split": asdict(config),
                   "data_sha256": hashlib.sha256(json.dumps([t.id for t in trades]).encode()).hexdigest()}


def assess(spec: str, train, validation, test, config: SegmentConfig) -> tuple[dict, object, dict]:
    """한 모델을 학습·보정·평가한다. 모든 모델이 같은 규칙을 거친다."""
    import numpy as np
    segment = SEGMENTS[config.segment]
    levels = [lv for lv in segment.levels if lv not in segment.withheld_levels]
    name, _, feature_set = spec.partition("@")
    # resid: 전체 변수를 쓰되 타깃을 "비교사례 값 대비 차이"로 둔다. 모델이 절대 가격 수준을 평균 쪽으로 끌어내리지 않고
    # 층·면적·시점 차이만 보정하게 하려는 변형이다. 비교사례가 없는 단계를 산출하는 세그먼트(R-RH L3)에는 쓸 수 없다.
    residual = feature_set == "resid"
    features_spec = segment.feature_sets.get("full" if residual else (feature_set or "full"))
    if features_spec is None:
        raise ValueError(f"알 수 없는 변수 묶음: {feature_set} (full, base, resid)")
    if residual and set(segment.no_comp_levels) - set(segment.withheld_levels):
        raise ValueError(f"{segment.id}는 비교사례 없이 산출하는 단계가 있어 잔차 학습을 쓸 수 없습니다")
    params = {"iterations": config.iterations, "seed": config.seed} if name == "catboost" else {}
    def fit_frame(frame):
        if not residual:
            return frame
        kept = frame[frame.comp_estimate.notna()].reset_index(drop=True)
        return kept.assign(target=kept.target - kept.comp_estimate)
    def to_log(frame, predicted):
        predicted = np.asarray(predicted, dtype=float)
        return frame.comp_estimate.to_numpy(dtype=float) + predicted if residual else predicted
    model = price_models.create(name, features_spec, **params).fit(fit_frame(train), fit_frame(validation))
    uses_comps = "comp_estimate" in features_spec.numeric
    # 검증 구간: 검증을 보지 않은 예측으로 단계별 비교사례 혼합 가중치와 잔차 분위수·신뢰도를 정한다.
    val_pred = to_log(validation, model.predict_probe(validation))
    target = validation.target.to_numpy()
    weights, residuals = {}, {}
    val_log = np.full(len(validation), np.nan)
    for level in levels:
        mask = (validation.level == level).to_numpy()
        if not mask.any():
            weights[level], residuals[level] = 0.0, np.array([]); continue
        comp = np.nan_to_num(validation.comp_estimate.to_numpy()[mask], nan=0.0)
        choices = [0.0] if level in segment.no_comp_levels or not uses_comps else [0, .25, .5, .75, 1.0]
        scored = {w: float(np.mean(np.abs(np.exp(target[mask] - (w * comp + (1 - w) * val_pred[mask])) - 1))) for w in choices}
        weights[level] = min(scored, key=scored.get)
        val_log[mask] = weights[level] * comp + (1 - weights[level]) * val_pred[mask]
        residuals[level] = target[mask] - val_log[mask]
    alpha = (1 - config.interval) / 2
    bands = {lv: (float(np.quantile(r, alpha)), float(np.quantile(r, 1 - alpha))) if len(r) >= 30 else None for lv, r in residuals.items()}
    confidence = {lv: round(float(np.mean(np.abs(np.exp(r) - 1) <= .10)), 3) if len(r) >= 30 else None for lv, r in residuals.items()}
    # 추정가 가격대별 보정: 같은 근거 단계라도 가격대마다 불확실성이 다르다. 실제 가격은 운영에서 모르므로 추정가로 나눈다.
    val_estimate = np.exp(val_log) * validation.area_value.to_numpy(dtype=float)
    finite = np.isfinite(val_estimate)
    price_edges = [float(np.quantile(val_estimate[finite], q)) for q in (.2, .4, .6, .8)] if finite.sum() >= 50 else []
    def price_bin(value: float) -> int:
        return sum(value > edge for edge in price_edges) + 1
    price_bands, price_confidence = {}, {}
    if price_edges:
        bins = np.array([price_bin(v) if np.isfinite(v) else 0 for v in val_estimate])
        for level in levels:
            for b in range(1, 6):
                cell = (validation.level == level).to_numpy() & (bins == b)
                r = target[cell] - val_log[cell]
                if len(r) >= 30:
                    price_bands[f"{level}|{b}"] = (float(np.quantile(r, alpha)), float(np.quantile(r, 1 - alpha)))
                    price_confidence[f"{level}|{b}"] = round(float(np.mean(np.abs(np.exp(r) - 1) <= .10)), 3)
    produced = ~validation.level.isin(segment.withheld_levels).to_numpy()
    validation_mape = round(float(np.mean(np.abs(np.exp(target[produced] - val_pred[produced]) - 1))), 4)
    # 최종 평가: 학습+검증으로 다시 학습한 모델과 검증에서 정한 가중치·분위수를 그대로 쓴다.
    test_pred = to_log(test, model.predict(test)) if len(test) else np.array([])
    edges = [float(np.quantile(test.price, q)) for q in (.2, .4, .6, .8)] if len(test) else []
    groups, rows_out, withheld = defaultdict(list), [], Counter()
    for i, rec in test.iterrows():
        if rec.level in segment.withheld_levels:
            withheld[rec.level] += 1
            continue
        w, comp = weights[rec.level], rec.comp_estimate
        log_estimate = w * comp + (1 - w) * test_pred[i] if (w and not math.isnan(comp)) else test_pred[i]
        estimate = math.exp(log_estimate) * rec.area_value
        error = estimate / rec.price - 1
        band_no = sum(rec.price > edge for edge in edges) + 1
        for key in ("all", rec.level, f"region:{rec.lawd}", f"price_q{band_no}"):
            groups[key].append(error)
        cell = f"{rec.level}|{price_bin(estimate)}" if price_edges else None
        variants = {"level": (bands.get(rec.level), confidence.get(rec.level)),
                    "price": (price_bands.get(cell, bands.get(rec.level)), price_confidence.get(cell, confidence.get(rec.level)))}
        inside = {key: None if band is None else bool(math.exp(log_estimate + band[0]) * rec.area_value <= rec.price
                                                      <= math.exp(log_estimate + band[1]) * rec.area_value)
                  for key, (band, _) in variants.items()}
        band, stated = variants[config.band_by]
        low = math.exp(log_estimate + band[0]) * rec.area_value if band else None
        high = math.exp(log_estimate + band[1]) * rec.area_value if band else None
        rows_out.append({"id": int(rec.id), "ym": rec.get("ym"), "level": rec.level, "lawd": rec.lawd, "actual": int(rec.price),
                         "estimate": round(estimate), "low": None if low is None else round(low), "high": None if high is None else round(high),
                         "inside": inside[config.band_by], "inside_level": inside["level"], "inside_price": inside["price"],
                         "confidence": stated, "confidence_level": variants["level"][1], "confidence_price": variants["price"][1],
                         "error": error, "basis": rec.basis})
    coverage = {lv: round(mean(r["inside"] for r in rows_out if r["level"] == lv and r["inside"] is not None), 3)
                if any(r["level"] == lv and r["inside"] is not None for r in rows_out) else None for lv in levels}
    calibration = {lv: {"stated": confidence.get(lv), "observed_hit10": round(mean(abs(r["error"]) <= .10 for r in rows_out if r["level"] == lv), 3)
                        if any(r["level"] == lv for r in rows_out) else None} for lv in levels}
    rng = random.Random(config.seed)
    draws = sorted(mean(abs(r["error"]) for r in rng.sample(rows_out, config.blind_size)) for _ in range(config.blind_draws)) \
        if len(rows_out) >= config.blind_size else []
    if not rows_out:
        groups["all"] = []
    result = {"model": spec, "model_name": name, "features": feature_set or "full", "residual": residual, "price_band_edges": edges, "training": model.training,
              "validation_mape": validation_mape, "weights": weights, "interval_log_quantiles": bands, "confidence_by_level": confidence,
              "metrics": {key: _metrics(values) for key, values in sorted(groups.items())},
              "produced_rate": round(len(rows_out) / max(len(test), 1), 4), "withheld": dict(withheld),
              "interval_coverage": coverage, "calibration": calibration,
              "blind_simulation": {"draws": len(draws), "size": config.blind_size,
                                   "mape_median": round(median(draws), 4) if draws else None,
                                   "mape_p10": round(draws[int(.1 * (len(draws) - 1))], 4) if draws else None,
                                   "mape_p90": round(draws[int(.9 * (len(draws) - 1))], 4) if draws else None},
              "worst_cases": sorted(rows_out, key=lambda r: -abs(r["error"]))[:15]}
    if config.keep_rows:
        result["rows"] = rows_out
    return result, model, {"weights": weights, "interval_log_quantiles": bands, "confidence_by_level": confidence, "interval": config.interval,
                           "residual": residual, "band_by": config.band_by, "price_band_edges": price_edges,
                           "price_interval_log_quantiles": price_bands, "confidence_by_price": price_confidence}


def _service_rule(test) -> dict | None:
    """현재 서비스 규칙(A1만 산출, 시점 보정 ㎡당 평균 × 면적)의 같은 평가 구간 성적. 산출률을 함께 본다."""
    if "service_rule" not in test:
        return None
    import numpy as np
    produced = test[test.service_rule.notna()]
    edges = [float(np.quantile(test.price, q)) for q in (.2, .4, .6, .8)]
    groups = defaultdict(list)
    for row in produced.itertuples():
        error = row.service_rule / row.price - 1
        for key in ("all", f"region:{row.lawd}", f"price_q{sum(row.price > e for e in edges) + 1}"):
            groups[key].append(error)
    return {"model": "service_rules(A1 only)", "produced_rate": round(len(produced) / max(len(test), 1), 4), **_metrics(groups["all"]),
            "groups": {key: _metrics(values) for key, values in sorted(groups.items()) if key != "all"}}


def evaluate(rows: list[dict], config: SegmentConfig) -> tuple[dict, object, dict]:
    if not config.models:
        raise ValueError("비교할 모델을 하나 이상 지정해주세요")
    segment = SEGMENTS[config.segment]
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
    test = parts["test"]
    by_level = {r["model"]: {lv: r["metrics"].get(lv, {"n": 0}) for lv in segment.levels if lv not in segment.withheld_levels} for r in results}
    report = {"segment": segment.id, "config": asdict(config), "available_models": price_models.available(),
              "samples": {k: len(v) for k, v in parts.items()}, "level_share": {k: dict(Counter(v.level)) for k, v in parts.items()},
              "train_outliers_removed": removed, "champion_by_validation": champion,
              "service_rule": _service_rule(test),
              "comparison": [{"model": r["model"], "validation_mape": r["validation_mape"], "produced_rate": r["produced_rate"],
                              **{k: r["metrics"]["all"][k] for k in ("n", "mape", "median_ape", "hit10")},
                              "interval_coverage": r["interval_coverage"], "blind_mape_median": r["blind_simulation"]["mape_median"]} for r in results],
              "by_level": by_level,
              "results": results,
              "data_sha256": hashlib.sha256(json.dumps([t.id for t in trades]).encode()).hexdigest()}
    model, calibration = fitted[champion]
    return report, model, calibration


def run(args) -> int:
    from dotenv import load_dotenv
    from concierge_workspace import REPO_ROOT
    load_dotenv(REPO_ROOT / ".env", override=False)
    segment = SEGMENTS.get(args.segment)
    if segment is None:
        raise ValueError(f"지원하지 않는 세그먼트: {args.segment} ({', '.join(SEGMENTS)})")
    if args.test_end >= datetime.now(timezone.utc).strftime("%Y%m"):
        raise ValueError("진행 중이거나 미래인 월을 최종 평가에 넣을 수 없습니다")
    final = getattr(args, "final", False)
    if final:
        # 서비스용 학습: validation_start~test_end를 보정 구간으로 쓰고 평가 구간은 두지 않는다.
        if not args.save_model or not (args.train_start < args.validation_start <= args.test_end):
            raise ValueError("--final은 --save-model과 학습 < 보정(validation_start~test_end) 순서가 필요합니다")
    elif not (args.train_start < args.validation_start < args.test_start <= args.test_end):
        raise ValueError("학습 < 검증 < 평가 순서로 월을 지정해주세요")
    if not .5 <= getattr(args, "interval", .80) <= .99:
        raise ValueError("--interval은 0.5~0.99 사이여야 합니다")
    specs = tuple(spec.strip() for spec in args.models.split(",") if spec.strip())
    unknown = [spec for spec in specs if spec.partition("@")[0] not in price_models.available()]
    if unknown:
        raise ValueError(f"등록되지 않은 모델: {unknown} (사용 가능: {price_models.available()})")
    config = SegmentConfig(tuple(args.regions), args.train_start, args.validation_start, "999999" if final else args.test_start, args.test_end,
                           models=specs, iterations=args.iterations, seed=args.seed, segment=args.segment,
                           interval=getattr(args, "interval", .80), band_by=getattr(args, "band_by", "level"))
    # 비교사례는 학습 시작 이전 거래도 근거로 써야 하므로 세그먼트의 근거 기간만큼 앞부터 읽는다.
    start_month = int(args.train_start[:4]) * 12 + int(args.train_start[4:]) - 1 - segment.history_months
    rows = load_rows(config.regions, f"{start_month // 12:04d}{start_month % 12 + 1:02d}", args.test_end, segment.endpoint)
    if final:
        if len(specs) != 1:
            raise ValueError("--final은 평가로 고른 모델 하나만 지정해주세요")
        model, meta = train_final(rows, config, specs[0])
        # A1(공개 기준 충족)의 혼합 적용은 두 기간 평가에서 기존 규칙보다 일관되게 나을 때만 명시적으로 켠다.
        price_models.save(model, Path(args.save_model), meta | {"deployment": "service", "regions": list(config.regions),
                                                                "a1_hybrid_approved": bool(getattr(args, "approve_a1_hybrid", False)),
                                                                "evaluation_report": getattr(args, "evaluation_report", None)})
        print(json.dumps({"saved_model": args.save_model, "model": specs[0], "trained_through": meta["trained_through"],
                          "validation_mape": meta["validation_mape"], "calibration": meta["calibration"]}, ensure_ascii=False, indent=1))
        return 0
    report, model, calibration = evaluate(rows, config)
    directory = Path(args.output) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-avm-segment-{args.segment}")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if args.save_model:
        price_models.save(model, Path(args.save_model), {"segment": segment.id, "calibration": calibration, "split": asdict(config),
                                                        "data_sha256": report["data_sha256"], "deployment": "evaluation_only"})
    print(json.dumps({"champion_by_validation": report["champion_by_validation"], "service_rule": report["service_rule"],
                      "comparison": report["comparison"], "by_level": report["by_level"], "level_share": report["level_share"],
                      "report": str(directory / "result.json"), "saved_model": args.save_model or None, "deployment": "evaluation_only"},
                     ensure_ascii=False, indent=1))
    return 0
