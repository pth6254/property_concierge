"""가격·단가를 입력에 넣지 않는 아파트 CatBoost 실험 모델."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

FEATURE_VERSION = "apartment-catboost-v1"
FEATURES = ("area_sqm", "floor", "building_age", "month_index", "lawd_cd", "dong", "complex_key")
CATEGORICAL = ("lawd_cd", "dong", "complex_key")


def month_index(value: str) -> int:
    if len(value) != 6 or not value.isdigit() or not 1 <= int(value[4:]) <= 12:
        raise ValueError("거래월은 YYYYMM 형식이어야 합니다")
    return int(value[:4]) * 12 + int(value[4:]) - 1


def month_shift(value: str, amount: int) -> str:
    index = month_index(value) + amount
    return f"{index // 12:04d}{index % 12 + 1:02d}"


def numeric(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else math.nan
    except (ValueError, TypeError):
        return math.nan


def complex_key(row: dict) -> str:
    # 확인된 개별 물건 ID가 아니라 광고/거래 자료의 범주 특성이다. DB 객체를 병합하지 않는다.
    return json.dumps([str(row.get(key) or "").strip() for key in ("lawd_cd", "dong", "jibun", "apt_name")], ensure_ascii=False)


def feature_values(row: dict) -> list:
    area = numeric(row.get("area_sqm"))
    if not math.isfinite(area) or area <= 0:
        raise ValueError("전용면적은 양수여야 합니다")
    month = str(row["deal_ym"])
    index = month_index(month)
    year = numeric(row.get("year_built"))
    age = int(month[:4]) - year if math.isfinite(year) and 1800 <= year <= int(month[:4]) else math.nan
    return [area, numeric(row.get("floor")), age, index,
            str(row.get("lawd_cd") or "unknown"), str(row.get("dong") or "unknown"), complex_key(row)]


def _pool(rows, labels=False):
    try:
        from catboost import Pool
    except ImportError as error:
        raise RuntimeError("requirements-ml.txt의 CatBoost 의존성을 먼저 설치해주세요") from error
    targets = [numeric(row.get("price")) for row in rows] if labels else None
    if targets is not None and any(not math.isfinite(value) or value <= 0 for value in targets):
        raise ValueError("학습 정답은 유한한 양수 가격이어야 합니다")
    return Pool([feature_values(row) for row in rows],
                label=[math.log(value) for value in targets] if targets is not None else None,
                cat_features=list(CATEGORICAL), feature_names=list(FEATURES))


class CatBoostAvm:
    def __init__(self, iterations=500, depth=6, seed=42, threads=4):
        if not 1 <= iterations <= 2000 or not 2 <= depth <= 10 or not 1 <= threads <= 8:
            raise ValueError("학습 반복·깊이·CPU 수의 허용 범위를 확인해주세요")
        self.parameters = dict(iterations=iterations, depth=depth, random_seed=seed, thread_count=threads,
                               loss_function="RMSE", learning_rate=.05, verbose=False, allow_writing_files=False)
        self.model = None
        self.best_iterations = None

    def fit(self, train: list[dict], validation: list[dict]):
        from catboost import CatBoostRegressor
        if not train or not validation or max(r["deal_ym"] for r in train) >= min(r["deal_ym"] for r in validation):
            raise ValueError("학습과 검증은 겹치지 않는 과거/이후 월로 분리해야 합니다")
        # 최종 평가 거래는 early stopping에도 전달하지 않는다.
        selected = CatBoostRegressor(**self.parameters)
        selected.fit(_pool(train, True), eval_set=_pool(validation, True), early_stopping_rounds=40)
        self.best_iterations = selected.tree_count_
        self.model = CatBoostRegressor(**(self.parameters | {"iterations": self.best_iterations}))
        self.model.fit(_pool(train + validation, True))
        return self

    def predict(self, rows: list[dict]) -> list[float]:
        if self.model is None:
            raise ValueError("학습 또는 모델 로드가 필요합니다")
        values = self.model.predict(_pool(rows))
        result = []
        for value in values:
            # 실패한 수치를 정상 가격으로 조용히 자르지 않는다.
            price = math.exp(float(value))
            if not math.isfinite(price) or price <= 0:
                raise ValueError("유효하지 않은 모델 추정 가격입니다")
            result.append(price)
        return result

    def save(self, directory: Path, metadata: dict):
        if self.model is None:
            raise ValueError("학습된 모델이 없습니다")
        model_path = directory / "model.cbm"
        self.model.save_model(str(model_path), format="cbm")
        manifest = metadata | {"feature_version": FEATURE_VERSION, "features": list(FEATURES),
            "categorical_features": list(CATEGORICAL), "target": "log(transaction_price_manwon)",
            "prediction_unit": "manwon", "parameters": self.parameters, "best_iterations": self.best_iterations,
            "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(), "deployment": "evaluation_only"}
        (directory / "model.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path):
        from catboost import CatBoostRegressor
        metadata = json.loads((directory / "model.json").read_text(encoding="utf-8"))
        model_path = directory / "model.cbm"
        if (metadata.get("feature_version") != FEATURE_VERSION or metadata.get("features") != list(FEATURES)
                or metadata.get("categorical_features") != list(CATEGORICAL)
                or metadata.get("prediction_unit") != "manwon"
                or metadata.get("model_sha256") != hashlib.sha256(model_path.read_bytes()).hexdigest()):
            raise ValueError("모델 파일·특성 버전·금액 단위가 일치하지 않습니다")
        instance = cls()
        instance.model = CatBoostRegressor().load_model(str(model_path))
        if instance.model.feature_names_ != list(FEATURES):
            raise ValueError("모델 내부 특성 순서가 다릅니다")
        instance.parameters = metadata["parameters"]
        instance.best_iterations = metadata["best_iterations"]
        return instance
