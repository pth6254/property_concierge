"""격리된 브라우저 검증 DB에 지역 계층과 선택적인 가상 거래를 넣는다."""

from pathlib import Path as _WorkspacePath
import sys as _workspace_sys
_workspace_sys.path.insert(0, str(_WorkspacePath(__file__).resolve().parents[1] / "services/intelligence"))
from concierge_workspace import ensure_import_paths as _ensure_import_paths
_ensure_import_paths()

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.base import session_scope
from db.models import LegalRegion


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transactions", action="store_true")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL", "")
    if (os.getenv("BROWSER_TEST_DB") != "1" or os.getenv("APP_ENV") != "development"
            or not database_url or make_url(database_url).database != "real_estate_test"):
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
    if args.transactions:
        from sqlalchemy.dialects.postgresql import insert
        from db.models import ComplexCatalog
        # 주소 정책을 끄지 않고 양쪽 주소가 확인된 가상 기준정보를 함께 준비한다.
        address = {"road_address": "서울특별시 강남구 검증로 123", "jibun_address": "서울특별시 강남구 역삼동 123",
            "address_status": "matched", "address_source": "browser_fixture", "address_version": 4,
            "address_checked_at": datetime.now().isoformat(), "official_jibuns": ["123"]}
        with session_scope() as session:
            values = dict(lawd_code="11680", dong="역삼동", canonical_name="품질검증용가상단지", name="품질검증용가상단지",
                region="서울특별시 강남구", aliases=["품질검증용가상단지"], address=address, status="matched", checked_at=time.time())
            session.execute(insert(ComplexCatalog).values(**values).on_conflict_do_update(
                index_elements=["lawd_code", "dong", "canonical_name"], set_={"address": address, "status": "matched", "checked_at": time.time()}))
        from backend.transaction_store import put_month
        now = datetime.now()
        month = now.year * 12 + now.month - 1
        for offset in range(12):
            year, index = divmod(month - offset, 12)
            ym = f"{year:04d}{index+1:02d}"
            # 해당 테스트 구간만 교체한다. 위 DB 이름 검사를 통과하지 않으면 여기에 도달할 수 없다.
            rows = [{"apt_name":"품질검증용가상단지", "dong":"역삼동", "bjdong_code":"1168010100",
                "price":price,"area_sqm":area,"per_sqm":round(price/area),"year_built":built,"jibun":"123",
                "deal_year":str(year),"deal_month":str(index+1),"deal_day":"1","floor":"10","is_cancelled":False}
                for price,area,built in [(60000,84,"2018"),(61000,84,"2018"),(62000,84,"2018"),
                    (90000,130,"2018"),(50000,84,"미상")]]
            put_month("RTMSDataSvcAptTrade","주거용","11680",ym,rows)


if __name__ == "__main__":
    main()
