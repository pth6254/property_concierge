"""격리된 브라우저 검증 DB에 지역 계층과 선택적인 가상 거래를 넣는다."""
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
        from backend.transaction_store import put_month
        now = datetime.now()
        month = now.year * 12 + now.month - 1
        for offset in range(12):
            year, index = divmod(month - offset, 12)
            ym = f"{year:04d}{index+1:02d}"
            # 해당 테스트 구간만 교체한다. 위 DB 이름 검사를 통과하지 않으면 여기에 도달할 수 없다.
            rows = [{"apt_name":"품질검증용가상단지", "dong":"역삼동", "bjdong_code":"1168010100",
                "price":price,"area_sqm":area,"per_sqm":round(price/area),"year_built":built,
                "deal_year":str(year),"deal_month":str(index+1),"deal_day":"1","floor":"10","is_cancelled":False}
                for price,area,built in [(60000,84,"2018"),(61000,84,"2018"),(62000,84,"2018"),
                    (90000,130,"2018"),(50000,84,"미상")]]
            put_month("RTMSDataSvcAptTrade","주거용","11680",ym,rows)


if __name__ == "__main__":
    main()
