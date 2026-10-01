"""주소와 이름의 조회 근거를 서명해 저장 시 사용자 입력과 구분한다."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from xml.etree import ElementTree

import requests
from pydantic import ValidationError

from api.auth_utils import SECRET_KEY
from schemas.listing_address import ListingAddress, ListingAddressChoice

KAKAO_ROOT = "https://dapi.kakao.com/v2/local/search/"
TOKEN_SECONDS = 3600


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _signature(body: str) -> str:
    # 인증 JWT와 다른 형식·용도다. 주소 증명으로 로그인 세션을 만들 수 없게 한다.
    return _encode(hmac.new(SECRET_KEY.encode(), b"listing-address-v1:" + body.encode(), hashlib.sha256).digest())


def sign_address(address: ListingAddress, user_id: int) -> str:
    body = _encode(json.dumps({"owner": user_id, "expires": time.time() + TOKEN_SECONDS,
                              "address": address.model_dump()}, ensure_ascii=False, separators=(",", ":")).encode())
    return body + "." + _signature(body)


def verified_address(token: str, user_id: int) -> ListingAddress:
    try:
        body, signature = token.split(".")
        if not hmac.compare_digest(signature, _signature(body)):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if payload["owner"] != user_id or payload["expires"] <= time.time():
            raise ValueError
        return ListingAddress.model_validate(payload["address"])
    except (ValueError, KeyError, TypeError, ValidationError):
        raise ValueError("주소 확인 정보가 유효하지 않거나 만료되었습니다. 주소를 다시 검색·선택해주세요.") from None


def _kakao(query: str, kind: str = "address") -> list[dict]:
    key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not key:
        raise ValueError("주소 검색 설정이 없습니다. 주소를 직접 입력하거나 관리자에게 문의해주세요.")
    response = requests.get(KAKAO_ROOT + kind + ".json", headers={"Authorization": "KakaoAK " + key},
                            params={"query": query, "size": 5}, timeout=4)
    response.raise_for_status()
    return response.json().get("documents", [])


def _register_names(address: dict) -> list[str]:
    key = os.getenv("MOLIT_API_KEY", "").strip()
    code, bun = address.get("b_code", ""), address.get("main_address_no", "")
    if not key or not re.fullmatch(r"\d{10}", code) or not bun or address.get("mountain_yn") == "Y":
        return []
    # 기존 건축 속성 함수는 첫 건을 선택한다. 이름 확인은 같은 필지의 결과를 모두 대조해야 한다.
    from backend.building_info import ENDPOINTS
    try:
        response = requests.get(ENDPOINTS["기본개요"], params={"serviceKey": requests.utils.unquote(key),
            "sigunguCd": code[:5], "bjdongCd": code[5:], "bun": str(bun).zfill(4),
            "ji": str(address.get("sub_address_no") or "0").zfill(4), "numOfRows": 100,
            "pageNo": 1, "_type": "xml"}, timeout=4)
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        if root.findtext(".//resultCode", "0").lstrip("0") or int(root.findtext(".//totalCount", "0")) > 100:
            return []
        names = set()
        for item in root.findall(".//item"):
            values = {child.tag: (child.text or "").strip() for child in item}
            # 주소 식별 필드가 없는 응답은 해당 필지의 확인 근거로 사용하지 않는다.
            if (values.get("sigunguCd") != code[:5] or values.get("bjdongCd") != code[5:]
                    or values.get("bun", "").zfill(4) != str(bun).zfill(4)
                    or values.get("ji", "0").zfill(4) != str(address.get("sub_address_no") or "0").zfill(4)):
                continue
            name = values.get("bldNm", "")
            if name and len(name) <= 150:
                names.add(name)
        return sorted(names)[:10]
    except (requests.RequestException, ElementTree.ParseError, ValueError):
        # 보조 조회 실패는 주소를 지우거나 존재하지 않는 이름을 만들어낼 이유가 아니다.
        return []


def _normalize(document: dict) -> ListingAddress | None:
    address, road = document.get("address") or {}, document.get("road_address") or {}
    if not address.get("main_address_no") or not re.fullmatch(r"\d{10}", address.get("b_code", "")):
        return None
    try:
        name = str(road.get("building_name") or "").strip()
        names = _register_names(address) if not name else []
        if not name and len(names) == 1:
            name, name_source = names[0], "building_register"
        else:
            name_source = "kakao_address" if name else "unknown"
        return ListingAddress(road_address=road.get("address_name") or "", jibun_address=address["address_name"],
            legal_region_code=address["b_code"], latitude=float(document["y"]), longitude=float(document["x"]),
            building_name=name, name_source=name_source,
            name_status="found" if name else "ambiguous" if names else "unknown", name_candidates=names,
            checked_at=datetime.now(timezone.utc).isoformat(), identity_level="building" if name else "parcel")
    except (ValueError, KeyError, TypeError, ValidationError):
        return None


def search_addresses(query: str, user_id: int) -> dict:
    documents = _kakao(query)
    if not documents:
        # 장소 이름만으로 건물명을 확정하지 않고, 장소의 주소를 다시 정방향 조회한다.
        places = _kakao(query, "keyword")
        addresses = list(dict.fromkeys(place.get("road_address_name") or place.get("address_name") for place in places))
        with ThreadPoolExecutor(max_workers=5) as pool:
            for result in pool.map(_kakao, [address for address in addresses if address]):
                documents.extend(result)
    with ThreadPoolExecutor(max_workers=5) as pool:
        resolved = list(pool.map(_normalize, documents[:10]))
    seen, items = set(), []
    for address in resolved:
        if address is None:
            continue
        identity = (address.legal_region_code, address.jibun_address, address.road_address, address.building_name)
        if identity in seen:
            continue
        seen.add(identity)
        items.append(ListingAddressChoice(**address.model_dump(), token=sign_address(address, user_id)).model_dump())
    return {"items": items}
