"""서비스 코드와 저장소의 데이터·운영 도구 경로를 구분한다."""
from pathlib import Path
import sys

INTELLIGENCE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = INTELLIGENCE_ROOT.parents[1]

def ensure_import_paths() -> None:
    # 기존 분석 모듈의 직접 import를 유지하되 서비스 밖에 복제 모듈을 두지 않는다.
    for path in (REPO_ROOT, INTELLIGENCE_ROOT / 'backend', INTELLIGENCE_ROOT):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
