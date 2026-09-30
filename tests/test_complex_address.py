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


def test_official_parcel_resolves_abbreviation_without_keyword_guess(lookup, monkeypatch):
    calls = []
    def fetch(url, query):
        calls.append((url, query))
        assert url == service.KAKAO_ADDR_URL
        return lookup["addresses"]
    monkeypatch.setattr(service, "_request", fetch)
    result = service.resolve_complex_address("서울특별시 노원구 상계동", "11350", "상계동", "주공10",
                                              official_jibuns=["0666"])
    assert service.is_complete_address(result)
    assert calls == [(service.KAKAO_ADDR_URL, "서울특별시 노원구 상계동 666")]
    assert "국토교통부" in result["address_source"]


def test_road_address_missing_is_never_marked_matched(lookup):
    lookup["addresses"][0]["road_address"] = None
    result = resolve()
    assert result["jibun_address"] and not result["road_address"]
    assert result["address_status"] == "unresolved"
    assert not service.is_complete_address(result)


def test_multiple_official_parcels_require_review(lookup, monkeypatch):
    monkeypatch.setattr(service, "_request", lambda *args: pytest.fail("대표 필지를 임의 선택하면 안 됩니다"))
    result = service.resolve_complex_address("서울 노원구", "11350", "상계동", "현대", official_jibuns=["666", "667"])
    assert result["address_status"] == "ambiguous"
    assert not service.is_complete_address(result)


def test_dong_prefix_is_allowed_but_other_brand_or_phase_is_not(lookup):
    lookup["places"][0]["place_name"] = "상계주공10단지아파트"
    assert service.resolve_complex_address("서울 노원구", "11350", "상계동", "주공10")["address_status"] == "matched"
    assert not service._place_name_matches("학여울청구아파트", "청구", "하계동")
    assert not service._place_name_matches("하계1차청구아파트", "하계2차청구", "하계동")


def test_coordinate_fallback_rejects_neighboring_parcel(lookup, monkeypatch):
    lookup["addresses"][0].update(x="127.0", y="37.0", road_address=None)
    from types import SimpleNamespace
    other = {"address": {"region_3depth_name": "상계동", "main_address_no": "667"},
             "road_address": {"address_name": "서울 노원구 잘못된길 1"}}
    monkeypatch.setattr(service.requests, "get", lambda *a, **kw: SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"documents": [other]}))
    result = resolve()
    assert result["road_address"] == "" and result["address_status"] == "unresolved"


def test_coordinate_fallback_requires_forward_address_confirmation(lookup, monkeypatch):
    import copy
    from types import SimpleNamespace
    document = lookup["addresses"][0]
    document["address"]["region_2depth_name"] = "노원구"
    verified = copy.deepcopy(document)
    document.update(x="127.0", y="37.0", road_address=None)
    reverse = {"address": {"region_2depth_name": "노원구", "region_3depth_name": "상계동", "main_address_no": "666"},
               "road_address": verified["road_address"]}
    monkeypatch.setattr(service.requests, "get", lambda *a, **kw: SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"documents": [reverse]}))
    def request(url, query):
        if url == service.KAKAO_KWD_URL:
            return lookup["places"]
        return [verified] if query == "서울 노원구 노원로 564" else [document]
    monkeypatch.setattr(service, "_request", request)
    assert service.is_complete_address(resolve())
