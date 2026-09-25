"""주소 오연결 방지: 동명 단지·차수·중개업소·API 장애를 구분한다."""
import pytest
import requests

from services import complex_address_service as service
from services.complex_recommend_service import _aggregate_complexes


@pytest.fixture
def lookup(monkeypatch):
    place = {"place_name": "상계주공10단지아파트", "category_name": "부동산 > 주거시설 > 아파트",
             "address_name": "서울 노원구 상계동 666"}
    address = {"address": {"address_name": place["address_name"], "b_code": "1135010500",
                           "region_3depth_name": "상계동", "main_address_no": "666"},
               "road_address": {"address_name": "서울 노원구 노원로 564"}}
    data = {"places": [place], "addresses": [address], "saved": []}
    monkeypatch.setattr(service, "KAKAO_API_KEY", "test-key")
    monkeypatch.setattr(service, "cache_get", lambda *a, **kw: None)
    monkeypatch.setattr(service, "cache_set", lambda value, **kw: data["saved"].append(value))
    monkeypatch.setattr(service, "_request", lambda url, query: data["places"] if url == service.KAKAO_KWD_URL else data["addresses"])
    return data


def resolve():
    return service.resolve_complex_address("서울특별시 노원구", "11350", "상계동", "상계주공(10단지)")


def test_exact_name_dong_and_region_returns_both_addresses(lookup):
    result = resolve()
    assert result["address_status"] == "matched"
    assert result["road_address"] == "서울 노원구 노원로 564"
    assert result["jibun_address"] == "서울 노원구 상계동 666"
    assert result["address_checked_at"]
    assert lookup["saved"] == [result]


@pytest.mark.parametrize("field,value", [("b_code", "1168010100"), ("region_3depth_name", "중계동"),
                                         ("address_name", "서울 노원구 상계동 667")])
def test_address_search_must_match_original_place(lookup, field, value):
    lookup["addresses"][0]["address"][field] = value
    assert resolve()["jibun_address"] == ""


@pytest.mark.parametrize("field,value", [("place_name", "상계주공11단지아파트"),
                                         ("category_name", "부동산 > 중개업소"),
                                         ("address_name", "서울 노원구 중계동 666")])
def test_different_phase_broker_or_dong_is_rejected(lookup, field, value):
    lookup["places"][0][field] = value
    assert resolve()["address_status"] == "unresolved"


def test_multiple_addresses_are_not_silently_selected(lookup):
    lookup["places"].append({**lookup["places"][0], "address_name": "서울 노원구 상계동 667"})
    assert resolve()["address_status"] == "ambiguous"


def test_failure_is_not_cached(lookup, monkeypatch):
    def fail(*args):
        raise requests.Timeout()
    monkeypatch.setattr(service, "_request", fail)
    assert resolve()["address_status"] == "unavailable"
    assert not lookup["saved"]


def test_cached_address_avoids_network(lookup, monkeypatch):
    cached = resolve()
    monkeypatch.setattr(service, "cache_get", lambda *a, **kw: cached)
    monkeypatch.setattr(service, "_request", lambda *args: pytest.fail("캐시가 있으면 API 호출 금지"))
    assert resolve() == cached


def test_same_name_in_different_dongs_stays_separate():
    samples = [{"apt_name": "현대", "dong": dong, "price": price, "area_sqm": 80,
                "per_sqm": price / 80, "deal_year": "2026", "deal_month": "9"}
               for dong, price in [("상계동", 50000), ("중계동", 90000)] for _ in range(2)]
    results = _aggregate_complexes(samples)
    assert {(c["dong"], c["avg_price"]) for c in results} == {("상계동", 50000), ("중계동", 90000)}


def test_official_abbreviations_preserve_phase_numbers():
    assert service._name("상계현대3차") == service._name("상계3차현대아파트")
    assert service._name("초안1") == service._name("초안1단지아파트")
    assert service._name("초안1") != service._name("초안10단지아파트")
    assert service._name("현대1차") != service._name("현대2차")
