"""교체 가능한 AVM 가격 모델: 등록표·저장/읽기·변조 거부, 그리고 새 모델이 평가 파이프라인을 그대로 통과하는지."""
import math
import random

import numpy as np
import pandas as pd
import pytest

from backend.valuation import models as price_models
from backend.valuation.models import FeatureSpec, PriceModel, register

SPEC = FeatureSpec(("lawd", "dong", "house_type"), ("area", "floor", "comp_estimate", "block_median", "index_level"))


def _frame(n, seed, level_cycle=("L1", "L2", "L3")):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        lawd = rng.choice(["11500", "11620", "11680"])
        area, floor = rng.uniform(20, 60), rng.randint(1, 5)
        base = {"11500": 15.8, "11620": 15.9, "11680": 16.6}[lawd] + .01 * floor - .002 * area
        level = level_cycle[i % len(level_cycle)]
        target = base + rng.gauss(0, .05)
        rows.append({"lawd": lawd, "dong": f"동{rng.randint(1, 3)}", "house_type": "다세대", "area": area, "floor": float(floor),
                     "comp_estimate": base + rng.gauss(0, .08) if level != "L3" else float("nan"), "block_median": base,
                     "index_level": 15.9, "target": target, "level": level, "area_value": area,
                     "price": math.exp(target) * area, "id": i, "basis": "합성", "lawd_code": lawd})
    frame = pd.DataFrame(rows)
    frame["lawd"] = frame["lawd"].astype(str)
    return frame


def test_registry_lists_builtins_and_rejects_unknown_names():
    assert {"catboost", "ridge", "comparables"} <= set(price_models.available())
    with pytest.raises(ValueError, match="등록되지 않은"):
        price_models.create("no-such-model", SPEC)


@pytest.mark.parametrize("name", ["ridge", "comparables"])
def test_save_and_load_through_manifest_give_identical_predictions(name, tmp_path):
    train, validation, test = _frame(300, 1), _frame(80, 2), _frame(50, 3)
    model = price_models.create(name, SPEC).fit(train, validation)
    price_models.save(model, tmp_path, {"segment": "R-RH"})
    loaded, manifest = price_models.load(tmp_path)
    assert manifest["model"] == name and manifest["segment"] == "R-RH"
    assert type(loaded) is type(model)
    np.testing.assert_allclose(loaded.predict(test), model.predict(test))


def test_catboost_round_trip(tmp_path):
    pytest.importorskip("catboost")
    train, validation, test = _frame(300, 1), _frame(80, 2), _frame(50, 3)
    model = price_models.create("catboost", SPEC, iterations=60).fit(train, validation)
    price_models.save(model, tmp_path)
    loaded, manifest = price_models.load(tmp_path)
    assert manifest["training"]["iterations"] >= 50
    np.testing.assert_allclose(loaded.predict(test), model.predict(test))


def test_load_refuses_artifacts_that_do_not_match_the_manifest(tmp_path):
    model = price_models.create("comparables", SPEC).fit(_frame(100, 1), _frame(30, 2))
    price_models.save(model, tmp_path)
    (tmp_path / "comparables.json").write_text('{"median": 1.0}', encoding="utf-8")
    with pytest.raises(ValueError, match="manifest와 다릅니다"):
        price_models.load(tmp_path)


def test_ridge_learns_signal_better_than_a_constant():
    train, validation, test = _frame(400, 1), _frame(100, 2), _frame(200, 3)
    ridge = price_models.create("ridge", SPEC).fit(train, validation)
    error = np.mean(np.abs(ridge.predict(test) - test.target))
    constant = np.mean(np.abs(train.target.median() - test.target))
    assert error < constant * .7


def test_comparables_falls_back_when_no_comparable_exists():
    frame = _frame(30, 4)
    model = price_models.create("comparables", SPEC).fit(frame, frame)
    predicted = model.predict(frame)
    l3 = frame.level == "L3"
    np.testing.assert_allclose(predicted[l3.to_numpy()], frame.loc[l3, "block_median"])
    np.testing.assert_allclose(predicted[(~l3).to_numpy()], frame.loc[~l3, "comp_estimate"])


def test_a_newly_registered_model_runs_through_the_same_evaluation_pipeline():
    """모델 교체 구조의 핵심: 평가 코드 수정 없이 새 구현을 등록만 해서 비교할 수 있어야 한다."""
    from evaluation.segment_avm import SegmentConfig, assess

    @register("test-district-median")
    class DistrictMedian(PriceModel):
        def fit(self, train, validation):
            self.table = train.groupby("lawd").target.median().to_dict()
            self.default = float(train.target.median())
            self.training = {"rows": len(train)}
            return self

        def predict(self, frame):
            return np.array([self.table.get(v, self.default) for v in frame["lawd"]])

        predict_probe = predict

        def save_artifact(self, directory):
            return []

        def load_artifact(self, directory):
            pass

    config = SegmentConfig(("11500",), "202401", "202402", "202403", "202403", models=("test-district-median",), blind_draws=10)
    result, model, calibration = assess("test-district-median", _frame(300, 1), _frame(120, 2), _frame(120, 3), config)
    assert result["model_name"] == "test-district-median"
    assert result["metrics"]["all"]["n"] == 120
    assert set(calibration["confidence_by_level"]) == {"L1", "L2", "L3"}
    assert "test-district-median" in price_models.available()
