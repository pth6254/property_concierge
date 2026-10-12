"""국토교통부 연립다세대 매매 실거래가를 공공데이터포털 API에서 수집해 data/rh_trades.csv로 저장한다.

python collect.py --from 202310 --to 202610
환경변수 MOLIT_API_KEY(공공데이터포털 일반 인증키, 인코딩/디코딩 형식 모두 가능)가 필요하다.
개인정보(매수·매도인 정보 외 식별 정보)는 원천에 없으며, 구분값(개인/법인)도 저장하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

URL = "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade"
REGIONS = {"11500": "서울특별시 강서구", "11620": "서울특별시 관악구", "11680": "서울특별시 강남구"}
COLUMNS = ["id", "sigungu_code", "dong", "jibun", "building_name", "deal_year", "deal_month", "deal_day", "price_manwon",
           "area_m2", "floor", "build_year", "land_area_m2", "house_type", "deal_type", "cancelled"]


def service_key() -> str:
    key = os.environ.get("MOLIT_API_KEY", "").strip()
    if not key:
        sys.exit("MOLIT_API_KEY 환경변수가 필요합니다 (README 참고)")
    # 원문 키의 '+'를 공백으로 바꾸지 않도록 한 번 디코딩한 뒤 쿼리에서 한 번만 인코딩한다.
    return urllib.parse.unquote(key)


def months(start: str, end: str) -> list[str]:
    y, m, out = int(start[:4]), int(start[4:]), []
    while f"{y:04d}{m:02d}" <= end:
        out.append(f"{y:04d}{m:02d}"); m += 1
        if m == 13: y, m = y + 1, 1
    return out


def fetch_month(key: str, lawd: str, ym: str) -> list[dict]:
    rows, page = [], 1
    while True:
        query = urllib.parse.urlencode({"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ym, "numOfRows": 1000, "pageNo": page})
        for attempt in range(3):
            try:
                root = ET.fromstring(urllib.request.urlopen(f"{URL}?{query}", timeout=30).read())
                break
            except Exception:
                if attempt == 2: raise
                time.sleep(2)
        code = root.findtext(".//resultCode", "")
        if code not in ("00", "000"):
            raise RuntimeError(f"API 오류 {code}: {root.findtext('.//resultMsg', '')}")
        items = root.findall(".//item")
        for item in items:
            text = lambda tag: (item.findtext(tag) or "").strip()
            rows.append({"sigungu_code": lawd, "dong": text("umdNm"), "jibun": text("jibun"), "building_name": text("mhouseNm"),
                         "deal_year": text("dealYear"), "deal_month": text("dealMonth"), "deal_day": text("dealDay"),
                         "price_manwon": text("dealAmount").replace(",", ""), "area_m2": text("excluUseAr"), "floor": text("floor"),
                         "build_year": text("buildYear"), "land_area_m2": text("landAr"), "house_type": text("houseType"),
                         "deal_type": text("dealingGbn"), "cancelled": "1" if text("cdealDay") else "0"})
        total = int(root.findtext(".//totalCount", "0") or 0)
        if page * 1000 >= total or not items:
            return rows
        page += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="연립다세대 매매 실거래 수집")
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--output", default=str(Path(__file__).parent / "data" / "rh_trades.csv"))
    args = parser.parse_args()
    key, rows = service_key(), []
    for lawd, name in REGIONS.items():
        for ym in months(args.start, args.end):
            got = fetch_month(key, lawd, ym)
            rows.extend(got)
            print(f"{name} {ym}: {len(got)}건", flush=True)
    for index, row in enumerate(rows, 1):
        row["id"] = index
    with open(args.output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader(); writer.writerows(rows)
    print(f"저장: {args.output} ({len(rows)}건)")


if __name__ == "__main__":
    main()
