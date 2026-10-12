"""아파트(R-APT) 혼합 AVM 운영 실행.

시간 분할 평가(`evaluation avm-segment --segment apartment`)를 통과한 뒤 `--final`로 학습한 산출물(manifest 포함)만 읽는다.
산출물이 없거나 읽기·해시 검증·DB 조회에 실패하면 None을 돌려주고, 호출측은 기존 비교사례 규칙으로 처리한다.
근거 단계와 변수는 평가와 같은 `segments.apartment` 코드를 쓴다. 평가와 운영의 규칙이 다르면 검증 결과가 운영 품질을 말해주지 않는다.

결과 단계
- A1: 같은 단지 6개월 ±10% 5건 이상 — 비교사례 값과 모델 보정값을 검증에서 정한 가중치로 섞는다(시장가격 참고).
- A2·A3: 공개 기준 미달 — 모델 추정을 근거 단계별로 보정한 구간·신뢰도와 함께 낸다(ML 참고 추정, 시장가격 비교 제외).
- A4: 근거 없음 — 가격을 내지 않는다.
금액은 원, 면적은 ㎡.
"""
from __future__ import annotations

import math
import os
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from backend.valuation.segments import apartment as apt
from backend.valuation.segments.row_house import MarketIndex

ENDPOINT = "RTMSDataSvcAptTrade"


def model_dir() -> Path:
    from concierge_workspace import REPO_ROOT
    return Path(os.getenv("AVM_APARTMENT_MODEL_DIR") or REPO_ROOT / "data" / "models" / "r-apt")


@lru_cache(maxsize=1)
def _loaded(directory: str):
    from backend.valuation import models as price_models
    try:
        model, manifest = price_models.load(Path(directory))
    except Exception as exc:  # 산출물 없음·해시 불일치·라이브러리 없음은 모두 "모델 미사용"이다.
        print(f"[apartment-avm] 모델 미사용: {type(exc).__name__}")
        return None
    if manifest.get("segment") != "R-APT" or manifest.get("deployment") != "service":
        print("[apartment-avm] 모델 미사용: 서비스용 R-APT 산출물이 아님")
        return None
    return model, manifest


def load_model():
    return _loaded(str(model_dir()))


def _ym(day: date) -> str:
    return f"{day.year:04d}{day.month:02d}"


def _rows(lawd: str, start: str, end: str) -> list[dict]:
    from sqlalchemy import select, text
    from db.base import get_engine
    from db.models import Transaction
    columns = [Transaction.id, Transaction.lawd_cd, Transaction.deal_year, Transaction.deal_month, Transaction.deal_day,
               Transaction.price, Transaction.area_sqm, Transaction.floor, Transaction.year_built, Transaction.dong,
               Transaction.apt_name, Transaction.transaction_type, Transaction.is_cancelled]
    with get_engine().connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = connection.execute(select(*columns).where(Transaction.endpoint == ENDPOINT, Transaction.lawd_cd == lawd,
                Transaction.deal_ym >= start, Transaction.deal_ym <= end)).mappings().all()
    return [dict(row) for row in rows]


def _resolve_complex(comps: apt.ComparableIndex, lawd: str, dong: str, names: list[str]) -> str | None:
    """국토부 단지명과 사용자 입력 이름을 같은 법정동 안에서만 맞춘다. 여러 단지가 걸리면 정하지 않는다."""
    for name in names:
        key = apt.complex_key(lawd, dong, name)
        if key in comps.by_complex:
            return key
    prefix = f"{lawd}|{(dong or '').strip()}|"
    keys = [k for k in comps.by_complex if k.startswith(prefix)]
    for name in names:
        clean = apt.complex_key(lawd, dong, name)[len(prefix):]
        if len(clean) < 3:
            continue
        hits = [k for k in keys if clean in k[len(prefix):] or k[len(prefix):] in clean]
        if len(hits) == 1:
            return hits[0]
    return None


def estimate(lawd: str, dong: str, names: list[str], area: float, floor: int | None, as_of: date) -> dict | None:
    """대상 한 건의 근거 단계·추정가·구간·신뢰도. 모델을 쓸 수 없으면 None."""
    loaded = load_model()
    if loaded is None or not lawd or not dong or not area or area <= 0:
        return None
    model, manifest = loaded
    history = int(manifest.get("history_months", 12)) + 4  # 근거 12개월 + 시점 지수 창(3개월) 여유
    start_index = as_of.year * 12 + as_of.month - 1 - history
    try:
        rows = _rows(lawd, f"{start_index // 12:04d}{start_index % 12 + 1:02d}", _ym(as_of))
    except Exception as exc:
        print(f"[apartment-avm] 실거래 조회 실패: {type(exc).__name__}")
        return None
    trades = [t for t in apt.normalize(rows) if t.day <= as_of]
    if not trades:
        return None
    index = MarketIndex(trades)
    comps = apt.ComparableIndex(trades, index)
    key = _resolve_complex(comps, lawd, dong, [n for n in names if n])
    if key is None:
        return {"level": "A4", "basis": "같은 법정동에서 단지를 하나로 확인하지 못했습니다", "model": manifest["model"]}
    subject = apt.Subject(lawd, dong.strip(), key, float(area), floor, None, as_of)
    # 기준일 당일 신고까지 근거로 쓴다. 평가에서는 대상 거래일 이전만 쓰므로 하루 뒤를 기준으로 둔다.
    evidence = comps.evidence(subject, as_of=as_of + timedelta(days=1))
    calibration = manifest.get("calibration") or {}
    context = {"level": evidence.level, "basis": evidence.basis, "complex": key.split("|", 2)[2],
               "counts": {"a1": evidence.a1_count, "a2": evidence.a2_count, "complex_other_area": evidence.cx_count, "dong_similar": evidence.dong_count},
               "model": manifest["model"], "model_version": manifest.get("model_version"), "trained_through": manifest.get("trained_through"),
               "interval": calibration.get("interval"), "hybrid_approved": bool(manifest.get("a1_hybrid_approved"))}
    if evidence.level in set(manifest.get("withheld_levels", ["A4"])):
        return context
    import pandas as pd
    values = apt.features(subject, evidence, index, int(manifest["feature_origin_month"]), direct=False,
                          year_built=comps.complex_year(key))
    predicted = float(model.predict(pd.DataFrame([values]))[0])
    weight = float((calibration.get("weights") or {}).get(evidence.level, 0.0))
    comp = evidence.estimate
    if calibration.get("residual"):
        # 잔차 학습 모델은 비교사례 값 대비 차이를 예측한다. 비교사례가 없으면 가격을 만들지 않는다.
        if comp is None:
            return context | {"level": "A4"}
        predicted += comp
    log_estimate = weight * comp + (1 - weight) * predicted if (weight and comp is not None) else predicted
    band = (calibration.get("interval_log_quantiles") or {}).get(evidence.level)
    confidence = (calibration.get("confidence_by_level") or {}).get(evidence.level)
    if band is None or confidence is None:
        context["basis"] += " · 이 근거 단계의 검증 표본이 부족해 가격을 내지 않습니다"
        context["level"] = "A4"
        return context
    won = lambda log_value: int(round(math.exp(log_value) * area))
    return context | {"estimated_value": won(log_estimate), "value_min": won(log_estimate + band[0]), "value_max": won(log_estimate + band[1]),
                      "confidence": confidence, "comparable_weight": weight, "comparable_per_sqm": None if comp is None else int(round(math.exp(comp)))}
