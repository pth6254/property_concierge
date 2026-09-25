"""단지명·법정동·시군구를 대조한 상세 주소. 매물 재고 확인과는 별개다."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import re

import requests

from cache_db import cache_get, cache_set
from geocoding import KAKAO_API_KEY, KAKAO_ADDR_URL, KAKAO_KWD_URL


def _name(value: str) -> str:
    # 국토부의 '초안1'과 장소명의 '초안1단지아파트'를 대응하되 번호는 보존한다.
    name = re.sub(r"[^0-9a-z가-힣]", "", value.lower()).removesuffix("아파트")
    name = re.sub(r"(\d+)단지$", r"\1", name)
    phases = re.findall(r"\d+차", name)
    # '상계현대3차' / '상계3차현대'처럼 차수 위치만 다른 표기를 통일한다.
    return re.sub(r"\d+차", "", name) + "".join(phases)


def _request(url: str, query: str) -> list[dict]:
    response = requests.get(url, headers={"Authorization": f"KakaoAK {KAKAO_API_KEY}"},
                            params={"query": query, "size": 15}, timeout=4)
    response.raise_for_status()
    return response.json().get("documents", [])


def resolve_complex_address(region: str, lawd_code: str, dong: str, name: str, *, force=False) -> dict:
    missing = {"road_address": "", "jibun_address": "", "address_status": "unresolved",
               "address_source": "", "address_checked_at": None}
    if not KAKAO_API_KEY or not dong or not _name(name):
        return missing
    key = dict(lawd_code=lawd_code, dong=dong, name=name)
    cached = None if force else cache_get("complex_address_v3", **key)
    if cached is not None:
        return cached
    try:
        scope = region if region.endswith(dong) else f"{region} {dong}"
        places = _request(KAKAO_KWD_URL, f"{scope} {name}")
        matches = {p.get("address_name", ""): p for p in places
                   if _name(p.get("place_name", "")) == _name(name)
                   and (p.get("category_name", "").split(" > ")[-1] == "아파트")
                   and dong in p.get("address_name", "").split()
                   and re.search(r"\d+(?:-\d+)?$", p.get("address_name", ""))}
        # 검색 첫 결과를 고르면 동명 단지·중개업소를 잘못 연결할 수 있다.
        if len(matches) != 1:
            result = {**missing, "address_status": "ambiguous" if len(matches) > 1 else "unresolved"}
        else:
            jibun = next(iter(matches))
            addresses = _request(KAKAO_ADDR_URL, jibun)
            exact = [d for d in addresses
                     if (d.get("address") or {}).get("address_name") == jibun
                     and (d.get("address") or {}).get("b_code", "")[:5] == lawd_code
                     and (d.get("address") or {}).get("region_3depth_name") == dong
                     and (d.get("address") or {}).get("main_address_no")]
            if len(exact) != 1:
                result = missing
            else:
                result = {"road_address": (exact[0].get("road_address") or {}).get("address_name", ""),
                          "jibun_address": jibun, "address_status": "matched",
                          "matched_name": matches[jibun].get("place_name", ""),
                          "source_place_id": matches[jibun].get("id", ""),
                          "latitude": float(exact[0]["y"]) if exact[0].get("y") else None,
                          "longitude": float(exact[0]["x"]) if exact[0].get("x") else None,
                          "address_source": "카카오 로컬 장소·주소 검색",
                          "address_checked_at": datetime.now(timezone.utc).isoformat()}
        cache_set(result, ttl=86400 * 7 if result["address_status"] == "matched" else 3600,
                  namespace="complex_address_v3", **key)
        return result
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        # 일시 장애로 추천 자체가 실패하거나 실패 응답이 장기 캐시되지 않게 한다.
        return {**missing, "address_status": "unavailable"}


def enrich_complex_addresses(results: list[dict], region: str, lawd_code: str) -> None:
    if not results:
        return
    # 전체 거래가 아니라 최종 추천 단지만 조회하고 외부 호출 동시성을 제한한다.
    with ThreadPoolExecutor(max_workers=4) as pool:
        from services.complex_catalog import lookup
        resolved = pool.map(lambda c: lookup(region, lawd_code, c["dong"], c["complex_name"]), results)
        for item, address in zip(results, resolved):
            item.update(address)
