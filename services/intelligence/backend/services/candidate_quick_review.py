"""후보 하나의 자금 계산과 시세추정을 사용자가 한 번에 요청한다.

새 계산 규칙을 만들지 않는다. 컨시어지와 같은 경로를 쓴다.
- 자금: 케이스 공통 조건(`profile_funding_inputs`) → Kotlin 계산·소유자 확인·저장(`execute_simulation`).
- 시세: 후보 저장 정보로 AVM 작업 접수(`start_candidate_appraisal`). 결과 연결은 기존 작업 실행기가 한다.
- 권리: 등기부 PDF가 필요해 실행하지 않고 상태만 알려준다.

되돌리면 안 되는 경계(AGENTS 2-11·2-12·2-14):
- 사용자가 버튼을 눌렀을 때만 실행한다. 조회(요약·비교)에서 이 함수를 부르지 않는다.
- 현재 유효한 분석은 다시 실행하지 않는다. 유효 여부는 다음 행동(candidate_next_actions.py)과 같은 기준이다:
  저장 상태가 completed이고, 자금은 분석 매수가가 현재 희망가와 같아야 한다. 희망가만 바꾸면 저장 상태는 completed로 남는다.
- 후보별로 저장한 개별 자금 조건을 공통 조건으로 덮어쓰지 않는다. 다시 계산할 때는 저장된 개별 조건 + 현재 희망가를 쓴다
  (화면의 재계산과 같은 입력). 저장 조건의 현금은 이미 비상자금을 뺀 값이므로 다시 빼지 않는다.
- 계산 기본값(대출 50%·금리 4% 등)으로 빈 조건을 채우지 않는다. 필요한 조건이 없으면 계산하지 않고 알려준다.
- 아파트의 면적 기준이 미확인이면 시세추정을 시작하지 않는다. 정책상 항상 보류되므로 시세추정 화면과 같이 먼저 입력을 요청한다.
- 선택·제외 상태를 바꾸지 않는다.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError

from api import case_db

SAVED_FUNDING_EXCLUDED = {"case_id", "candidate_id", "purchase_price", "property_type"}


def _saved_funding_inputs(analysis: dict | None) -> dict:
    from schemas.funding_request import SimulationRequest
    saved = ((analysis or {}).get("summary") or {}).get("inputs")
    if not isinstance(saved, dict):
        return {}
    fields = set(SimulationRequest.model_fields) - SAVED_FUNDING_EXCLUDED
    return {key: value for key, value in saved.items() if key in fields and value is not None}


def _funding(case: dict, candidate: dict, analysis: dict | None, user_id: int) -> dict:
    from schemas.funding_request import SimulationRequest
    from backend.services.candidate_funding import (funding_issues, funding_property_type,
                                                    missing_funding_inputs, profile_funding_inputs)
    from backend.services.funding_execution_client import execute_simulation

    if (analysis and analysis.get("status") == "completed"
            and (analysis.get("summary") or {}).get("purchase_price") == candidate.get("asking_price")):
        return {"status": "current"}
    saved = _saved_funding_inputs(analysis)
    try:
        profile_values = profile_funding_inputs(case.get("buyer_profile") or {})
    except ValidationError:
        # 공통 조건 형식이 잘못돼도 후보에 저장된 개별 조건만으로 계산할 수 있으면 막지 않는다.
        if not saved:
            return {"status": "needs_input", "missing": ["buyer_profile"], "input_source": "profile"}
        profile_values = {}
    values = {**profile_values, **saved}
    source = "saved" if saved else "profile"
    missing = missing_funding_inputs(values)
    if not isinstance(candidate.get("asking_price"), int) or candidate["asking_price"] <= 0:
        missing.append("asking_price")
    property_type = funding_property_type(candidate.get("category"))
    if property_type is None:
        missing.append("property_type")
    if missing:
        return {"status": "needs_input", "missing": missing, "input_source": source}
    try:
        request = SimulationRequest(case_id=case["id"], candidate_id=candidate["id"],
                                    purchase_price=candidate["asking_price"], property_type=property_type, **values)
    except ValidationError:
        return {"status": "error", "message": "저장된 자금 조건의 형식을 확인하지 못했습니다. 자금 분석 화면에서 다시 계산해주세요.",
                "input_source": source}
    try:
        result = execute_simulation(request, {"id": user_id})
    except HTTPException as error:
        return {"status": "error", "message": str(error.detail), "input_source": source}
    summary = result.get("candidate_funding") or {}
    return {"status": "calculated", "input_source": source,
            "summary": {key: summary.get(key) for key in ("purchase_price", "required_cash", "cash_shortfall", "monthly_payment")},
            "warnings": [title for _, title, _, _ in funding_issues(summary)]}


def _appraisal(case_id: int, candidate: dict, analysis: dict | None, user_id: int) -> dict:
    from api.candidate_appraisal import PROPERTY_TYPES, start_candidate_appraisal

    if analysis and analysis.get("status") == "completed":
        return {"status": "current"}
    if analysis and analysis.get("status") == "pending":
        return {"status": "current", "message": "진행 중인 시세 분석이 있어 새로 시작하지 않았습니다."}
    input_url = f"/appraisal?caseId={case_id}&candidateId={candidate['id']}"
    detail = PROPERTY_TYPES.get(candidate.get("category") or "", ("", ""))[1]
    if detail == "아파트" and (candidate.get("identity") or {}).get("area_basis") in (None, "", "unknown"):
        return {"status": "needs_input", "missing": ["area_basis"], "input_url": input_url}
    try:
        data = start_candidate_appraisal(user_id, case_id, candidate["id"])
    except ValueError as error:
        return {"status": "error", "message": str(error), "input_url": input_url}
    if data.get("missing_fields"):
        return {"status": "needs_input", "missing": data["missing_fields"], "input_url": data.get("input_url", input_url)}
    return {"status": "queued", "job_id": data["job_id"]}


def _rights(analysis: dict | None) -> dict:
    if not analysis:
        return {"status": "needs_document"}
    # 갱신 필요·실패·진행 중은 확인된 결과가 아니다. 판독 실패를 안전으로 보이지 않게 한다(AGENTS 2-11).
    return {"status": "current" if analysis.get("status") == "completed" else "stale"}


def run_quick_review(user_id: int, case_id: int, candidate_id: int) -> dict:
    case = case_db.get_case(case_id, user_id)
    candidate = next((item for item in (case or {}).get("properties", []) if item["id"] == candidate_id), None)
    if case is None or candidate is None:
        raise LookupError("candidate_not_found")
    if candidate.get("status") == "rejected":
        raise ValueError("제외한 후보입니다. 검토를 재개한 뒤 실행해주세요.")
    analyses = {item.get("analysis_type"): item for item in candidate.get("analyses") or []}
    # 자금은 즉시 끝나고, 시세추정은 작업으로 접수된다. 한쪽 실패가 다른 쪽 실행을 막지 않는다.
    funding = _funding(case, candidate, analyses.get("simulation"), user_id)
    appraisal = _appraisal(case_id, candidate, analyses.get("appraisal"), user_id)
    return {"case_id": case_id, "candidate_id": candidate_id, "funding": funding,
            "appraisal": appraisal, "rights": _rights(analyses.get("rights"))}
