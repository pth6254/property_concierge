"""동·호 정보 보존·소유권·광고 분리·입력 변경 후 재검토를 실제 Spring 계약으로 검증한다."""
import csv
import io
from datetime import datetime, timezone

from tests.test_listing_import import client, regions, row
from tests.test_purchase_cases import _register


def import_rows(client, values):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(values[0]))
    writer.writeheader(); writer.writerows(values)
    return client.post("/api/listings/import", json={"source_name": "호수 검증", "csv_text": output.getvalue(), "commit": True})


def test_same_address_units_are_preserved_without_merging(regions):
    values = [row(external_id="unit-1", building_dong="101", unit_number="501", area_basis="exclusive"),
              row(external_id="unit-2", building_dong="101", unit_number="502", area_basis="exclusive")]
    assert import_rows(regions, values).json()["created"] == 2
    saved = regions.get("/api/listings").json()["items"]
    assert {item["identity"]["unit_number"] for item in saved} == {"501", "502"}
    assert all(item["identity"]["unit_source"] == "user_input" for item in saved)
    case = regions.post("/api/cases", json={"title": "개별 호 비교"}).json()
    for item in saved:
        assert regions.post(f"/api/listings/{item['id']}/candidate", json={"case_id": case["id"]}).status_code == 201
    detail = regions.get(f"/api/cases/{case['id']}").json()
    assert len(detail["properties"]) == 2
    assert {item["identity"]["unit_number"] for item in detail["properties"]} == {"501", "502"}
    assert len(regions.get(f"/api/cases/{case['id']}/comparison").json()["rows"]) == 2
    assert all(item["identity"] for item in regions.get(f"/api/cases/{case['id']}/summary").json()["decision"]["candidates"])


def test_unit_revision_reopens_selected_candidate(regions):
    original = row(building_dong="101", unit_number="501", area_basis="exclusive")
    assert import_rows(regions, [original]).json()["created"] == 1
    listing = regions.get("/api/listings").json()["items"][0]
    case_id = regions.post("/api/cases", json={"title": "호수 변경"}).json()["id"]
    candidate_id = regions.post(f"/api/listings/{listing['id']}/candidate", json={"case_id": case_id}).json()["id"]
    assert regions.post(f"/api/cases/{case_id}/decision", json={"property_id": candidate_id, "reason": "사용자가 확인한 후보 선택"}).status_code == 200
    assert import_rows(regions, [{**original, "unit_number": "502", "confirmed_at": datetime.now(timezone.utc).isoformat()}]).json()["updated"] == 1
    current = regions.get(f"/api/cases/{case_id}").json()["properties"][0]["source_status"]
    assert current["status"] == "changed" and "identity" in current["changes"]
    result = regions.post(f"/api/cases/{case_id}/properties/{candidate_id}/source-update", json={
        "expected_revision_id": current["current"]["revision_id"], "expected_confirmed_at": current["current"]["confirmed_at"]}).json()
    assert result["decision_reopened"]
    case = regions.get(f"/api/cases/{case_id}").json()
    assert case["selected_property_id"] is None and case["properties"][0]["identity"]["unit_number"] == "502"


def test_manual_identity_change_invalidates_results_and_keeps_owner(client):
    owner = _register(client, "unit-owner@example.com")
    case_id = client.post("/api/cases", json={"title": "직접 후보"}).json()["id"]
    identity = {"building_dong": "101", "unit_number": "501", "floor": "5", "area_basis": "exclusive"}
    created = client.post(f"/api/cases/{case_id}/properties", json={"name": "같은 주소 후보", "identity": identity}).json()
    from api import case_db
    before = case_db.candidate_inputs(case_id, created["id"], owner)
    assert case_db.link_candidate_analysis(case_id, created["id"], owner, "rights", {"risk_grade": "safe"})
    assert client.patch(f"/api/cases/{case_id}/properties/{created['id']}", json={"identity": {**identity, "unit_number": "502"}}).status_code == 200
    detail = client.get(f"/api/cases/{case_id}").json()["properties"][0]
    assert detail["analyses"][0]["status"] == "stale"
    assert detail["source_reviews"][0]["previous_snapshot"]["identity"]["unit_number"] == "501"
    import pytest
    with pytest.raises(ValueError, match="후보 정보"):
        case_db.link_candidate_analysis(case_id, created["id"], owner, "rights", {"risk_grade": "safe"}, expected_inputs=before)
    client.cookies.clear(); _register(client, "unit-other@example.com")
    assert client.get(f"/api/cases/{case_id}").status_code == 404


def test_legacy_csv_remains_valid_and_missing_area_basis_is_unknown(regions):
    assert import_rows(regions, [row()]).json()["created"] == 1
    identity = regions.get("/api/listings").json()["items"][0]["identity"]
    assert identity["area_basis"] == "unknown" and identity["unit_source"] == "unknown"


def test_supply_area_cannot_be_silently_used_as_exclusive(client):
    _register(client, "supply-area@example.com")
    case_id = client.post("/api/cases", json={"title": "면적 기준 확인"}).json()["id"]
    candidate_id = client.post(f"/api/cases/{case_id}/properties", json={"name": "입력 후보", "address": "서울 강남구 역삼동 123",
        "area_sqm": 100, "category": "아파트", "identity": {"area_basis": "supply"}}).json()["id"]
    result = client.post("/api/appraisal/jobs", json={"user_input": "후보 시세 추정", "case_id": case_id, "candidate_id": candidate_id})
    assert result.status_code == 422
