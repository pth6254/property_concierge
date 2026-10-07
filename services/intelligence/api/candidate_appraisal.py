"""후보의 저장된 입력으로 AVM 작업을 생성한다."""
from __future__ import annotations

from api import case_db, history_db, jobs


PROPERTY_TYPES = {
    "apartment": ("주거용", "아파트"), "아파트": ("주거용", "아파트"),
    "officetel": ("주거용", "오피스텔"), "오피스텔": ("주거용", "오피스텔"),
    "row_house": ("주거용", "연립다세대"), "연립다세대": ("주거용", "연립다세대"),
    "detached": ("주거용", "단독다가구"), "단독다가구": ("주거용", "단독다가구"),
    "land": ("토지", "토지"), "토지": ("토지", "토지"),
    "상가": ("상업용", "상가"), "사무실": ("업무용", "사무실"),
    "공장": ("산업용", "공장"), "창고": ("산업용", "창고"),
}


def start_candidate_appraisal(user_id: int, case_id: int, candidate_id: int) -> dict:
    case = case_db.get_case(case_id, user_id)
    candidate = next((c for c in (case or {}).get("properties", []) if c["id"] == candidate_id), None)
    if candidate is None:
        raise LookupError("candidate_not_found")
    missing = [key for key in ("address", "area_sqm") if not candidate.get(key)]
    if (candidate.get("identity") or {}).get("area_basis") == "supply":
        missing.append("exclusive_area_sqm")
    category, detail = PROPERTY_TYPES.get(candidate.get("category"), ("", ""))
    if not detail:
        missing.append("property_type")
    if category in {"상업용", "업무용"}:
        missing.append("income_valuation")
    if missing:
        return {"missing_fields": missing, "case_id": case_id, "candidate_id": candidate_id,
                "input_url": f"/appraisal?caseId={case_id}&candidateId={candidate_id}"}
    query = f"{candidate['address']} {candidate['name']} {detail} {candidate['area_sqm']}㎡ 매매"
    expected = case_db.candidate_inputs(case_id, candidate_id, user_id)
    if not expected or any(expected.get(key) != candidate.get(key) for key in ("address", "area_sqm", "category", "asking_price")):
        raise ValueError("후보 정보가 변경되었습니다. 다시 확인해주세요.")

    return {"job_id": jobs.create_task("candidate_appraisal", {
                "query": query, "building_name": candidate["name"], "address": candidate["address"],
                "category": category, "detail": detail, "area_sqm": candidate["area_sqm"],
                "valuation_context": {"scope": "single_parcel" if category == "토지" else "single_unit",
                    "area_basis": (candidate.get("identity") or {}).get("area_basis") or "unknown", "transaction_type": "sale",
                    "dong": (candidate.get("identity") or {}).get("building_dong") or "", "ho": (candidate.get("identity") or {}).get("unit_number") or ""},
                "case_id": case_id, "candidate_id": candidate_id,
                "expected_candidate_inputs": expected}, owner_id=user_id),
            "case_id": case_id, "candidate_id": candidate_id, "candidate_name": candidate["name"]}
