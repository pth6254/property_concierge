"""기존 단지 기준정보의 지번 누락을 공식 거래 원문으로 보완하고 주소를 재대조한다."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from sqlalchemy import func, select
from db.base import session_scope
from db.models import ComplexCatalog, LegalRegion, Transaction
from services.complex_address_service import enrich_complex_addresses, is_complete_address


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lawd-code")
    args = parser.parse_args()
    grouped = defaultdict(list)
    with session_scope() as session:
        query = select(ComplexCatalog)
        if args.lawd_code:
            query = query.where(ComplexCatalog.lawd_code == args.lawd_code)
        for row in session.scalars(query):
            month = session.scalar(select(func.max(Transaction.deal_ym)).where(
                Transaction.endpoint == "RTMSDataSvcAptTrade", Transaction.lawd_cd == row.lawd_code,
                Transaction.dong == row.dong, Transaction.apt_name == row.name))
            grouped[row.lawd_code].append({"complex_name": row.name, "dong": row.dong, "last_deal_ym": month or ""})
        regions = {row.lawd_code: row.full_name for row in session.scalars(
            select(LegalRegion).where(LegalRegion.level == "sigungu", LegalRegion.is_active.is_(True)))}
    resolved = []
    for lawd, items in grouped.items():
        region = regions.get(lawd)
        if not region:
            raise RuntimeError(f"{lawd} 시군구 기준정보가 필요합니다")
        enrich_complex_addresses(items, region, lawd)
        resolved.extend(items)
        print(json.dumps({"lawd_code": lawd, "checked": len(items),
                          "complete": sum(is_complete_address(item) for item in items)}, ensure_ascii=False), flush=True)
    report = {"checked": len(resolved), "complete": sum(is_complete_address(item) for item in resolved),
              "pending": [{"name": item["complex_name"], "dong": item["dong"], "status": item["address_status"]}
                          for item in resolved if not is_complete_address(item)]}
    output = ROOT / "evaluation-results" / "complex-address-backfill.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
