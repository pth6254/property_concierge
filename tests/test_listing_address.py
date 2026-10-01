"""주소 조회·서명·소유권·이름/별칭 분리와 후보 저장을 검증한다."""
import csv
import io
import time

import pytest
import requests

from backend.services import listing_address_service as addresses
from tests.test_listing_import import regions, row
from tests.test_market_explorer import client


def document(name="주소 검증 단지", **changes):
    return {"x": "127.04", "y": "37.5", "address": {"address_name": "서울 강남구 역삼동 123",
        "b_code": "1168010100", "main_address_no": "123", "sub_address_no": "", "mountain_yn": "N"},
        "road_address": {"address_name": "서울 강남구 테헤란로 123", "building_name": name}, **changes}


@pytest.fixture
def lookup(regions, monkeypatch):
    monkeypatch.setattr(addresses, "_kakao", lambda query, kind="address": [document()])
    monkeypatch.setattr(addresses, "_register_names", lambda address: [])
    return regions


def chosen(client):
    response = client.get("/api/listings/address/search", params={"query": "테헤란로 123"})
    assert response.status_code == 200, response.text
    return response.json()["items"][0]


def upload_address(client, choice, **changes):
    data = row(name=choice["building_name"] or choice["jibun_address"][:150], address=choice["jibun_address"],
               legal_region_code="", alias="", address_token=choice["token"])
    data.update(changes)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(data))
    writer.writeheader(); writer.writerow(data)
    return client.post("/api/listings/import", json={"source_name": "주소·중개사 확인", "csv_text": stream.getvalue(), "commit": True})


@pytest.mark.parametrize("alias", ["", "출퇴근 후보", '첫 임장, "남향"', "  출퇴근 후보  "])
def test_address_name_alias_and_candidate_restore(lookup, alias):
    choice = chosen(lookup)
    result = upload_address(lookup, choice, alias=alias)
    assert result.status_code == 200 and result.json()["created"] == 1, result.text
    listing = lookup.get("/api/listings").json()["items"][0]
    assert listing["name"] == "주소 검증 단지" and listing["alias"] == alias.strip()
    assert listing["address"] == "서울특별시 강남구 역삼동 123"
    assert listing["legal_region_code"] == "1168010100"
    assert listing["address_details"]["road_address"] == "서울특별시 강남구 테헤란로 123"
    assert listing["address_details"]["name_source"] == "kakao_address"
    assert "address_token" not in listing
    case_id = lookup.post("/api/cases", json={"title": "주소 등록 후보"}).json()["id"]
    endpoint = f"/api/listings/{listing['id']}/candidate"
    candidate = lookup.post(endpoint, json={"case_id": case_id}).json()
    assert candidate["alias"] == alias.strip() and candidate["name"] == listing["name"]
    assert candidate["address_details"] == listing["address_details"]
    restored = lookup.get(f"/api/cases/{case_id}").json()["properties"][0]
    assert restored["alias"] == alias.strip()
    assert restored["source_status"]["status"] == "current"
    history = lookup.get(f"/api/listings/{listing['id']}/history").json()["items"][0]
    assert history["alias"] == alias.strip() and "address_token" not in history


@pytest.mark.parametrize("change", ["name", "address", "token", "alias"])
def test_modified_address_proof_and_invalid_alias_never_save(lookup, change):
    choice = chosen(lookup)
    changes = {"name": "내가 만든 건물명"} if change == "name" else {"address": "서울 강남구 역삼동 456"} if change == "address" else {"address_token": choice["token"] + "x"} if change == "token" else {"alias": "가" * 101}
    result = upload_address(lookup, choice, **changes).json()
    assert not result["valid"] and result["errors"]
    assert lookup.get("/api/listings").json()["total"] == 0


def test_address_proof_owner_expiry_and_not_auth_cookie(lookup, monkeypatch):
    choice = chosen(lookup)
    owner_id = lookup.get("/api/auth/me").json()["id"]
    with pytest.raises(ValueError): addresses.verified_address(choice["token"], owner_id + 1)
    clock = time.time()
    monkeypatch.setattr(addresses.time, "time", lambda: clock + addresses.TOKEN_SECONDS + 1)
    with pytest.raises(ValueError): addresses.verified_address(choice["token"], owner_id)
    monkeypatch.undo()
    lookup.cookies.clear()
    assert lookup.get("/api/listings/address/search?query=역삼동").status_code == 401
    lookup.cookies.set("auth_token", choice["token"])
    assert lookup.get("/api/auth/me").status_code == 401
    lookup.cookies.clear()
    assert lookup.post("/api/auth/register", json={"email": "address-other@example.com", "password": "address-other-1234", "name": "다른 사용자"}).status_code == 201
    assert not upload_address(lookup, choice).json()["valid"]


@pytest.mark.parametrize("names,status,name", [([], "unknown", ""), (["대장 건물명"], "found", "대장 건물명"), (["A동", "B동"], "ambiguous", "")])
def test_missing_or_multiple_building_names_are_not_guessed(lookup, monkeypatch, names, status, name):
    monkeypatch.setattr(addresses, "_kakao", lambda query, kind="address": [document("")])
    monkeypatch.setattr(addresses, "_register_names", lambda address: names)
    choice = chosen(lookup)
    assert choice["building_name"] == name and choice["name_status"] == status
    assert upload_address(lookup, choice).json()["committed"]
    saved = lookup.get("/api/listings").json()["items"][0]
    assert saved["address_details"]["building_name"] == name
    assert saved["name"] == (name or "서울특별시 강남구 역삼동 123")


def test_keyword_place_name_is_not_used_as_building_name(lookup, monkeypatch):
    def provider(query, kind="address"):
        if kind == "keyword": return [{"place_name": "건물 안 카페", "address_name": "서울 강남구 역삼동 123"}]
        return [] if query == "건물 안 카페" else [document()]
    monkeypatch.setattr(addresses, "_kakao", provider)
    choice = lookup.get("/api/listings/address/search?query=건물 안 카페").json()["items"][0]
    assert choice["building_name"] == "주소 검증 단지"


def test_provider_failure_and_non_address_results(lookup, monkeypatch):
    monkeypatch.setattr(addresses, "_kakao", lambda *args: (_ for _ in ()).throw(requests.Timeout("secret-key-must-not-leak")))
    response = lookup.get("/api/listings/address/search?query=역삼동")
    assert response.status_code == 502 and "secret-key" not in response.text
    monkeypatch.setattr(addresses, "_kakao", lambda *args: [document(address={"b_code": "1168010100"})])
    assert lookup.get("/api/listings/address/search?query=역삼동").json()["items"] == []
    assert lookup.get("/api/listings/address/search?query=%20%20").status_code == 422
