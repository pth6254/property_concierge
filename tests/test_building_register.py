"""격리 Spring의 건축물대장 조회·확인 서명·매물 및 후보 근거 보존 검증."""
import pytest

from db.redis_client import get_redis
from tests.test_listing_address import configure, document, chosen, upload_address
from tests.test_listing_import import regions
from tests.test_market_explorer import client


def record(**values):
    return {"sigunguCd": "11680", "bjdongCd": "10100", "bun": "0123", "ji": "0000", "platGbCd": "0", **values}


def configuration(*, dong="101동", other=False, failed=False):
    cache = get_redis()
    keys = list(cache.scan_iter(match="building-register:v1:*"))
    if keys:
        cache.delete(*keys)
    title = record(mgmBldrgstPk="building-main", bldNm="공식 조회 단지", dongNm=dong, mainAtchGbCd="0",
                   mainPurpsCdNm="아파트", totArea="12000", useAprDay="19991125", hhldCnt="120", rideUseElvtCnt="2")
    titles = [record(mgmBldrgstPk="guard", dongNm="경비실", mainAtchGbCd="1", totArea="5.5"), title]
    if other:
        titles.append(title | {"mgmBldrgstPk": "building-other", "dongNm": "102동"})
    configure(documents=[document("공식 조회 단지")], register_failure=failed, register_records={
        "getBrTitleInfo": titles,
        "getBrRecapTitleInfo": [record(mgmBldrgstPk="complex", hhldCnt="500", totPkngCnt="600", totArea="60000")],
        "getBrFlrOulnInfo": [record(mgmBldrgstPk="building-main", dongNm=dong, flrNo="5", flrNoNm="5층", area="1000", mainPurpsCdNm="아파트")],
        "getBrExposPubuseAreaInfo": [
            record(mgmBldrgstPk="unit-main", dongNm=dong, hoNm="501호", exposPubuseGbCd="1", area="84.9", flrNo="5", flrNoNm="5층", mainPurpsCdNm="아파트"),
            record(mgmBldrgstPk="unit-main", dongNm=dong, hoNm="501호", exposPubuseGbCd="2", area="35.5", flrNoNm="각층", mainPurpsCdNm="아파트"),
            record(mgmBldrgstPk="wrong-unit", dongNm="102동", hoNm="501호", exposPubuseGbCd="1", area="59.9"),
        ],
        "getBrJijiguInfo": [record(jijiguCdNm="일반주거지역")],
    })


@pytest.fixture
def lookup(regions):
    configuration()
    return regions


def building(client, choice, **input):
    return client.post("/api/listings/address/building", json={"address_token": choice["token"], **input})


def test_optional_dong_ho_and_first_auxiliary_are_not_used_as_unit(lookup):
    choice = chosen(lookup)
    assert choice["parcel_main_no"] == "123"
    response = building(lookup, choice)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["selected_building"]["id"] == "building-main"
    assert result["selected_building"]["fields"]["total_area_sqm"] == 12000
    assert result["complex"]["fields"]["total_area_sqm"] == 60000
    assert result["unit"]["status"] == "not_requested"
    assert upload_address(lookup, choice, building_token=result["building_token"]).json()["committed"]
    saved = lookup.get("/api/listings").json()["items"][0]
    assert saved["identity"]["building_dong"] == saved["identity"]["unit_number"] == ""
    assert saved["address_details"]["building_register"]["unit"]["status"] == "not_requested"
    assert "building_token" not in saved


def test_exact_unit_area_and_public_evidence_restore_in_candidate_and_history(lookup):
    choice = chosen(lookup)
    result = building(lookup, choice, building_dong="101", unit_number="501").json()
    assert result["unit"]["exclusive_area_sqm"] == 84.9
    assert result["unit"]["common_areas"][0]["area_sqm"] == 35.5
    assert result["floors"][0]["area_sqm"] == 1000
    response = upload_address(lookup, choice, building_token=result["building_token"], building_dong="101동",
                              unit_number="501호", area_sqm=84.9, area_basis="exclusive", alias="임장 후보")
    assert response.json()["committed"], response.text
    saved = lookup.get("/api/listings").json()["items"][0]
    evidence = saved["address_details"]["building_register"]
    assert evidence["area_matches_input"] is True
    assert evidence["source"] == "building_register" and evidence["checked_at"]
    assert "building_token" not in saved and "address_token" not in saved
    case_id = lookup.post("/api/cases", json={"title": "공식 자료 후보"}).json()["id"]
    candidate = lookup.post(f"/api/listings/{saved['id']}/candidate", json={"case_id": case_id})
    assert candidate.status_code == 201, candidate.text
    restored = lookup.get(f"/api/cases/{case_id}").json()["properties"][0]
    assert restored["address_details"]["building_register"] == evidence
    history = lookup.get(f"/api/listings/{saved['id']}/history").json()["items"][0]
    assert history["address_details"]["building_register"] == evidence and "building_token" not in history


def test_different_manual_area_is_preserved_and_not_marked_as_official(lookup):
    choice = chosen(lookup)
    result = building(lookup, choice, building_dong="101", unit_number="501").json()
    assert upload_address(lookup, choice, building_token=result["building_token"], building_dong="101", unit_number="501",
                          area_sqm=80, area_basis="exclusive").json()["committed"]
    saved = lookup.get("/api/listings").json()["items"][0]
    assert saved["area_sqm"] == 80
    assert saved["address_details"]["building_register"]["area_matches_input"] is False


@pytest.mark.parametrize("change", [{"unit_number": "502"}, {"building_dong": "102"}, {"building_token": "invalid"}])
def test_changed_or_forged_unit_evidence_never_saves(lookup, change):
    choice = chosen(lookup)
    result = building(lookup, choice, building_dong="101", unit_number="501").json()
    args = dict(building_token=result["building_token"], building_dong="101", unit_number="501") | change
    response = upload_address(lookup, choice, **args)
    assert not response.json()["committed"] and response.json()["errors"]
    assert lookup.get("/api/listings").json()["total"] == 0


def test_ambiguous_multiple_buildings_and_missing_unit_do_not_fill_area(lookup):
    configuration(other=True)
    choice = chosen(lookup)
    result = building(lookup, choice, unit_number="501").json()
    assert result["selected_building"] is None and result["status"] == "ambiguous"
    result = building(lookup, choice, building_id="building-main", building_dong="101", unit_number="999").json()
    assert result["unit"]["status"] == "not_found" and "exclusive_area_sqm" not in result["unit"]


def test_no_dong_ho_only_and_detached_without_unit_are_supported(lookup):
    configuration(dong="")
    choice = chosen(lookup)
    result = building(lookup, choice, unit_number="501", property_type="row_house").json()
    assert result["unit"]["status"] == "found" and result["unit"]["dong_name"] == ""
    result = building(lookup, choice, property_type="detached").json()
    assert result["unit"]["status"] == "not_requested"


def test_provider_failure_and_no_session_do_not_bypass_registration_or_auth(lookup):
    configuration(failed=True)
    choice = chosen(lookup)
    response = building(lookup, choice)
    assert response.status_code == 200 and response.json()["status"] == "unavailable"
    assert "secret-key-must-not-leak" not in response.text
    assert upload_address(lookup, choice).json()["committed"]
    lookup.cookies.clear()
    assert building(lookup, choice).status_code == 401
