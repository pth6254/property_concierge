"""교체 가능한 AVM 가격 모델.

학습·보정·평가·예측 코드는 `PriceModel` 인터페이스만 알고, 어떤 구현을 쓸지는 이름(설정)과 저장된 manifest가 정한다.
모델을 바꾸는 절차: ① 구현을 `@register("이름")`으로 등록 ② 같은 시간 분할로 기존 모델과 비교 평가
③ 기준을 넘으면 그 모델로 학습한 산출물(manifest 포함)로 교체. 세그먼트 공개 기준(홀드아웃 검증)은 모델이 바뀌어도 다시 통과해야 한다.

계약
- 입력: pandas.DataFrame. `features.categorical`·`features.numeric` 열을 쓰며 숫자 열의 결측(NaN)을 스스로 처리해야 한다.
- 타깃·출력: ㎡당 가격의 자연로그. 가격 환산(× 면적)·구간·신뢰도 보정은 모델 밖 공통 코드가 한다.
- 학습: fit(train, validation)에서 검증 구간은 조기 종료·하이퍼파라미터 선택에만 쓰고, 최종 평가 구간은 절대 받지 않는다.
- 무거운 라이브러리는 구현 안에서만 지연 import 한다(운영 API 이미지에 학습 의존성을 강제하지 않기 위함).
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

MANIFEST = "model.json"
MANIFEST_SCHEMA = "price-model-manifest-1"


@dataclass(frozen=True)
class FeatureSpec:
    categorical: tuple[str, ...]
    numeric: tuple[str, ...]
    target: str = "target"

    @property
    def columns(self) -> list[str]:
        return [*self.categorical, *self.numeric]


class PriceModel(ABC):
    """모든 가격 모델 구현의 공통 인터페이스."""

    name: str = ""
    version: str = "1"

    def __init__(self, features: FeatureSpec, **params):
        self.features = features
        self.params = params
        self.training: dict = {}

    @abstractmethod
    def fit(self, train, validation) -> "PriceModel":
        """train으로 학습하고 validation은 조기 종료·선택에만 쓴다. 학습 정보는 self.training에 남긴다."""

    @abstractmethod
    def predict(self, frame):
        """frame의 각 행에 대해 ㎡당 가격 로그를 numpy 배열로 돌려준다."""

    def predict_probe(self, frame):
        """구간·신뢰도 보정용 예측: 검증 자료로 다시 학습하기 **전** 모델의 예측. 검증 잔차가 낙관적으로 줄지 않게 한다."""
        raise NotImplementedError(f"{self.name} 모델은 보정용 예측(predict_probe)을 구현해야 합니다")

    @abstractmethod
    def save_artifact(self, directory: Path) -> list[str]:
        """구현별 파일을 저장하고 파일 이름 목록을 돌려준다."""

    @abstractmethod
    def load_artifact(self, directory: Path) -> None:
        """save_artifact로 저장한 파일을 읽는다."""


_REGISTRY: dict[str, Callable[..., PriceModel]] = {}


def register(name: str):
    def decorate(cls):
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return decorate


def available() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def create(name: str, features: FeatureSpec, **params) -> PriceModel:
    _load_builtin()
    if name not in _REGISTRY:
        raise ValueError(f"등록되지 않은 가격 모델: {name} (사용 가능: {', '.join(sorted(_REGISTRY))})")
    return _REGISTRY[name](features, **params)


def save(model: PriceModel, directory: Path, extra: dict | None = None) -> Path:
    """구현 파일과 manifest를 저장한다. manifest만 보고 같은 구현·설정으로 다시 읽을 수 있어야 한다."""
    directory.mkdir(parents=True, exist_ok=True)
    files = model.save_artifact(directory)
    manifest = {"schema": MANIFEST_SCHEMA, "model": model.name, "model_version": model.version, "params": model.params,
                "features": asdict(model.features), "training": model.training, "files": files,
                "sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in files}} | (extra or {})
    path = directory / MANIFEST
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def load(directory: Path) -> tuple[PriceModel, dict]:
    """manifest의 모델 이름으로 구현을 찾아 읽는다. 파일이 바뀌었으면(해시 불일치) 거부한다."""
    manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("가격 모델 manifest 형식을 확인해주세요")
    for name, digest in manifest.get("sha256", {}).items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"모델 파일이 manifest와 다릅니다: {name}")
    spec = manifest["features"]
    model = create(manifest["model"], FeatureSpec(tuple(spec["categorical"]), tuple(spec["numeric"]), spec.get("target", "target")),
                   **manifest.get("params", {}))
    model.training = manifest.get("training", {})
    model.load_artifact(directory)
    return model, manifest


def _load_builtin() -> None:
    # 내장 구현은 등록만 하고 라이브러리 import는 각 구현의 fit/load에서 한다.
    from backend.valuation.models import catboost_model, comparables_model, ridge_model  # noqa: F401
