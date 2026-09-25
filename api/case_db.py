"""매수 검토 케이스 저장소. 모든 공개 함수는 user_id로 소유자를 제한한다."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import delete, func, select

from db.base import session_scope
from db.models import (
    CandidateAnalysis, CandidateChecklistItem, CandidateSourceReview, CaseExecutionPlan,
    CaseExecutionTask, CaseProperty, CaseRegion,
    HistoryRecord, ImportedListing, LegalRegion, ListingRevision, PurchaseCase,
)
from db.models import _now_str
from backend.services.analysis_freshness import analysis_freshness, expiry_for
from backend.services.candidate_next_actions import candidate_next_actions


def _candidate_version() -> str:
    # 같은 초에 가격이 바뀌어도 진행 중인 AVM의 입력 버전이 달라야 한다.
    return datetime.now().isoformat(sep=" ", timespec="microseconds")


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
    return {"confidence": confidence["score"], "confidence_basis": confidence["basis"],
            "match_level": confidence["match_level"], "comparable_count": count}


def _source_status(item: CaseProperty, listing: ImportedListing | None, session) -> dict | None:
    snapshot = item.source_snapshot
    if not snapshot:
        return None
    if listing is None:
        return {"status": "missing", "listing_id": snapshot["listing_id"], "changes": {},
                "needs_confirmation": True, "saved": snapshot, "current": None}
    from backend.services.listing_store import _view

    current = _view(listing, session)
    revision_id = session.scalar(select(ListingRevision.id).where(
        ListingRevision.listing_id == listing.id).order_by(ListingRevision.id.desc()).limit(1))
    fields = ("name", "asking_price", "address", "area_sqm", "status", "legal_region_code", "property_type")
    changes = {field: {"saved": snapshot.get(field), "current": current.get(field)}
               for field in fields if snapshot.get(field) != current.get(field)}
    needs_confirmation = current["needs_confirmation"] or current["status"] != "active"
    return {"status": "changed" if changes else "needs_confirmation" if needs_confirmation else "current",
            "listing_id": listing.id, "changes": changes, "needs_confirmation": needs_confirmation,
            "saved": snapshot, "current": {field: current.get(field) for field in fields} |
            {"revision_id": revision_id, "confirmed_at": current.get("confirmed_at"),
             "last_collection_outcome": current.get("last_collection_outcome")}}


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


def create_case(user_id: int, data: dict) -> dict:
    with session_scope() as session:
        if hasattr(data.get("buyer_profile"), "model_dump"):
            data["buyer_profile"] = data["buyer_profile"].model_dump(mode="json")
        case = PurchaseCase(user_id=user_id, **data)
        session.add(case)
        session.flush()
        return _case_dict(case)


def list_cases(user_id: int) -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(PurchaseCase, func.count(CaseProperty.id))
            .outerjoin(CaseProperty, CaseProperty.case_id == PurchaseCase.id)
            .where(PurchaseCase.user_id == user_id)
            .group_by(PurchaseCase.id)
            .order_by(PurchaseCase.updated.desc(), PurchaseCase.id.desc())
        ).all()
        return [_case_dict(case, count) for case, count in rows]


def get_case(case_id: int, user_id: int) -> dict | None:
    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(PurchaseCase.id == case_id, PurchaseCase.user_id == user_id))
        if not case:
            return None
        properties = session.scalars(
            select(CaseProperty).where(CaseProperty.case_id == case.id).order_by(CaseProperty.created, CaseProperty.id)
        ).all()
        regions = session.scalars(
            select(CaseRegion).where(CaseRegion.case_id == case.id).order_by(CaseRegion.created, CaseRegion.id)
        ).all()
        history_ids = [item.history_id for item in properties if item.history_id]
        histories = {}
        if history_ids:
            histories = {row.id: row for row in session.scalars(
                select(HistoryRecord).where(HistoryRecord.id.in_(history_ids), HistoryRecord.user_id == user_id)
            )}
        property_ids = [item.id for item in properties]
        listing_ids = {item.source_listing_id for item in properties if item.source_listing_id}
        source_listings = {row.id: row for row in session.scalars(select(ImportedListing).where(
            ImportedListing.id.in_(listing_ids), ImportedListing.user_id == user_id))} if listing_ids else {}
        analyses_by_property: dict[int, list] = {item.id: [] for item in properties}
        checklist_by_property: dict[int, list] = {item.id: [] for item in properties}
        if property_ids:
            source_reviews = {item.id: [] for item in properties}
            for review in session.scalars(select(CandidateSourceReview).where(
                CandidateSourceReview.property_id.in_(property_ids), CandidateSourceReview.user_id == user_id
            ).order_by(CandidateSourceReview.id.desc())):
                source_reviews[review.property_id].append({
                    "id": review.id, "created": review.created, "previous_snapshot": review.previous_snapshot,
                    "applied_snapshot": review.applied_snapshot, "previous_decision": review.previous_decision,
                    "invalidated_analyses": review.invalidated_analyses,
                    "previous_analyses": review.previous_analyses,
                    "previous_execution": review.previous_execution,
                })
            for row in session.scalars(select(CandidateAnalysis).where(CandidateAnalysis.property_id.in_(property_ids))):
                serialized = _analysis_dict(row)
                history = histories.get(row.reference_id)
                if row.analysis_type == "appraisal" and history:
                    # 이전에 연결된 기록도 원본 이력의 단위로 읽어 비교값을 바로잡는다.
                    serialized["summary"]["estimated_value"] = _appraisal_won(history.result or {})
                    serialized["summary"].update(_appraisal_evidence(history.result or {}))
                analyses_by_property[row.property_id].append(serialized)
            for row in session.scalars(select(CandidateChecklistItem).where(
                CandidateChecklistItem.property_id.in_(property_ids)
            ).order_by(CandidateChecklistItem.sort_order, CandidateChecklistItem.id)):
                checklist_by_property[row.property_id].append(_checklist_dict(row))
        result = _case_dict(case, len(properties))
        result["properties"] = [
            _property_dict(item, histories.get(item.history_id), analyses_by_property[item.id], checklist_by_property[item.id],
                           _source_status(item, source_listings.get(item.source_listing_id), session),
                           source_reviews.get(item.id, []) if property_ids else [])
            for item in properties
        ]
        result["regions"] = [_region_dict(item) for item in regions]
        for candidate in result["properties"]:
            candidate["next_actions"] = candidate_next_actions(result, candidate)
        all_checks = [check for checks in checklist_by_property.values() for check in checks]
        done = sum(check["status"] == "done" for check in all_checks)
        result["workspace"] = {
            "checklist_total": len(all_checks), "checklist_done": done,
            "warning_count": sum(check["status"] == "warning" for check in all_checks),
            "blocked_count": sum(check["status"] == "blocked" for check in all_checks),
            "progress_percent": round(done / len(all_checks) * 100) if all_checks else 0,
        }
        return result


def update_case(case_id: int, user_id: int, data: dict) -> dict | None:
    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(PurchaseCase.id == case_id, PurchaseCase.user_id == user_id))
        if not case:
            return None
        for key, value in data.items():
            if key == "buyer_profile" and hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")
            setattr(case, key, value)
        case.updated = _now_str()
        session.flush()
        return _case_dict(case, session.scalar(select(func.count()).select_from(CaseProperty).where(CaseProperty.case_id == case.id)) or 0)


def delete_case(case_id: int, user_id: int) -> bool:
    with session_scope() as session:
        result = session.execute(delete(PurchaseCase).where(PurchaseCase.id == case_id, PurchaseCase.user_id == user_id))
        return bool(result.rowcount)


def add_property(case_id: int, user_id: int, data: dict) -> dict | None:
    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(PurchaseCase.id == case_id, PurchaseCase.user_id == user_id))
        if not case:
            return None
        if data.get("status") == "selected":
            raise ValueError("후보를 추가한 뒤 선택 근거와 함께 최종 선택해주세요")
        source_listing_id = data.pop("source_listing_id", None)
        if source_listing_id is not None:
            from backend.services.listing_store import _view

            listing = session.scalar(select(ImportedListing).where(
                ImportedListing.id == source_listing_id, ImportedListing.user_id == user_id).with_for_update())
            if listing is None:
                raise LookupError("listing_not_found")
            source = _view(listing, session)
            if source["status"] != "active" or source["needs_confirmation"] or not source["region_linked"]:
                raise ValueError("법정동 연결 및 최근 7일 이내의 거래 가능 상태를 확인한 뒤 저장해주세요")
            if source["transaction_type"] != "purchase":
                raise ValueError("현재 매수 검토 케이스에는 매매 매물만 저장할 수 있습니다")
            existing = session.scalar(select(CaseProperty).where(
                CaseProperty.case_id == case_id, CaseProperty.source_listing_id == listing.id))
            if existing:
                return {**_property_dict(existing, source_status=_source_status(existing, listing, session)),
                        "_already_linked": True}
            revision_id = session.scalar(select(ListingRevision.id).where(
                ListingRevision.listing_id == listing.id).order_by(ListingRevision.id.desc()).limit(1))
            snapshot = {field: source.get(field) for field in (
                "name", "asking_price", "address", "area_sqm", "status", "legal_region_code", "property_type", "confirmed_at")}
            snapshot.update(listing_id=listing.id, revision_id=revision_id)
            data = {"name": source["name"], "address": source["address"], "category": source["property_type"],
                    "asking_price": source["asking_price"], "area_sqm": source["area_sqm"],
                    "legal_region_code": source["legal_region_code"], "source": "manual",
                    "notes": f"제공 매물 #{listing.id} · 출처 {source['source_name']} / {source['external_id']} · 확인 {source['confirmed_at']}\n"
                             f"원문 {source.get('source_url') or '없음'} · 마지막 수집 시도 {source.get('last_collection_at')}\n"
                             "사용자 제공 정보이며 현재 매물 존재·희망가를 서비스가 독립 확인한 것은 아닙니다.",
                    "source_listing_id": listing.id, "source_snapshot": snapshot}
        history = None
        history_id = data.get("history_id")
        if history_id:
            history = session.scalar(select(HistoryRecord).where(HistoryRecord.id == history_id, HistoryRecord.user_id == user_id))
            if not history:
                raise LookupError("history_not_found")
        item = CaseProperty(case_id=case.id, **data)
        session.add(item)
        session.flush()
        for order, (category, title) in enumerate([
            ("price", "적정가격 확인"), ("funding", "자금 조건 입력 필요"),
            ("rights", "권리서류 업로드 필요"), ("site", "현장 상태 확인"),
            ("contract", "계약 조건 확인"),
        ]):
            linked_appraisal = bool(history and category == "price")
            session.add(CandidateChecklistItem(
                case_id=case.id, property_id=item.id, category=category,
                title=title, sort_order=order, status="done" if linked_appraisal else "todo",
                source="appraisal" if linked_appraisal else "system",
                evidence=f"시세추정 이력 #{history.id} 연결" if linked_appraisal else "",
                completed_at=_now_str() if linked_appraisal else None,
            ))
        if history:
            analysis_result = (history.result or {}).get("analysis_result") or {}
            session.add(CandidateAnalysis(
                case_id=case.id, property_id=item.id, analysis_type="appraisal",
                reference_id=history.id, analyzed_at=history.created,
                expires_at=expiry_for("appraisal", history.created),
                summary={
                    "history_id": history.id,
                    "estimated_value": _appraisal_won(history.result or {}),
                    "valuation_verdict": analysis_result.get("valuation_verdict") or history.result.get("valuation_verdict"),
                    **_appraisal_evidence(history.result or {}),
                },
            ))
        case.updated = _now_str()
        session.flush()
        checks = session.scalars(select(CandidateChecklistItem).where(CandidateChecklistItem.property_id == item.id).order_by(CandidateChecklistItem.sort_order)).all()
        analyses = session.scalars(select(CandidateAnalysis).where(CandidateAnalysis.property_id == item.id)).all()
        return _property_dict(item, history, [_analysis_dict(value) for value in analyses], [_checklist_dict(check) for check in checks],
                              _source_status(item, listing, session) if source_listing_id is not None else None)


def update_property(case_id: int, property_id: int, user_id: int, data: dict) -> dict | None:
    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(PurchaseCase.id == case_id, PurchaseCase.user_id == user_id))
        if not case:
            return None
        item = session.scalar(select(CaseProperty).where(CaseProperty.id == property_id, CaseProperty.case_id == case.id))
        if not item:
            return None
        if data.get("status") == "selected" and case.selected_property_id != item.id:
            raise ValueError("최종 선택은 후보 검토 화면에서 선택 근거와 함께 저장해주세요")
        if case.selected_property_id == item.id and data.get("status", "selected") != "selected":
            raise ValueError("최종 선택된 후보입니다. 후보 검토 화면에서 다른 후보를 선택해주세요")
        for key, value in data.items():
            setattr(item, key, value)
        item.updated = _candidate_version()
        case.updated = _now_str()
        session.flush()
        return _property_dict(item)


def apply_listing_update(case_id: int, property_id: int, user_id: int,
                         expected_revision_id: int, expected_confirmed_at: str) -> dict | None:
    """확인한 원본 버전만 후보에 반영하고 영향받는 판단을 재검토 상태로 돌린다."""
    from backend.services.listing_store import _view

    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(
            PurchaseCase.id == case_id, PurchaseCase.user_id == user_id).with_for_update())
        if case is None:
            return None
        item = session.scalar(select(CaseProperty).where(
            CaseProperty.id == property_id, CaseProperty.case_id == case_id).with_for_update())
        if item is None or item.source_listing_id is None or not item.source_snapshot:
            return None
        listing = session.scalar(select(ImportedListing).where(
            ImportedListing.id == item.source_listing_id, ImportedListing.user_id == user_id).with_for_update())
        if listing is None:
            raise ValueError("원본 매물을 찾을 수 없습니다. 후보를 직접 다시 확인해주세요")
        source = _view(listing, session)
        revision_id = session.scalar(select(ListingRevision.id).where(
            ListingRevision.listing_id == listing.id).order_by(ListingRevision.id.desc()).limit(1))
        if revision_id != expected_revision_id or source["confirmed_at"] != expected_confirmed_at:
            raise ValueError("원본 매물이 다시 바뀌었습니다. 새 내용을 확인한 뒤 반영해주세요")
        if source["status"] != "active" or source["needs_confirmation"] or not source["region_linked"]:
            raise ValueError("거래 가능 상태와 최근 7일 이내 확인 시각을 먼저 확인해주세요")
        if source["transaction_type"] != "purchase":
            raise ValueError("매매 매물만 매수 후보에 반영할 수 있습니다")

        before = dict(item.source_snapshot)
        after = {field: source.get(field) for field in (
            "name", "asking_price", "address", "area_sqm", "status", "legal_region_code",
            "property_type", "confirmed_at")}
        after.update(listing_id=listing.id, revision_id=revision_id)
        changed = {field for field in ("name", "asking_price", "address", "area_sqm",
                                        "legal_region_code", "property_type", "status")
                   if before.get(field) != after.get(field)}
        if not changed and before.get("confirmed_at") == after["confirmed_at"]:
            return {"changed": False, "invalidated_analyses": [], "decision_reopened": False}

        analyses = session.scalars(select(CandidateAnalysis).where(
            CandidateAnalysis.property_id == property_id).with_for_update()).all()
        checks = session.scalars(select(CandidateChecklistItem).where(
            CandidateChecklistItem.property_id == property_id).with_for_update()).all()
        previous_analyses = [{"type": row.analysis_type, "status": row.status, "summary": row.summary,
                              "analyzed_at": row.analyzed_at, "reference_id": row.reference_id} for row in analyses]
        # 이름·확인 시각만 달라졌다면 수치 분석을 무효화하지 않는다.
        invalidate = ({"appraisal", "simulation", "rights"} if changed - {"name"} else set())
        now = _now_str()
        for row in analyses:
            if row.analysis_type in invalidate:
                row.status = "stale"
                row.updated = now
        for check in checks:
            if check.category in {"price": "appraisal", "funding": "simulation", "rights": "rights"}:
                if {"price": "appraisal", "funding": "simulation", "rights": "rights"}[check.category] in invalidate:
                    check.status, check.completed_at, check.updated = "todo", None, now
                    check.evidence = "원본 매물 변경 후 다시 확인 필요"

        selected = case.selected_property_id == item.id
        previous_decision = ({"property_id": item.id, "reason": case.decision_reason,
                              "decided_at": case.decided_at} if selected else None)
        previous_execution = []
        if selected and invalidate:
            plan = session.scalar(select(CaseExecutionPlan).where(CaseExecutionPlan.case_id == case.id))
            if plan:
                tasks = session.scalars(select(CaseExecutionTask).where(CaseExecutionTask.plan_id == plan.id)).all()
                previous_execution = [{"id": task.id, "title": task.title, "status": task.status,
                                       "checked_by": task.checked_by, "outcome": task.outcome,
                                       "evidence_note": task.evidence_note} for task in tasks]
                plan.contract_planned_date = plan.closing_planned_date = None
                plan.updated = now
                for task in tasks:
                    task.status, task.completed_at, task.due_date = "scheduled", None, None
                    task.checked_by = task.outcome = task.follow_up = ""
                    task.evidence_note = "원본 매물 변경 전 확인 기록은 변경 이력에 보관됨"
                    task.updated = now
            case.selected_property_id, case.decided_at, case.decision_reason = None, None, ""
            case.status = "reviewing"
            item.status = "shortlisted"

        session.add(CandidateSourceReview(case_id=case.id, property_id=item.id, user_id=user_id,
            previous_snapshot=before, applied_snapshot=after, previous_decision=previous_decision,
            invalidated_analyses=sorted(invalidate), previous_analyses=previous_analyses,
            previous_execution=previous_execution, created=now))
        item.name, item.asking_price, item.address, item.area_sqm = (
            source["name"], source["asking_price"], source["address"], source["area_sqm"])
        item.category, item.legal_region_code, item.source_snapshot = (
            source["property_type"], source["legal_region_code"], after)
        item.updated = _candidate_version()
        case.updated = now
        return {"changed": bool(changed), "invalidated_analyses": sorted(invalidate),
                "decision_reopened": bool(selected and invalidate)}


def select_final_candidate(case_id: int, property_id: int, user_id: int, reason: str) -> dict | None:
    """최종 후보와 선택 근거를 같은 트랜잭션에서 저장한다."""
    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(
            PurchaseCase.id == case_id, PurchaseCase.user_id == user_id,
        ).with_for_update())
        if not case:
            return None
        selected = session.scalar(select(CaseProperty).where(
            CaseProperty.id == property_id, CaseProperty.case_id == case.id,
        ))
        if not selected:
            return None
        if selected.source_listing_id:
            source = session.scalar(select(ImportedListing).where(
                ImportedListing.id == selected.source_listing_id, ImportedListing.user_id == user_id))
            status = _source_status(selected, source, session)
            if status and status["status"] != "current":
                raise ValueError("원본 매물 변경 또는 확인 만료를 먼저 검토해주세요")
            stale = session.scalar(select(CandidateAnalysis.id).where(
                CandidateAnalysis.property_id == selected.id, CandidateAnalysis.status == "stale").limit(1))
            if stale:
                raise ValueError("원본 매물 변경으로 무효화된 분석을 다시 확인해주세요")
        now = _now_str()
        properties = session.scalars(select(CaseProperty).where(CaseProperty.case_id == case.id)).all()
        for item in properties:
            if item.id == selected.id:
                item.status = "selected"
            elif item.status == "selected":
                item.status = "shortlisted"
            item.updated = now
        case.selected_property_id = selected.id
        case.decision_reason = reason
        case.decided_at = now
        case.status = "decided"
        case.updated = now
        session.flush()
        # 선택과 실행 계획이 따로 커밋되면 중간 실패 후 다른 후보의 작업이 노출된다.
        from api.case_execution_db import sync_execution_plan
        sync_execution_plan(session, case)
        return _case_dict(case, len(properties))


def clear_final_candidate(case_id: int, user_id: int) -> dict | None:
    """판단을 재검토할 수 있게 선택을 해제하되 기존 실행 기록은 보존한다."""
    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(
            PurchaseCase.id == case_id, PurchaseCase.user_id == user_id,
        ).with_for_update())
        if not case:
            return None
        for candidate in session.scalars(select(CaseProperty).where(
            CaseProperty.case_id == case.id, CaseProperty.status == "selected",
        )):
            candidate.status = "shortlisted"
            candidate.updated = _now_str()
        case.selected_property_id = case.decided_at = None
        case.decision_reason = ""
        case.status = "reviewing"
        case.updated = _now_str()
        session.flush()
        return _case_dict(case)


def update_checklist(case_id: int, property_id: int, checklist_id: int, user_id: int, data: dict) -> dict | None:
    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(PurchaseCase.id == case_id, PurchaseCase.user_id == user_id))
        if not case:
            return None
        check = session.scalar(select(CandidateChecklistItem).where(
            CandidateChecklistItem.id == checklist_id,
            CandidateChecklistItem.property_id == property_id,
            CandidateChecklistItem.case_id == case.id,
        ))
        if not check:
            return None
        check.status = data["status"]
        if data.get("evidence") is not None:
            check.evidence = data["evidence"]
        check.completed_at = _now_str() if check.status == "done" else None
        check.updated = case.updated = _now_str()
        session.flush()
        return _checklist_dict(check)


def validate_candidate(case_id: int, property_id: int, user_id: int) -> bool:
    with session_scope() as session:
        return session.scalar(select(CaseProperty.id).join(
            PurchaseCase, PurchaseCase.id == CaseProperty.case_id
        ).where(
            PurchaseCase.id == case_id, PurchaseCase.user_id == user_id,
            CaseProperty.id == property_id, CaseProperty.case_id == case_id,
        )) is not None


def candidate_inputs(case_id: int, property_id: int, user_id: int) -> dict | None:
    with session_scope() as session:
        item = session.scalar(select(CaseProperty).join(
            PurchaseCase, PurchaseCase.id == CaseProperty.case_id
        ).where(PurchaseCase.id == case_id, PurchaseCase.user_id == user_id,
                CaseProperty.id == property_id, CaseProperty.case_id == case_id))
        return _candidate_inputs(item) if item else None


def _candidate_inputs(item: CaseProperty) -> dict:
    return {"address": item.address, "area_sqm": item.area_sqm, "category": item.category,
            "asking_price": item.asking_price,
            "source_revision_id": (item.source_snapshot or {}).get("revision_id")}


def link_appraisal(case_id: int, property_id: int, history_id: int, user_id: int, result: dict,
                   expected_inputs: dict | None = None) -> bool:
    """분석 완료 시 후보·분석·가격 체크 항목을 하나의 트랜잭션으로 갱신한다."""
    with session_scope() as session:
        item = session.scalar(select(CaseProperty).join(
            PurchaseCase, PurchaseCase.id == CaseProperty.case_id
        ).where(
            PurchaseCase.id == case_id, PurchaseCase.user_id == user_id,
            CaseProperty.id == property_id, CaseProperty.case_id == case_id,
        ))
        if not item:
            return False
        if expected_inputs is not None and _candidate_inputs(item) != expected_inputs:
            # 재실행 결과가 이미 연결된 경우만 허용한다. 입력 변경 전 결과는 버린다.
            if item.history_id == history_id:
                return True
            raise ValueError("분석 중 후보 정보가 바뀌었습니다. 최신 정보로 다시 실행해주세요")
        now = _now_str()
        analysis_result = result.get("analysis_result") or {}
        estimated = _appraisal_won(result)
        verdict = analysis_result.get("valuation_verdict") or result.get("valuation_verdict")
        summary = {"history_id": history_id, "estimated_value": estimated, "valuation_verdict": verdict,
                   **_appraisal_evidence(result)}
        analysis = session.scalar(select(CandidateAnalysis).where(
            CandidateAnalysis.property_id == property_id, CandidateAnalysis.analysis_type == "appraisal"
        ))
        if analysis:
            analysis.reference_id, analysis.status, analysis.summary = history_id, "completed", summary
            analysis.analyzed_at = analysis.updated = now
            analysis.expires_at = expiry_for("appraisal", now)
        else:
            session.add(CandidateAnalysis(case_id=case_id, property_id=property_id, analysis_type="appraisal", reference_id=history_id, summary=summary, analyzed_at=now, expires_at=expiry_for("appraisal", now)))
        item.history_id, item.updated = history_id, _candidate_version()
        check = session.scalar(select(CandidateChecklistItem).where(
            CandidateChecklistItem.property_id == property_id, CandidateChecklistItem.category == "price"
        ))
        if check:
            check.status = "done"
            check.evidence = f"시세추정 이력 #{history_id} 연결"
            check.completed_at = check.updated = now
        case = session.get(PurchaseCase, case_id)
        case.updated = now
        return True


def link_candidate_analysis(case_id: int, property_id: int, user_id: int, analysis_type: str,
                            summary: dict, checklist_status: str = "done", evidence: str = "") -> bool:
    """실제로 완료된 계산·문서 분석만 후보에 연결한다."""
    category = {"simulation": "funding", "rights": "rights"}.get(analysis_type)
    if not category:
        raise ValueError("지원하지 않는 후보 분석 유형")
    with session_scope() as session:
        item = session.scalar(select(CaseProperty).join(
            PurchaseCase, PurchaseCase.id == CaseProperty.case_id
        ).where(
            PurchaseCase.id == case_id, PurchaseCase.user_id == user_id,
            CaseProperty.id == property_id, CaseProperty.case_id == case_id,
        ))
        if not item:
            return False
        now = _now_str()
        analysis = session.scalar(select(CandidateAnalysis).where(
            CandidateAnalysis.property_id == property_id, CandidateAnalysis.analysis_type == analysis_type,
        ))
        if analysis:
            analysis.status, analysis.summary = "completed", summary
            analysis.analyzed_at = analysis.updated = now
            analysis.expires_at = expiry_for(analysis_type, now)
        else:
            session.add(CandidateAnalysis(case_id=case_id, property_id=property_id,
                        analysis_type=analysis_type, status="completed", summary=summary, analyzed_at=now,
                        expires_at=expiry_for(analysis_type, now)))
        check = session.scalar(select(CandidateChecklistItem).where(
            CandidateChecklistItem.property_id == property_id, CandidateChecklistItem.category == category,
        ))
        if check:
            check.status, check.source, check.evidence = checklist_status, analysis_type, evidence
            check.completed_at = now if checklist_status == "done" else None
            check.updated = now
        item.updated = _candidate_version()
        session.get(PurchaseCase, case_id).updated = now
        return True


def delete_property(case_id: int, property_id: int, user_id: int) -> bool | None:
    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(PurchaseCase.id == case_id, PurchaseCase.user_id == user_id))
        if not case:
            return None
        if case.selected_property_id == property_id:
            raise ValueError("최종 선택된 후보는 삭제할 수 없습니다. 먼저 다른 후보를 선택해주세요")
        result = session.execute(delete(CaseProperty).where(CaseProperty.id == property_id, CaseProperty.case_id == case.id))
        if result.rowcount:
            case.updated = _now_str()
        return bool(result.rowcount)


def add_region(case_id: int, user_id: int, data: dict) -> dict | None:
    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(PurchaseCase.id == case_id, PurchaseCase.user_id == user_id))
        if not case:
            return None
        region = session.scalar(select(LegalRegion).where(
            LegalRegion.code == data["region_code"], LegalRegion.is_active.is_(True)
        ))
        if not region:
            raise LookupError("region_not_found")
        existing = session.scalar(select(CaseRegion).where(
            CaseRegion.case_id == case.id, CaseRegion.region_code == region.code
        ))
        if existing:
            return _region_dict(existing)
        item = CaseRegion(case_id=case.id, region_name=region.full_name, **data)
        session.add(item)
        if region.full_name not in (case.target_regions or []):
            case.target_regions = [*(case.target_regions or []), region.full_name]
        case.updated = _now_str()
        session.flush()
        return _region_dict(item)


def delete_region(case_id: int, region_id: int, user_id: int) -> bool | None:
    with session_scope() as session:
        case = session.scalar(select(PurchaseCase).where(PurchaseCase.id == case_id, PurchaseCase.user_id == user_id))
        if not case:
            return None
        item = session.scalar(select(CaseRegion).where(
            CaseRegion.id == region_id, CaseRegion.case_id == case.id
        ))
        if not item:
            return False
        session.delete(item)
        case.target_regions = [name for name in (case.target_regions or []) if name != item.region_name]
        case.updated = _now_str()
        return True


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
