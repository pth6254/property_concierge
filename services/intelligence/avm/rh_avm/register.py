"""건축물대장(국토교통부 건축HUB) 조회. 전용면적이 비어 있거나 실거래 자료에 없는 건물의 준공연도·주용도를 보완한다.

키는 MOLIT_API_KEY(공공데이터포털 일반 인증키)를 쓴다. 키가 없거나 조회가 실패하면 None을 돌려주고,
호출 측은 그 사실을 basis에 적은 뒤 다른 근거로 추정을 계속한다(실패를 숨기지 않는다).
"""
from __future__ import annotations

import csv
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = "https://apis.data.go.kr/1613000/BldRgstHubService"
_CODES: dict[tuple[str, str], str] | None = None


def legal_dong_code(lawd: str, dong: str) -> str | None:
    """시군구코드+법정동명 → 법정동 10자리 코드 (data/legal_dong_codes.csv, 행정안전부 법정동코드)."""
    global _CODES
    if _CODES is None:
        with open(Path(__file__).resolve().parent.parent / "data" / "legal_dong_codes.csv", encoding="utf-8") as handle:
            _CODES = {(row["sigungu_code"], row["dong"]): row["code"] for row in csv.DictReader(handle)}
    return _CODES.get((lawd, dong))


def _key() -> str | None:
    key = os.environ.get("MOLIT_API_KEY", "").strip()
    return urllib.parse.unquote(key) if key else None


def _items(endpoint: str, params: dict) -> list[dict] | None:
    key = _key()
    if not key:
        return None
    query = urllib.parse.urlencode(params | {"serviceKey": key, "numOfRows": 100, "pageNo": 1, "_type": "xml"})
    try:
        root = ET.fromstring(urllib.request.urlopen(f"{ROOT}/{endpoint}?{query}", timeout=20).read())
    except Exception:
        return None
    if root.findtext(".//resultCode", "") not in ("00", "000"):
        return None
    return [{child.tag: (child.text or "").strip() for child in item} for item in root.findall(".//item")]


def _parcel(lawd: str, dong: str, jibun: str) -> dict | None:
    code = legal_dong_code(lawd, dong)
    if not code or jibun.startswith("산"):
        return None
    main, _, sub = jibun.partition("-")
    if not main.isdigit() or (sub and not sub.isdigit()):
        return None
    return {"sigunguCd": code[:5], "bjdongCd": code[5:], "platGbCd": "0", "bun": main.zfill(4), "ji": (sub or "0").zfill(4)}


def building_title(lawd: str, dong: str, jibun: str) -> dict | None:
    """표제부: 사용승인 연도·주용도·지상층수. 같은 지번에 건물이 여러 동이면 주용도가 공동주택인 첫 동을 쓰지 않고 합의값만 쓴다."""
    params = _parcel(lawd, dong, jibun)
    items = _items("getBrTitleInfo", params) if params else None
    if not items:
        return None
    years = {item.get("useAprDay", "")[:4] for item in items if re.fullmatch(r"\d{8}", item.get("useAprDay", ""))}
    uses = {item.get("mainPurpsCdNm", "") for item in items if item.get("mainPurpsCdNm")}
    return {"year_built": int(years.pop()) if len(years) == 1 else None,
            "main_use": uses.pop() if len(uses) == 1 else ("/".join(sorted(uses)) if uses else ""),
            "buildings": len(items)}


def unit_area(lawd: str, dong: str, jibun: str, ho: str) -> float | None:
    """전유부: 지번+호의 전유 면적 합. 여러 동에 같은 호가 있어 하나로 정해지지 않으면 None."""
    params = _parcel(lawd, dong, jibun)
    number = re.sub(r"[^0-9A-Za-z]", "", str(ho or "")).upper()
    if not params or not number:
        return None
    items = _items("getBrExposPubuseAreaInfo", params | {"hoNm": number + "호"}) or _items("getBrExposPubuseAreaInfo", params | {"hoNm": number})
    if not items:
        return None
    exclusive = [item for item in items if item.get("exposPubuseGbCd") == "1"
                 and re.sub(r"[^0-9A-Za-z]", "", item.get("hoNm", "")).upper() == number]
    buildings = {item.get("dongNm", "") for item in exclusive}
    if not exclusive or len(buildings) != 1:
        return None
    try:
        total = sum(float(item["area"]) for item in exclusive)
    except (KeyError, ValueError):
        return None
    return round(total, 2) if total > 0 else None
