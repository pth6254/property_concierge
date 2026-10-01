"""실제 추천 API에서 두 주소가 확인된 후보만 반환하는지 검증한다. 매물 호가 검증은 아니다."""
from __future__ import annotations

from pathlib import Path as _WorkspacePath
import sys as _workspace_sys
_workspace_sys.path.insert(0, str(_WorkspacePath(__file__).resolve().parents[1] / "services/intelligence"))
from concierge_workspace import ensure_import_paths as _ensure_import_paths
_ensure_import_paths()


import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import requests

DISTRICTS = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
    "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
    "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8002")
    parser.add_argument("--district", choices=DISTRICTS)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--output", default="evaluation-results/complex-address-api.json")
    args = parser.parse_args()
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "months": args.months,
              "status": "passed", "districts": [], "scope": "서울 구별 추천 상위 후보의 주소 완전성·주소 확인 출처. 개별 매물 재고·호가 검증은 제외."}
    districts = {args.district: DISTRICTS[args.district]} if args.district else DISTRICTS
    for code, name in districts.items():
        started = time.monotonic()
        response = requests.post(args.api_url.rstrip("/") + "/api/recommendation/complexes", json={
            "region": f"서울특별시 {name}", "region_code": code + "00000", "months": args.months,
            "limit": 10, "require_complete_address": True}, timeout=(10, 180))
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        failures = [item["complex_name"] for item in results
                    if not item.get("jibun_address") or not item.get("road_address") or item.get("address_status") != "matched"]
        row = {"lawd_code": code, "district": name, "count": len(results),
               "pending_count": len(data.get("address_pending") or []), "failures": failures,
               "elapsed_seconds": round(time.monotonic() - started, 2),
               "results": [{key: item.get(key) for key in ("complex_name", "dong", "road_address", "jibun_address",
                   "address_status", "address_source", "address_checked_at", "official_jibuns")} for item in results],
               "pending": data.get("address_pending") or [], "error": data.get("error")}
        if failures or not results or data.get("error") or data.get("address_policy") != "verified_only":
            report["status"] = "failed"
        report["districts"].append(row)
        print(json.dumps({key: row[key] for key in ("district", "count", "pending_count", "failures", "elapsed_seconds")}, ensure_ascii=False), flush=True)
    report["result_count"] = sum(row["count"] for row in report["districts"])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['status']}: {len(report['districts'])}개 구, {report['result_count']}개 후보")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
