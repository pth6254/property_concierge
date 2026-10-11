"""ML 없는 비교사례 기준선: 비교사례 추정값(comp_estimate)을 그대로 쓰고, 없으면 같은 동 블록 → 시군구 지수 → 학습 중앙값 순으로 대체한다.

새 모델이 "비교사례만 쓰는 것보다 나은가"를 같은 파이프라인에서 확인하기 위한 기준선이다.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.valuation.models import PriceModel, register

FALLBACK = ("comp_estimate", "block_median", "index_level")


@register("comparables")
class ComparablesPriceModel(PriceModel):
    version = "1"

    def __init__(self, features, **params):
        super().__init__(features, **params)
        self.median: float | None = None

    def fit(self, train, validation):
        import numpy as np
        self.median = float(np.median(train[self.features.target].to_numpy()))
        self.training = {"fallback_order": list(FALLBACK), "train_median": self.median, "train_rows": int(len(train))}
        return self

    def predict(self, frame):
        import numpy as np
        out = np.full(len(frame), self.median, dtype=float)
        filled = np.zeros(len(frame), dtype=bool)
        for name in FALLBACK:
            if name not in frame:
                continue
            values = frame[name].astype(float).to_numpy()
            use = ~filled & np.isfinite(values)
            out[use], filled = values[use], filled | use
        return out

    predict_probe = predict

    def save_artifact(self, directory: Path) -> list[str]:
        (directory / "comparables.json").write_text(json.dumps({"median": self.median}), encoding="utf-8")
        return ["comparables.json"]

    def load_artifact(self, directory: Path) -> None:
        self.median = json.loads((directory / "comparables.json").read_text(encoding="utf-8"))["median"]
