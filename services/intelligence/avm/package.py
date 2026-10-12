"""제출용 단독 실행 묶음을 만든다.

python package.py                      # dist/avm/ 폴더와 dist/avm.zip 생성
python package.py --output 다른/경로

저장소에서는 가격 모델 등록표를 서비스 원본(services/intelligence/backend/valuation/models)에서 가져온다.
제출물은 서비스 DB·패키지 없이 `pip install -r requirements.txt` 후 바로 실행돼야 하므로, 묶을 때만
등록표를 rh_avm/models로 복사하고 import 경로를 묶음 안으로 바꾼다. 저장소에 복사본을 두지 않기 위함이다.
NOTES.md는 발표 자료 작성용 작업 기록이라 제출 묶음에서 뺀다. .env 등 키가 든 파일은 애초에 대상이 아니다.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT.parent / "backend" / "valuation" / "models"
FILES = ("README.md", "requirements.txt", "collect.py", "train.py", "validate.py", "predict.py",
         "input_sample.csv", "output_sample.csv")
FOLDERS = ("data", "model", "validation")
PACKAGE = ("__init__.py", "core.py", "model.py", "register.py", "price_models.py")


def build(output: Path) -> Path:
    target = output / "avm"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in FILES:
        shutil.copy2(ROOT / name, target / name)
    for name in FOLDERS:
        shutil.copytree(ROOT / name, target / name)
    (target / "rh_avm" / "models").mkdir(parents=True)
    for name in PACKAGE:
        shutil.copy2(ROOT / "rh_avm" / name, target / "rh_avm" / name)
    for source in sorted(REGISTRY.glob("*.py")):
        text = source.read_text(encoding="utf-8").replace("backend.valuation.models", "rh_avm.models")
        (target / "rh_avm" / "models" / source.name).write_text(text, encoding="utf-8")
    archive = shutil.make_archive(str(output / "avm"), "zip", root_dir=output, base_dir="avm")
    return Path(archive)


def main() -> None:
    parser = argparse.ArgumentParser(description="R-RH 과제 제출 묶음 생성")
    parser.add_argument("--output", default=str(ROOT / "dist"))
    args = parser.parse_args()
    archive = build(Path(args.output))
    print(f"묶음 {archive.with_suffix('')} · 압축 {archive}")


if __name__ == "__main__":
    main()
