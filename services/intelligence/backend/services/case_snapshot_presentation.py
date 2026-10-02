"""소유자 확인된 케이스 스냅샷의 표현·분석. 저장소에 접근하지 않는다."""
from __future__ import annotations
from typing import TYPE_CHECKING
from backend.services.analysis_freshness import analysis_freshness
from backend.services.candidate_next_actions import candidate_next_actions
if TYPE_CHECKING:
    from db.models import PurchaseCase, CaseProperty, HistoryRecord, CandidateAnalysis, CandidateChecklistItem, CaseRegion

def _appraisal_won(result: dict) -> int | None:
    analysis = result.get("analysis_result") or {}
    value = analysis.get("estimated_value")
    if value is None:
        value = result.get("estimated_value")
    if value is None:
        return None
    # 기존 입력·스키마는 원, 실제 AVM ValuationResult는 value_unit=만원이다.
    return round(value * 10_000) if analysis.get("value_unit", result.get("value_unit")) == "만원" else value

def _appraisal_evidence(result: dict) -> dict:
    analysis = result.get("analysis_result") or {}
    if "comparable_count" not in analysis:
        return {}
    from backend.confidence import compute_confidence

    count = analysis.get("comparable_count") or 0
    confidence = compute_confidence(count=count, samples=analysis.get("comparables") or None,
                                    used_months=analysis.get("used_months") or 0,
                                    source=analysis.get("source") or "")
    from services.price_analysis_service import _to_comparables
    samples = analysis.get("comparables") or []
    matched = samples[0].get("apt_name_matched", "") if samples else ""
    return {"confidence": confidence["score"], "confidence_basis": confidence["basis"],
            "match_level": confidence["match_level"], "comparable_count": count,
            "comparables": [item.model_dump(mode="json", exclude_none=True) for item in _to_comparables({"samples": samples}, matched)]}

def _case_dict(case: PurchaseCase, property_count: int = 0) -> dict:
    return {
        "id": case.id, "title": case.title, "status": case.status, "purpose": case.purpose,
        "budget_min": case.budget_min, "budget_max": case.budget_max,
        "buyer_profile": case.buyer_profile or {},
        "target_regions": case.target_regions or [], "notes": case.notes,
        "selected_property_id": case.selected_property_id,
        "decision_reason": case.decision_reason or "", "decided_at": case.decided_at,
        "created": case.created, "updated": case.updated, "property_count": property_count,
    }

def _property_dict(item: CaseProperty, history: HistoryRecord | None = None, analyses: list | None = None,
                   checklist: list | None = None, source_status: dict | None = None,
                   source_reviews: list | None = None) -> dict:
    appraisal = None
    if history:
        analysis = (history.result or {}).get("analysis_result") or {}
        appraisal = {
            "history_id": history.id, "query": history.query,
            "estimated_value": _appraisal_won(history.result or {}),
            "valuation_verdict": analysis.get("valuation_verdict") or history.result.get("valuation_verdict"),
            "created": history.created,
        }
    return {
        "id": item.id, "case_id": item.case_id, "name": item.name, "address": item.address,
        "alias": (item.source_snapshot or {}).get("alias", ""),
        "address_details": (item.source_snapshot or {}).get("address_details"),
        "identity": (item.source_snapshot or {}).get("identity"),
        "category": item.category, "asking_price": item.asking_price, "area_sqm": item.area_sqm,
        "legal_region_code": item.legal_region_code, "source": item.source, "status": item.status,
        "notes": item.notes, "history_id": item.history_id, "appraisal": appraisal,
        "source_listing_id": item.source_listing_id, "source_status": source_status,
        "source_reviews": source_reviews or [],
        "analyses": analyses or [], "checklist": checklist or [],
        "review_progress": round(sum(c["status"] == "done" for c in (checklist or [])) / len(checklist or []) * 100) if checklist else 0,
        "created": item.created, "updated": item.updated,
    }

def _analysis_dict(item: CandidateAnalysis) -> dict:
    freshness = analysis_freshness(
        item.analysis_type, item.analyzed_at, item.expires_at, item.status,
    )
    return {"id": item.id, "analysis_type": item.analysis_type, "reference_id": item.reference_id,
            "status": freshness["status"], "summary": item.summary or {}, "analyzed_at": item.analyzed_at,
            "expires_at": freshness["expires_at"], "days_remaining": freshness["days_remaining"],
            "updated": item.updated}

def _checklist_dict(item: CandidateChecklistItem) -> dict:
    return {"id": item.id, "category": item.category, "title": item.title, "status": item.status,
            "source": item.source, "evidence": item.evidence, "sort_order": item.sort_order,
            "completed_at": item.completed_at, "updated": item.updated}

def _region_dict(item: CaseRegion) -> dict:
    return {
        "id": item.id, "case_id": item.case_id,
        "region_code": item.region_code, "region_name": item.region_name,
        "source": item.source, "property_type": item.property_type,
        "budget_max_won": item.budget_max_won,
        "period_from": item.period_from, "period_to": item.period_to,
        "stats_snapshot": item.stats_snapshot or {}, "created": item.created,
    }
