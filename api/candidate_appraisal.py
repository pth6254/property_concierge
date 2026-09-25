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
    category, detail = PROPERTY_TYPES.get(candidate.get("category"), ("", ""))
    if not detail:
        missing.append("property_type")
    if missing:
        return {"missing_fields": missing, "case_id": case_id, "candidate_id": candidate_id,
                "input_url": f"/appraisal?caseId={case_id}&candidateId={candidate_id}"}
    query = f"{candidate['address']} {candidate['name']} {detail} {candidate['area_sqm']}㎡ 매매"

    return {"job_id": jobs.create_task("candidate_appraisal", {
                "query": query, "building_name": candidate["name"], "address": candidate["address"],
                "category": category, "detail": detail, "area_sqm": candidate["area_sqm"],
                "case_id": case_id, "candidate_id": candidate_id,
                "expected_candidate_inputs": {
                    "address": candidate["address"], "area_sqm": candidate["area_sqm"],
                    "category": candidate["category"], "asking_price": candidate["asking_price"],
                    "source_revision_id": (candidate.get("source_status") or {}).get("saved", {}).get("revision_id"),
                }}, owner_id=user_id),
            "case_id": case_id, "candidate_id": candidate_id, "candidate_name": candidate["name"]}
