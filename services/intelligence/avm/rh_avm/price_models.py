"""가격 모델 등록표 연결.

저장소 안에서는 서비스 원본 `backend.valuation.models`를 그대로 쓴다. 등록표를 이 폴더에 복사해 두면
서비스 평가(`evaluation avm-segment`)와 과제 산출의 모델 구현이 따로 고쳐져 결과가 갈라지기 때문이다.
제출용 묶음(`package.py`)은 서비스 저장소 없이 실행돼야 하므로 같은 파일을 `rh_avm/models`로 복사해 넣고,
그때는 묶음 안의 복사본을 먼저 쓴다.
"""
from __future__ import annotations

import sys
from importlib.util import find_spec
from pathlib import Path

# import 실패를 잡아 분기하면 묶음 복사본 안의 진짜 import 오류까지 서비스 원본으로 조용히 넘어가므로, 존재 여부로만 고른다.
if find_spec("rh_avm.models") is not None:
    from rh_avm import models as registry  # 제출 묶음에만 존재
else:
    _intelligence = Path(__file__).resolve().parents[2]
    if not (_intelligence / "backend" / "valuation" / "models").is_dir():
        raise RuntimeError("가격 모델 등록표를 찾지 못했습니다. 저장소 안에서 실행하거나 package.py로 만든 묶음을 사용하세요.")
    if str(_intelligence) not in sys.path:
        sys.path.insert(0, str(_intelligence))
    from backend.valuation import models as registry

__all__ = ["registry"]
