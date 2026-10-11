"""numpy 릿지 회귀 기준선. 외부 ML 라이브러리 없이 동작해 다른 모델의 비교 기준과 교체 구조 점검에 쓴다.

범주형은 학습 자료에 나온 값만 원-핫(그 외는 0), 숫자형은 학습 자료 중앙값으로 결측을 채우고 표준화하며 결측 표시 열을 더한다.
규제 강도는 검증 구간 MAE로 고른다.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.valuation.models import PriceModel, register


@register("ridge")
class RidgePriceModel(PriceModel):
    version = "1"
    DEFAULTS = {"alphas": [0.1, 1.0, 10.0, 100.0]}

    def __init__(self, features, **params):
        super().__init__(features, **(self.DEFAULTS | params))
        self.state: dict | None = None

    def _prepare(self, frame):
        import numpy as np
        columns = []
        for name in self.features.categorical:
            values = frame[name].astype(str).to_numpy()
            columns += [(values == level).astype(float) for level in self.state["levels"][name]]
        for name in self.features.numeric:
            raw = frame[name].astype(float).to_numpy()
            missing = np.isnan(raw)
            filled = np.where(missing, self.state["fill"][name], raw)
            columns.append((filled - self.state["mean"][name]) / self.state["scale"][name])
            columns.append(missing.astype(float))
        return np.column_stack([np.ones(len(frame))] + columns)

    def _solve(self, x, y, alpha):
        import numpy as np
        penalty = alpha * np.eye(x.shape[1]); penalty[0, 0] = 0  # 절편은 규제하지 않는다
        return np.linalg.solve(x.T @ x + penalty, x.T @ y)

    def _learn_state(self, frame):
        import numpy as np
        state = {"levels": {}, "fill": {}, "mean": {}, "scale": {}}
        for name in self.features.categorical:
            counts = frame[name].astype(str).value_counts()
            state["levels"][name] = [level for level, count in counts.items() if count >= 5]
        for name in self.features.numeric:
            raw = frame[name].astype(float).to_numpy()
            fill = float(np.nanmedian(raw)) if np.isfinite(raw).any() else 0.0
            filled = np.where(np.isnan(raw), fill, raw)
            state["fill"][name], state["mean"][name] = fill, float(filled.mean())
            state["scale"][name] = float(filled.std()) or 1.0
        return state

    def fit(self, train, validation):
        import numpy as np
        import pandas as pd
        target = self.features.target
        self.state = self._learn_state(train)
        x, xv = self._prepare(train), self._prepare(validation)
        scores = {alpha: float(np.mean(np.abs(xv @ self._solve(x, train[target].to_numpy(), alpha) - validation[target].to_numpy())))
                  for alpha in self.params["alphas"]}
        alpha = min(scores, key=scores.get)
        self.probe_state = (self.state, self._solve(x, train[target].to_numpy(), alpha))
        # 선택한 규제 강도로 학습+검증 전체를 다시 학습한다.
        full = pd.concat([train, validation]).reset_index(drop=True)
        self.state = self._learn_state(full)
        self.state["coef"] = self._solve(self._prepare(full), full[target].to_numpy(), alpha).tolist()
        self.training = {"alpha": alpha, "validation_mae": scores, "train_rows": int(len(train)), "validation_rows": int(len(validation))}
        return self

    def predict(self, frame):
        import numpy as np
        return self._prepare(frame) @ np.asarray(self.state["coef"])

    def predict_probe(self, frame):
        import numpy as np
        state, coef = self.probe_state
        saved, self.state = self.state, state
        try:
            return self._prepare(frame) @ np.asarray(coef)
        finally:
            self.state = saved

    def save_artifact(self, directory: Path) -> list[str]:
        (directory / "ridge.json").write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        return ["ridge.json"]

    def load_artifact(self, directory: Path) -> None:
        self.state = json.loads((directory / "ridge.json").read_text(encoding="utf-8"))
