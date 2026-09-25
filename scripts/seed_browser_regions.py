"""격리된 브라우저 검증 DB에 서울·강남구·역삼동 법정동 계층을 넣는다."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.base import session_scope
from db.models import LegalRegion


def main():
    if os.getenv("BROWSER_TEST_DB") != "1" or os.getenv("APP_ENV") != "development":
        raise RuntimeError("격리 개발 DB에서만 브라우저용 지역을 준비할 수 있습니다")
    nodes = [
        ("1100000000", None, "11", "000", "000", "서울특별시", "서울특별시", "sido", 1),
        ("1168000000", "1100000000", "11", "680", "000", "강남구", "서울특별시 강남구", "sigungu", 2),
        ("1168010100", "1168000000", "11", "680", "101", "역삼동", "서울특별시 강남구 역삼동", "eup_myeon_dong", 3),
    ]
    with session_scope() as session:
        for code, parent, sido, gu, dong, name, full, level, depth in nodes:
            session.merge(LegalRegion(code=code, parent_code=parent, sido_code=sido, sigungu_code=gu,
                eup_myeon_dong_code=dong, ri_code="00", name=name, full_name=full, level=level,
                depth=depth, lawd_code=code[:5] if depth > 1 else None, resident_code="",
                cadastral_code="", sort_order=1, remarks="", is_active=True, synced_at=time.time()))


if __name__ == "__main__":
    main()
