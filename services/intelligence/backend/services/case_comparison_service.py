"""매수 케이스 후보를 저장된 사실만으로 비교한다.

점수 하나로 결론을 만들면 자료가 부족한 후보가 그럴듯하게 순위화될 수 있으므로,
가격·자금·권리·검토 완성도를 독립 축과 경고로 반환한다.
"""
from __future__ import annotations
from datetime import datetime

from backend.services.case_decision_assessment import assess_case_decision
from schemas.decision_assessment import CaseDecisionAssessment


def _analysis(candidate: dict, analysis_type: str) -> dict | None:
    return next((item for item in candidate.get("analyses", []) if item.get("analysis_type") == analysis_type), None)


def compare_case_candidates(case: dict, property_ids: list[int] | None = None, *,
                            now: datetime | None = None, assessment: CaseDecisionAssessment | None = None) -> dict:
    candidates = case.get("properties") or []
    if property_ids:
        selected = set(property_ids)
        candidates = [candidate for candidate in candidates if candidate["id"] in selected]

    # 요약과 비교가 서로 다른 자료를 검토 완료로 판단하지 않게 같은 계약을 사용한다.
    decision = assessment or assess_case_decision({**case, "properties": candidates}, now=now)
    assessed = {candidate.property_id: candidate for candidate in decision.candidates}
    rows = []
    for candidate in candidates:
        appraisal = _analysis(candidate, "appraisal")
        simulation = _analysis(candidate, "simulation")
        rights = _analysis(candidate, "rights")
        appraisal_summary = (appraisal or {}).get("summary") or {}
        simulation_summary = (simulation or {}).get("summary") or {}
        rights_summary = (rights or {}).get("summary") or {}
        asking = candidate.get("asking_price")
        estimated = appraisal_summary.get("estimated_value")
        confidence = appraisal_summary.get("confidence")
        candidate_decision = assessed[candidate["id"]]
        axis_status = {axis.key: axis.status for axis in candidate_decision.axes}
        gap = candidate_decision.metrics.price_gap
        gap_ratio = candidate_decision.metrics.price_gap_ratio

        missing = []
        warnings = []
        highlights = []
        if asking is None:
            missing.append("희망가 입력 필요")
        if not appraisal:
            missing.append("시세분석 필요")
        if not simulation:
            missing.append("자금 조건 입력 필요")
        if not rights:
            missing.append("권리서류 업로드 필요")
        for analysis, label in ((appraisal, "시세분석"), (simulation, "자금분석"), (rights, "권리분석")):
            if analysis and analysis.get("status") == "stale":
                missing.append(f"{label} 갱신 필요")
        if case.get("budget_max") and asking and asking > case["budget_max"]:
            warnings.append("최대 예산 초과")
        elif case.get("budget_max") and asking:
            highlights.append("예산 범위 이내")
        if gap_ratio is not None and gap_ratio > 5:
            warnings.append("희망가가 추정가보다 5% 초과")
        elif gap_ratio is not None and gap_ratio <= 0:
            highlights.append("희망가가 추정가 이하")
        if (appraisal or {}).get("status") == "completed" and (not isinstance(confidence, (int, float)) or confidence < 0.5):
            warnings.append("AVM 추정 신뢰도가 낮거나 미확인되어 가격 차이를 판단하지 않았습니다")
        rights_grade = rights_summary.get("risk_grade")
        if rights_grade in {"caution", "danger"}:
            warnings.append(f"권리 위험: {rights_summary.get('risk_label') or rights_grade}")
        elif rights_grade == "safe" and (rights or {}).get("status") == "completed" and rights_summary.get("registry_parsed") is True and rights_summary.get("building_parsed") is True:
            highlights.append("업로드 문서 내 위험 신호 미검출")
        elif rights_grade == "safe":
            missing.append("최신 권리 문서의 판독 여부 확인 필요")
        warning_checks = [item for item in candidate.get("checklist", []) if item.get("status") in {"warning", "blocked"}]
        warnings.extend(item["title"] for item in warning_checks)
        next_actions = [action.model_dump() for action in candidate_decision.next_actions]
        missing.extend(action["title"] for action in next_actions if action["priority"] != "warning")
        warnings.extend(action["title"] for action in next_actions if action["priority"] == "warning")

        # 단계는 작업의 안내만 나타낸다. 최종 선택 가능 여부와 혼동하지 않는다.
        if candidate.get("status") == "rejected":
            review_stage = "excluded"
        elif case.get("selected_property_id") == candidate["id"]:
            review_stage = "precontract"
        elif all((analysis or {}).get("status") == "completed" for analysis in (appraisal, simulation, rights)):
            review_stage = "detailed"
        elif asking is not None and len(case.get("properties") or []) >= 2:
            review_stage = "comparison"
        else:
            review_stage = "exploration"

        rows.append({
            "property_id": candidate["id"], "name": candidate["name"],
            "address": candidate.get("address") or "", "status": candidate.get("status"),
            "identity": candidate.get("identity"),
            "asking_price": asking, "area_sqm": candidate.get("area_sqm"),
            "estimated_value": estimated if gap is not None else None, "price_gap": gap, "price_gap_ratio": gap_ratio,
            "appraisal_confidence": confidence, "appraisal_match_level": appraisal_summary.get("match_level"),
            "appraisal_comparable_count": appraisal_summary.get("comparable_count"),
            "source_status": candidate.get("source_status"),
            "funding": simulation_summary if axis_status["funding"] in {"confirmed", "warning"} else None,
            "rights": rights_summary if axis_status["risk"] in {"confirmed", "warning"} else None,
            "analysis_status": {
                "appraisal": (appraisal or {}).get("status", "missing"),
                "simulation": (simulation or {}).get("status", "missing"),
                "rights": (rights or {}).get("status", "missing"),
            },
            "review_progress": candidate.get("review_progress", 0),
            "review_stage": review_stage,
            "missing": list(dict.fromkeys(missing)), "warnings": list(dict.fromkeys(warnings)),
            "highlights": list(dict.fromkeys(highlights)),
            "decision_ready": candidate_decision.review_ready,
        })

    return {
        "case_id": case["id"], "case_title": case["title"],
        "budget_min": case.get("budget_min"), "budget_max": case.get("budget_max"),
        "selected_property_id": case.get("selected_property_id"),
        "decision_reason": case.get("decision_reason") or "", "decided_at": case.get("decided_at"),
        "rows": rows,
    }
