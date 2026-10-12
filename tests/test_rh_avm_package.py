"""연립·다세대 과제 패키지(services/intelligence/avm): 저장소에서는 서비스 등록표를 쓰고, 제출 묶음은 단독으로 실행되는지."""
import importlib.util
import sys
from pathlib import Path

AVM = Path(__file__).resolve().parents[1] / "services" / "intelligence" / "avm"
REGISTRY = AVM.parent / "backend" / "valuation" / "models"


def _load_package():
    spec = importlib.util.spec_from_file_location("rh_avm_package", AVM / "package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_keeps_no_copy_of_the_price_model_registry():
    # 복사본이 생기면 서비스 평가와 과제 산출의 모델 구현이 따로 고쳐진다.
    assert not (AVM / "rh_avm" / "models").exists()
    sys.path.insert(0, str(AVM))
    try:
        from rh_avm.price_models import registry
        from backend.valuation import models
        assert registry is models
    finally:
        sys.path.remove(str(AVM))


def test_bundle_copies_the_registry_and_drops_repository_imports(tmp_path):
    archive = _load_package().build(tmp_path)
    bundle = tmp_path / "avm"
    assert archive.exists() and (bundle / "predict.py").exists() and (bundle / "model" / "model.json").exists()
    assert not (bundle / "NOTES.md").exists() and not list(bundle.rglob(".env*"))
    copied = bundle / "rh_avm" / "models"
    assert sorted(p.name for p in copied.glob("*.py")) == sorted(p.name for p in REGISTRY.glob("*.py"))
    for source in REGISTRY.glob("*.py"):
        text = (copied / source.name).read_text(encoding="utf-8")
        assert "backend" not in text
        assert text == source.read_text(encoding="utf-8").replace("backend.valuation.models", "rh_avm.models")
