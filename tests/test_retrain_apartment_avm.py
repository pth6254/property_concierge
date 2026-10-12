"""아파트 혼합 AVM 매달 재학습: 최신이면 건너뛰기, 사전 기준 판정에 따른 교체·유지, 이력 보관, 운영의 새 모델 반영."""
import json
from datetime import date

import pandas as pd

from backend.tools import retrain_apartment_avm as retrain
from backend.valuation import apartment_avm
from backend.valuation import models as price_models
from backend.valuation.segments import apartment as apt


def _verdict(estimate_pass=True, a1=True):
    check = {"value": .82, "pass": estimate_pass}
    level = {"coverage": {"A2": check, "A3": check}, "price_band_coverage": {"min": .8, "pass": True},
             "calibration": {"A2": {"stated": .8, "observed_hit10": .8, "pass": True}}}
    return {"a1_hybrid": {"checks": {"a1_bias": {"bias": 0, "pass": a1}}, "approve": a1},
            "model_estimate": {"level": level, "price": level}, "a3": {"hit10": .45, "keep": True}}


def _fake_evaluate(verdict):
    def evaluate(rows, segment, months, train_start, models, base, progress=print):
        evaluate.called = {"months": months, "train_start": train_start}
        return {"models": {"catboost": {"verdict": verdict}}, "monthly": [], "rows": {}}
    return evaluate


def _fake_train(rows, config, spec):
    features = price_models.FeatureSpec(apt.CATEGORICAL, apt.BASE_NUMERIC + apt.COMP_NUMERIC)
    frame = pd.DataFrame([{name: 1.0 for name in features.numeric} | {"lawd": "11650", "dong": "반포동", "complex": f"단지{i % 3}",
                                                                       "area": 60 + i, "target": 17.5 + i * .001} for i in range(60)])
    model = price_models.create("ridge", features).fit(frame, frame)
    _fake_train.config = config
    return model, {"segment": "R-APT", "calibration": {"weights": {"A1": .25}, "interval": .85, "interval_log_quantiles": {"A1": [-.1, .1]},
                   "confidence_by_level": {"A1": .9}}, "feature_origin_month": 2023 * 12 + 9, "history_months": 12,
                   "trained_through": "2026-10-31", "withheld_levels": ["A4"]}


def _run(live, verdict, today=date(2026, 11, 20), **kwargs):
    return retrain.run(live, ("11650",), today, evaluate=_fake_evaluate(verdict), train=_fake_train,
                       load=lambda *args: [], earliest="202310", **kwargs)


def test_month_plan_matches_the_rolling_evaluation_setup():
    assert retrain.last_complete_month(date(2026, 10, 12)) == "202609"
    assert retrain.plan_months("202310", "202609") == {"train_start": "202410", "test_from": "202510", "test_to": "202609",
                                                       "final_validation_start": "202608"}
    # 자료가 쌓이면 학습 창은 최근 24개월로 미끄러진다.
    assert retrain.plan_months("202310", "202709")["train_start"] == "202510"


def test_deploys_when_criteria_pass_and_keeps_previous_in_history(tmp_path):
    live = tmp_path / "r-apt"
    first = _run(live, _verdict())
    assert first["status"] == "deployed" and first["previous"] is None
    manifest = json.loads((live / "model.json").read_text(encoding="utf-8"))
    assert manifest["deployment"] == "service" and manifest["a1_hybrid_approved"] is True
    assert _fake_train.config.validation_start == "202609" and _fake_train.config.band_by == "level"
    second = _run(live, _verdict(a1=False), force=True)
    assert second["status"] == "deployed" and (tmp_path / "history").exists()
    assert json.loads((live / "model.json").read_text(encoding="utf-8"))["a1_hybrid_approved"] is False
    assert len(list((tmp_path / "reports").glob("*.json"))) == 2


def test_skips_when_model_is_current_and_keeps_model_when_criteria_fail(tmp_path):
    live = tmp_path / "r-apt"
    _run(live, _verdict())
    before = (live / "model.json").read_text(encoding="utf-8")
    assert _run(live, _verdict(), today=date(2026, 11, 25))["status"] == "up_to_date"
    kept = _run(live, _verdict(estimate_pass=False), today=date(2026, 12, 5))
    assert kept["status"] == "kept" and "기존 모델 유지" in kept["decision"]["reason"]
    assert (live / "model.json").read_text(encoding="utf-8") == before


def test_runtime_prefers_live_model_and_reloads_after_swap(tmp_path, monkeypatch):
    live = tmp_path / "r-apt"
    monkeypatch.setenv("AVM_APARTMENT_LIVE_DIR", str(live))
    monkeypatch.setenv("AVM_APARTMENT_MODEL_DIR", str(tmp_path / "bundled-missing"))
    apartment_avm._loaded.cache_clear()
    assert apartment_avm.model_dir() == tmp_path / "bundled-missing"  # 라이브 모델이 없으면 이미지 모델 경로
    _run(live, _verdict())
    assert apartment_avm.model_dir() == live
    assert apartment_avm.load_model()[1]["a1_hybrid_approved"] is True
    _run(live, _verdict(a1=False), force=True)
    assert apartment_avm.load_model()[1]["a1_hybrid_approved"] is False  # 재시작 없이 교체본을 읽는다
    apartment_avm._loaded.cache_clear()


def test_first_start_uses_bundled_model_month_before_retraining(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    _run(bundled, _verdict())  # 이미지에 들어 있는 모델(2026-10까지 학습)
    monkeypatch.setenv("AVM_APARTMENT_MODEL_DIR", str(bundled))
    result = _run(tmp_path / "live", _verdict(), today=date(2026, 11, 20))
    assert result["status"] == "up_to_date" and not (tmp_path / "live").exists()
