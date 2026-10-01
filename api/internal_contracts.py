"""Spring에서 확인한 입력과 스냅샷을 받는 내부 분석 계약. 저장·권한 결정을 하지 않는다."""
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/internal/v1", tags=["internal-analysis"])


def require_service(x_internal_service_key: str | None = Header(default=None)):
    import hmac
    import os
    expected = os.getenv("INTERNAL_SERVICE_SECRET", "")
    if len(expected) < 32:
        raise HTTPException(503, "내부 분석 연결이 설정되지 않았습니다")
    if not x_internal_service_key or not hmac.compare_digest(expected, x_internal_service_key):
        raise HTTPException(401, "내부 서비스 인증이 필요합니다")


class RegionFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{10}$")
    full_name: str = Field(min_length=1, max_length=300)


class ImportValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(gt=0)
    source_name: str = Field(min_length=1, max_length=100)
    csv_text: str = Field(min_length=1, max_length=1_000_000)
    regions: list[RegionFact] = Field(max_length=100000)


@router.post("/listing-import/validate", dependencies=[Depends(require_service)])
def validate_listing_import(body: ImportValidation):
    from backend.services.listing_store import validate_csv
    regions = [SimpleNamespace(**region.model_dump()) for region in body.regions]
    output, rows = validate_csv(body.user_id, body.source_name, body.csv_text, regions)
    return {"validation": output, "rows": [
        {"row": index, "payload": item.model_dump(mode="json") | ({"address_details": details} if details else {}),
         "confirmed_at": item.confirmed_at.timestamp(),
         "price": item.asking_price if item.transaction_type == "purchase" else item.deposit}
        for index, item, details in rows]}


class CaseSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case: dict
    property_ids: list[int] | None = Field(default=None, max_length=4)


@router.post("/decision/assess", dependencies=[Depends(require_service)])
def assess_snapshot(body: CaseSnapshot):
    from backend.services.case_decision_assessment import assess_case_decision
    from backend.services.case_comparison_service import compare_case_candidates
    assessment = assess_case_decision(body.case)
    return {"comparison": compare_case_candidates(body.case, body.property_ids, assessment=assessment),
            "decision": assessment.model_dump(mode="json")}


class StoredSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: dict


@router.post("/decision/decorate", dependencies=[Depends(require_service)])
def decorate_snapshot(body: StoredSnapshot):
    from backend.services.case_snapshot_presentation import (
        _analysis_dict, _appraisal_evidence, _appraisal_won, _case_dict,
        _checklist_dict, _property_dict, _region_dict,
    )
    from backend.services.candidate_next_actions import candidate_next_actions

    # 이 경로에는 저장소 호출을 두지 않는다. 소유자가 확인된 동일 스냅샷만 분석한다.
    snapshot = body.snapshot
    histories = {int(key): SimpleNamespace(**value) for key, value in snapshot["histories"].items()}
    result = _case_dict(SimpleNamespace(**snapshot["case"]), len(snapshot["properties"]))
    properties, all_checks = [], []
    review_fields = ("id", "created", "previous_snapshot", "applied_snapshot", "previous_decision",
                     "invalidated_analyses", "previous_analyses", "previous_execution")
    for stored in snapshot["properties"]:
        item = SimpleNamespace(**stored["property"])
        analyses = []
        for raw in stored["analyses"]:
            analysis = _analysis_dict(SimpleNamespace(**raw))
            history = histories.get(raw["reference_id"])
            if raw["analysis_type"] == "appraisal" and history:
                analysis["summary"]["estimated_value"] = _appraisal_won(history.result or {})
                analysis["summary"].update(_appraisal_evidence(history.result or {}))
            analyses.append(analysis)
        checks = [_checklist_dict(SimpleNamespace(**check)) for check in stored["checklist"]]
        all_checks.extend(checks)
        reviews = [{field: review.get(field) for field in review_fields} for review in stored["source_reviews"]]
        properties.append(_property_dict(item, histories.get(item.history_id), analyses, checks,
                                         stored["source_status"], reviews))
    result["properties"] = properties
    result["regions"] = [_region_dict(SimpleNamespace(**region)) for region in snapshot["regions"]]
    for candidate in properties:
        candidate["next_actions"] = candidate_next_actions(result, candidate)
    done = sum(check["status"] == "done" for check in all_checks)
    result["workspace"] = {
        "checklist_total": len(all_checks), "checklist_done": done,
        "warning_count": sum(check["status"] == "warning" for check in all_checks),
        "blocked_count": sum(check["status"] == "blocked" for check in all_checks),
        "progress_percent": round(done / len(all_checks) * 100) if all_checks else 0,
    }
    return result


class AppraisalSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    history_id: int = Field(gt=0)
    result: dict


@router.post("/appraisal/summary", dependencies=[Depends(require_service)])
def summarize_appraisal(body: AppraisalSnapshot):
    from backend.services.case_snapshot_presentation import _appraisal_evidence, _appraisal_won
    analysis = body.result.get("analysis_result") or {}
    return {"history_id": body.history_id, "estimated_value": _appraisal_won(body.result),
            "valuation_verdict": analysis.get("valuation_verdict") or body.result.get("valuation_verdict"),
            **_appraisal_evidence(body.result)}


from schemas.simulation import SimulationInput, SimulationResult


class SimulationPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: SimulationInput
    result: SimulationResult


@router.post("/simulation/report", dependencies=[Depends(require_service)])
def render_simulation_report(body: SimulationPresentation):
    from schemas.report import SimulationReport
    from backend.services.simulation_service import generate_simulation_report
    markdown = generate_simulation_report(body.result, body.input)
    return {"report": markdown, "report_output": SimulationReport(result=body.result, input=body.input, markdown=markdown)}
