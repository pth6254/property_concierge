"""실거래 필지·법정동·시군구를 대조한 단지 대표 주소. 매물 재고 확인과는 별개다."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import re
import requests

from cache_db import cache_get, cache_set
from geocoding import KAKAO_API_KEY, KAKAO_ADDR_URL, KAKAO_KWD_URL
from services.complex_parcel_service import normalize_parcel

ADDRESS_VERSION = 4


def _name(value: str) -> str:
    name = re.sub(r"[^0-9a-z가-힣]", "", value.lower()).removesuffix("아파트")
    name = re.sub(r"(\d+)단지$", r"\1", name)
    phases = re.findall(r"\d+차", name)
    return re.sub(r"\d+차", "", name) + "".join(phases)


def is_complete_address(value: dict) -> bool:
    return value.get("address_status") == "matched" and bool(value.get("road_address")) and bool(value.get("jibun_address"))


def _request(url: str, query: str) -> list[dict]:
    response = requests.get(url, headers={"Authorization": f"KakaoAK {KAKAO_API_KEY}"},
                            params={"query": query, "size": 15}, timeout=4)
    response.raise_for_status()
    return response.json().get("documents", [])


def _parcel_of_address(address: dict) -> str:
    main = address.get("main_address_no")
    if not main:
        return ""
    sub = address.get("sub_address_no")
    return normalize_parcel(("산 " if address.get("mountain_yn") == "Y" else "")
                            + str(main) + (f"-{sub}" if sub and str(sub) != "0" else ""))


def _matching_addresses(documents: list[dict], lawd_code: str, dong: str, parcel: str) -> list[dict]:
    return [document for document in documents
            if (address := document.get("address") or {}).get("b_code", "")[:5] == lawd_code
            and address.get("region_3depth_name") == dong
            and _parcel_of_address(address) == parcel
            and dong in address.get("address_name", "").split()
            and normalize_parcel(address.get("address_name", "").split(dong, 1)[-1].strip()) == parcel]


def _coordinate_address(document: dict, lawd_code: str, dong: str, parcel: str) -> dict | None:
    if not document.get("x") or not document.get("y"):
        return None
    response = requests.get("https://dapi.kakao.com/v2/local/geo/coord2address.json",
        headers={"Authorization": f"KakaoAK {KAKAO_API_KEY}"},
        params={"x": document["x"], "y": document["y"]}, timeout=4)
    response.raise_for_status()
    for candidate in response.json().get("documents", []):
        address = candidate.get("address") or {}
        # 좌표 역검색이 옆 필지를 반환하면 원래 거래의 주소로 채택하지 않는다.
        if (address.get("region_3depth_name") == dong
                and address.get("region_2depth_name") == document["address"].get("region_2depth_name")
                and _parcel_of_address(address) == parcel and (candidate.get("road_address") or {}).get("address_name")):
            road = candidate["road_address"]["address_name"]
            # 역검색에는 법정동코드가 없어 도로명 정방향 조회로 한 번 더 대조한다.
            verified = _matching_addresses(_request(KAKAO_ADDR_URL, road), lawd_code, dong, parcel)
            if len(verified) == 1 and (verified[0].get("road_address") or {}).get("address_name"):
                return {**document, "road_address": verified[0]["road_address"]}
    return None


def _place_name_matches(place_name: str, name: str, dong: str) -> bool:
    def without_dong(value: str) -> str:
        normalized = _name(value)
        for prefix in (dong, dong.removesuffix("동")):
            if prefix and normalized.startswith(prefix):
                return normalized[len(prefix):]
        return normalized
    # 동 접두어만 허용한다. 다른 브랜드·차수에 느슨하게 붙이지 않는다.
    return without_dong(place_name) == without_dong(name)


def resolve_complex_address(region: str, lawd_code: str, dong: str, name: str, *,
                            force=False, official_jibuns: list[str] | None = None) -> dict:
    parcels = sorted({parcel for value in (official_jibuns or []) if (parcel := normalize_parcel(value))})
    missing = {"road_address": "", "jibun_address": "", "address_status": "unresolved",
               "address_source": "", "address_checked_at": None, "address_version": ADDRESS_VERSION,
               "official_jibuns": parcels}
    if not KAKAO_API_KEY or not dong or not _name(name):
        return missing
    key = dict(lawd_code=lawd_code, dong=dong, name=name, official_jibuns=parcels)
    cached = None if force else cache_get("complex_address_v4", **key)
    if cached is not None:
        return cached
    try:
        scope = region if region.endswith(dong) else f"{region} {dong}"
        place = {}
        if len(parcels) > 1:
            result = {**missing, "address_status": "ambiguous", "address_reason": "동일한 단지명에 여러 실거래 필지가 있어 대표 주소 확인이 필요합니다."}
        else:
            if parcels:
                parcel = parcels[0]
                query = f"{scope} {parcel}"
            else:
                places = _request(KAKAO_KWD_URL, f"{scope} {name}")
                matches = {p.get("address_name", ""): p for p in places
                    if _place_name_matches(p.get("place_name", ""), name, dong)
                    and p.get("category_name", "").split(" > ")[-1] == "아파트"
                    and dong in p.get("address_name", "").split()
                    and re.search(r"\d+(?:-\d+)?$", p.get("address_name", ""))}
                if len(matches) != 1:
                    result = {**missing, "address_status": "ambiguous" if len(matches) > 1 else "unresolved"}
                    cache_set(result, ttl=3600, namespace="complex_address_v4", **key)
                    return result
                query, place = next(iter(matches.items()))
                parcel = normalize_parcel(query.split(dong, 1)[-1].strip())
            exact = _matching_addresses(_request(KAKAO_ADDR_URL, query), lawd_code, dong, parcel)
            if len(exact) != 1:
                result = {**missing, "address_status": "ambiguous" if len(exact) > 1 else "unresolved"}
            else:
                document = exact[0]
                if not (document.get("road_address") or {}).get("address_name"):
                    document = _coordinate_address(document, lawd_code, dong, parcel) or document
                road = (document.get("road_address") or {}).get("address_name", "")
                result = {**missing, "road_address": road,
                          "jibun_address": document["address"]["address_name"],
                          "address_status": "matched" if road else "unresolved",
                          "address_reason": "" if road else "공식 지번은 확인했으나 대응하는 도로명 주소를 확인하지 못했습니다.",
                          "matched_name": place.get("place_name") or name,
                          "source_place_id": place.get("id", ""),
                          "latitude": float(document["y"]) if document.get("y") else None,
                          "longitude": float(document["x"]) if document.get("x") else None,
                          "address_source": "국토교통부 실거래 지번 · 카카오 로컬 주소 대조" if parcels else "카카오 로컬 장소·주소 검색",
                          "address_checked_at": datetime.now(timezone.utc).isoformat()}
        cache_set(result, ttl=86400 * 7 if is_complete_address(result) else 3600,
                  namespace="complex_address_v4", **key)
        return result
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return {**missing, "address_status": "unavailable"}


def enrich_complex_addresses(results: list[dict], region: str, lawd_code: str) -> None:
    if not results:
        return
    from services.complex_parcel_service import attach_official_parcels
    from services.complex_catalog import lookup
    attach_official_parcels(results, lawd_code)
    with ThreadPoolExecutor(max_workers=4) as pool:
        resolved = pool.map(lambda c: lookup(region, lawd_code, c["dong"], c["complex_name"],
                                            official_jibuns=c.get("official_jibuns")), results)
        for item, address in zip(results, resolved):
            item.update(address)
