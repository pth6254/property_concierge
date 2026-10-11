"""CatBoost 가격 모델. 범주형 변수를 직접 다루고 결측을 스스로 처리한다."""
from __future__ import annotations

from pathlib import Path

from backend.valuation.models import PriceModel, register


@register("catboost")
class CatBoostPriceModel(PriceModel):
    version = "1"
    DEFAULTS = {"iterations": 1500, "depth": 6, "learning_rate": .05, "loss": "RMSE", "seed": 42, "early_stopping": 60}

    def __init__(self, features, **params):
        super().__init__(features, **(self.DEFAULTS | params))
        self.model = None

    def _regressor(self, iterations: int, early_stop: bool):
        from catboost import CatBoostRegressor
        options = dict(iterations=iterations, depth=self.params["depth"], learning_rate=self.params["learning_rate"],
                       loss_function=self.params["loss"], eval_metric="MAE", random_seed=self.params["seed"],
                       verbose=False, allow_writing_files=False)
        if early_stop:
            options.update(od_type="Iter", od_wait=self.params["early_stopping"])
        return CatBoostRegressor(**options)

    def _pool(self, frame, with_target: bool):
        from catboost import Pool
        return Pool(frame[self.features.columns], frame[self.features.target] if with_target else None,
                    cat_features=list(self.features.categorical))

    def fit(self, train, validation):
        import pandas as pd
        # 반복 수만 검증으로 정하고 학습+검증으로 다시 학습한다.
        probe = self._regressor(self.params["iterations"], True)
        probe.fit(self._pool(train, True), eval_set=self._pool(validation, True), use_best_model=True)
        iterations = max((probe.get_best_iteration() or 0) + 1, 50)
        self.probe = probe
        self.model = self._regressor(iterations, False)
        self.model.fit(self._pool(pd.concat([train, validation]).reset_index(drop=True), True))
        self.training = {"iterations": iterations, "train_rows": int(len(train)), "validation_rows": int(len(validation))}
        return self

    def predict(self, frame):
        return self.model.predict(frame[self.features.columns])

    def predict_probe(self, frame):
        """검증 구간 잔차 보정용: 검증 자료를 보지 않은 모델의 예측."""
        return self.probe.predict(frame[self.features.columns])

    def save_artifact(self, directory: Path) -> list[str]:
        self.model.save_model(str(directory / "catboost.cbm"))
        return ["catboost.cbm"]

    def load_artifact(self, directory: Path) -> None:
        from catboost import CatBoostRegressor
        self.model = CatBoostRegressor()
        self.model.load_model(str(directory / "catboost.cbm"))
