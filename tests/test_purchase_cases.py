"""매수 검토 케이스 CRUD와 소유자 격리 회귀 테스트."""
from __future__ import annotations

import os
import pytest

os.environ.setdefault("DISABLE_RATE_LIMIT", "1")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-purchase-cases")


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from db.models import (CandidateAnalysis, CandidateChecklistItem, CaseExecutionPlan,
                           CaseExecutionTask, CaseProperty, CaseRegion, HistoryRecord,
                           PurchaseCase, User)
    from tests.conftest import truncate_tables

    truncate_tables(CaseExecutionTask, CaseExecutionPlan, CandidateAnalysis,
                    CandidateChecklistItem, CaseProperty, CaseRegion, PurchaseCase,
                    HistoryRecord, User)
    from api.main import app
    with TestClient(app) as value:
        yield value


def _register(client, email: str) -> int:
    response = client.post("/api/auth/register", json={
        "email": email, "password": "test-password-1234", "name": email.split("@")[0],
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_case_crud_and_history_link(client):
    from api import history_db

    user_id = _register(client, "case-owner@example.com")
    history_id = history_db.save(
        "서울특별시 서초구 아파트", {"analysis_result": {"estimated_value": 1_500_000_000}}, user_id=user_id,
    )
    created = client.post("/api/cases", json={
        "title": "서초구 실거주 매수", "budget_max": 1_700_000_000, "target_regions": ["서울특별시 서초구"],
    })
    assert created.status_code == 201
    case_id = created.json()["id"]

    added = client.post(f"/api/cases/{case_id}/properties", json={
        "name": "후보 아파트", "address": "서울특별시 서초구", "asking_price": 1_600_000_000,
        "history_id": history_id, "source": "appraisal",
    })
    assert added.status_code == 201
    assert added.json()["appraisal"]["estimated_value"] == 1_500_000_000

    detail = client.get(f"/api/cases/{case_id}")
    assert detail.status_code == 200
    assert detail.json()["property_count"] == 1
    assert client.patch(f"/api/cases/{case_id}", json={"status": "reviewing"}).json()["status"] == "reviewing"


def test_other_user_gets_404_for_case_and_history_link(client):
    from api import history_db

    owner_id = _register(client, "case-owner2@example.com")
    history_id = history_db.save("소유자 분석", {"analysis_result": {}}, user_id=owner_id)
    case_id = client.post("/api/cases", json={"title": "소유자 케이스"}).json()["id"]

    client.cookies.clear()
    _register(client, "case-attacker@example.com")
    assert client.get(f"/api/cases/{case_id}").status_code == 404
    assert client.patch(f"/api/cases/{case_id}", json={"status": "reviewing"}).status_code == 404
    assert client.delete(f"/api/cases/{case_id}").status_code == 404
    assert client.post(f"/api/cases/{case_id}/properties", json={
        "name": "침입 후보", "history_id": history_id,
    }).status_code == 404


def test_cannot_link_other_users_history(client):
    from api import history_db

    owner_id = _register(client, "history-owner@example.com")
    history_id = history_db.save("타인 분석", {"analysis_result": {}}, user_id=owner_id)
    client.cookies.clear()
    _register(client, "case-owner3@example.com")
    case_id = client.post("/api/cases", json={"title": "내 케이스"}).json()["id"]
    response = client.post(f"/api/cases/{case_id}/properties", json={
        "name": "후보", "history_id": history_id,
    })
    assert response.status_code == 404


def test_cases_require_login(client):
    client.cookies.clear()
    assert client.get("/api/cases").status_code == 401


def test_candidate_checklist_and_owner_scoped_updates(client):
    from api import case_db, history_db

    user_id = _register(client, "workspace-owner@example.com")
    case_id = client.post("/api/cases", json={"title": "매수 검토"}).json()["id"]
    candidate = client.post(f"/api/cases/{case_id}/properties", json={"name": "후보 A"}).json()
    assert len(candidate["checklist"]) == 5

    checklist_id = candidate["checklist"][0]["id"]
    updated = client.patch(
        f"/api/cases/{case_id}/properties/{candidate['id']}/checklist/{checklist_id}",
        json={"status": "done", "evidence": "검토 완료"},
    )
    assert updated.status_code == 200
    assert updated.json()["completed_at"]
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["workspace"]["checklist_done"] == 1
    assert detail["properties"][0]["review_progress"] == 20

    history_id = history_db.save("후보 A 시세", {"analysis_result": {"estimated_value": 900_000_000}}, user_id=user_id)
    assert case_db.link_appraisal(case_id, candidate["id"], history_id, user_id, {
        "analysis_result": {"estimated_value": 900_000_000, "valuation_verdict": "적정"}
    })
    linked = client.get(f"/api/cases/{case_id}").json()["properties"][0]
    assert linked["history_id"] == history_id
    assert linked["analyses"][0]["analysis_type"] == "appraisal"

    assert case_db.link_candidate_analysis(
        case_id, candidate["id"], user_id, "simulation",
        {"purchase_price": 1_000_000_000, "loan_amount": 500_000_000},
        evidence="금융 조건 입력 완료",
    )
    assert case_db.link_candidate_analysis(
        case_id, candidate["id"], user_id, "rights",
        {"risk_grade": "caution", "risk_score": 45},
        checklist_status="warning", evidence="권리 위험 확인 필요",
    )
    linked = client.get(f"/api/cases/{case_id}").json()["properties"][0]
    assert {value["analysis_type"] for value in linked["analyses"]} == {"appraisal", "simulation", "rights"}
    statuses = {value["category"]: value["status"] for value in linked["checklist"]}
    assert statuses["funding"] == "done"
    assert statuses["rights"] == "warning"

    client.cookies.clear()
    _register(client, "workspace-attacker@example.com")
    assert client.patch(
        f"/api/cases/{case_id}/properties/{candidate['id']}", json={"status": "selected"}
    ).status_code == 404
    assert client.patch(
        f"/api/cases/{case_id}/properties/{candidate['id']}/checklist/{checklist_id}",
        json={"status": "done"},
    ).status_code == 404
    assert client.post("/api/simulation", json={
        "purchase_price": 1_000_000_000, "case_id": case_id, "candidate_id": candidate["id"],
    }).status_code == 404
    assert client.post("/api/rights/analyze", json={
        "registry_pdf_b64": "data:application/pdf;base64,JVBERi0=",
        "case_id": case_id, "candidate_id": candidate["id"],
    }).status_code == 404


def test_case_candidate_comparison_and_final_decision(client):
    user_id = _register(client, "comparison-owner@example.com")
    case_id = client.post("/api/cases", json={
        "title": "후보 비교", "budget_max": 1_000_000_000,
    }).json()["id"]
    first = client.post(f"/api/cases/{case_id}/properties", json={
        "name": "후보 A", "asking_price": 900_000_000,
    }).json()
    second = client.post(f"/api/cases/{case_id}/properties", json={
        "name": "후보 B", "asking_price": 1_100_000_000,
    }).json()

    response = client.get(
        f"/api/cases/{case_id}/comparison",
        params=[("property_id", first["id"]), ("property_id", second["id"])],
    )
    assert response.status_code == 200
    rows = {row["property_id"]: row for row in response.json()["rows"]}
    assert "예산 범위 이내" in rows[first["id"]]["highlights"]
    assert "최대 예산 초과" in rows[second["id"]]["warnings"]
    assert "자금 조건 입력 필요" in rows[first["id"]]["missing"]

    selected = client.post(f"/api/cases/{case_id}/decision", json={
        "property_id": first["id"], "reason": "예산 범위 안이며 추가 검토를 진행하기 적합함",
    })
    assert selected.status_code == 200
    assert selected.json()["selected_property_id"] == first["id"]
    assert selected.json()["status"] == "decided"
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["decision_reason"].startswith("예산 범위")
    assert next(item for item in detail["properties"] if item["id"] == first["id"])["status"] == "selected"

    client.cookies.clear()
    _register(client, "comparison-attacker@example.com")
    assert client.get(f"/api/cases/{case_id}/comparison").status_code == 404
    assert client.post(f"/api/cases/{case_id}/decision", json={
        "property_id": first["id"], "reason": "타인의 후보 선택 시도",
    }).status_code == 404


def test_single_candidate_can_be_reviewed_before_final_selection(client):
    _register(client, "comparison-single@example.com")
    case_id = client.post("/api/cases", json={"title": "단일 후보"}).json()["id"]
    client.post(f"/api/cases/{case_id}/properties", json={"name": "후보 하나"})
    response = client.get(f"/api/cases/{case_id}/comparison")
    assert response.status_code == 200
    assert len(response.json()["rows"]) == 1
    assert response.json()["rows"][0]["decision_ready"] is False


def test_decision_and_execution_roll_back_together(client, monkeypatch):
    from api import case_execution_db
    _register(client, "atomic-decision@example.com")
    case_id = client.post("/api/cases", json={"title": "원자적 선택"}).json()["id"]
    candidate = client.post(f"/api/cases/{case_id}/properties", json={"name": "후보"}).json()
    original = case_execution_db.sync_execution_plan
    def fail_after_seed(session, case):
        original(session, case)
        raise RuntimeError("injected_failure")
    monkeypatch.setattr(case_execution_db, "sync_execution_plan", fail_after_seed)
    with pytest.raises(RuntimeError, match="injected_failure"):
        client.post(f"/api/cases/{case_id}/decision", json={"property_id": candidate["id"], "reason": "선택 근거"})
    value = client.get(f"/api/cases/{case_id}").json()
    assert value["selected_property_id"] is None
    assert value["properties"][0]["status"] == "reviewing"
    assert client.get(f"/api/cases/{case_id}/execution").json()["requires_selection"] is True


def test_selection_cannot_be_bypassed_or_damaged_by_candidate_crud(client):
    _register(client, "decision-integrity@example.com")
    case_id = client.post("/api/cases", json={"title": "선택 일관성"}).json()["id"]
    candidate = client.post(f"/api/cases/{case_id}/properties", json={"name": "후보"}).json()
    path = f"/api/cases/{case_id}/properties/{candidate['id']}"
    assert client.patch(path, json={"status": "selected"}).status_code == 422
    assert client.post(f"/api/cases/{case_id}/decision", json={"property_id": candidate["id"], "reason": "   "}).status_code == 422
    assert client.post(f"/api/cases/{case_id}/decision", json={"property_id": candidate["id"], "reason": "추가 확인할 후보"}).status_code == 200
    assert client.patch(path, json={"status": "rejected"}).status_code == 422
    assert client.delete(path).status_code == 422
    assert client.get(f"/api/cases/{case_id}/execution").json()["plan"]["property_id"] == candidate["id"]


def _case_with_final_candidate(client, email: str) -> tuple[int, int]:
    _register(client, email)
    case_id = client.post("/api/cases", json={"title": "거래 실행 준비"}).json()["id"]
    candidate_id = client.post(f"/api/cases/{case_id}/properties", json={"name": "최종 후보"}).json()["id"]
    response = client.post(f"/api/cases/{case_id}/decision", json={
        "property_id": candidate_id, "reason": "현장과 자금 조건을 확인할 우선 후보",
    })
    assert response.status_code == 200
    return case_id, candidate_id


def test_final_decision_creates_execution_plan_and_recommended_dates(client):
    case_id, candidate_id = _case_with_final_candidate(client, "execution-owner@example.com")
    execution = client.get(f"/api/cases/{case_id}/execution")
    assert execution.status_code == 200
    assert execution.json()["plan"]["property_id"] == candidate_id
    assert len(execution.json()["tasks"]) == 18

    scheduled = client.patch(f"/api/cases/{case_id}/execution", json={
        "contract_planned_date": "2026-09-15", "closing_planned_date": "2026-10-30",
    })
    assert scheduled.status_code == 200
    tasks = {task["template_key"]: task for task in scheduled.json()["tasks"]}
    assert tasks["site_visit"]["due_date"] == "2026-09-08"
    assert tasks["rights_check"]["due_date"] == "2026-09-14"
    assert tasks["loan_approval"]["due_date"] == "2026-10-16"
    assert tasks["final_registry"]["due_date"] == "2026-10-30"
    assert tasks["acquisition_tax"]["due_date"] == "2026-11-29"
    assert client.patch(f"/api/cases/{case_id}/execution", json={
        "contract_planned_date": "2026-11-01", "closing_planned_date": "2026-10-30",
    }).status_code == 422


def test_execution_completion_requires_real_verification_and_reports_blockers(client):
    case_id, _ = _case_with_final_candidate(client, "execution-verify@example.com")
    execution = client.get(f"/api/cases/{case_id}/execution").json()
    site_visit = next(task for task in execution["tasks"] if task["template_key"] == "site_visit")
    assert client.patch(f"/api/cases/{case_id}/execution/tasks/{site_visit['id']}", json={
        "status": "done",
    }).status_code == 422
    completed = client.patch(f"/api/cases/{case_id}/execution/tasks/{site_visit['id']}", json={
        "status": "done", "checked_by": "본인", "outcome": "누수와 균열 없음",
        "evidence_note": "2026-09-03 현장 방문",
    })
    assert completed.status_code == 200
    refreshed = client.get(f"/api/cases/{case_id}/execution").json()
    assert refreshed["summary"]["done"] == 1

    rights = next(task for task in refreshed["tasks"] if task["template_key"] == "rights_check")
    assert client.patch(f"/api/cases/{case_id}/execution/tasks/{rights['id']}", json={
        "status": "problem", "checked_by": "법무사", "outcome": "말소 조건 확인 필요",
        "follow_up": "계약 특약 반영",
    }).status_code == 200
    summary = client.get(f"/api/cases/{case_id}/execution").json()["summary"]
    assert summary["problems"] == 1
    assert any(item["task_id"] == rights["id"] for item in summary["blockers"])


def test_execution_custom_task_deletion_and_owner_isolation(client):
    case_id, _ = _case_with_final_candidate(client, "execution-private@example.com")
    tasks = client.get(f"/api/cases/{case_id}/execution").json()["tasks"]
    assert client.delete(f"/api/cases/{case_id}/execution/tasks/{tasks[0]['id']}").status_code == 422
    custom = client.post(f"/api/cases/{case_id}/execution/tasks", json={
        "phase": "before_closing", "title": "이삿짐 업체 예약", "actor_type": "self",
    })
    assert custom.status_code == 201
    custom_id = custom.json()["id"]

    client.cookies.clear()
    _register(client, "execution-attacker@example.com")
    assert client.get(f"/api/cases/{case_id}/execution").status_code == 404
    assert client.patch(f"/api/cases/{case_id}/execution/tasks/{custom_id}", json={
        "status": "in_progress",
    }).status_code == 404
    assert client.delete(f"/api/cases/{case_id}/execution/tasks/{custom_id}").status_code == 404

    client.cookies.clear()
    assert client.post("/api/auth/login", json={
        "email": "execution-private@example.com", "password": "test-password-1234",
    }).status_code == 200
    assert client.delete(f"/api/cases/{case_id}/execution/tasks/{custom_id}").status_code == 204


def test_execution_requires_final_candidate(client):
    _register(client, "execution-no-selection@example.com")
    case_id = client.post("/api/cases", json={"title": "아직 비교 중"}).json()["id"]
    result = client.get(f"/api/cases/{case_id}/execution")
    assert result.status_code == 200
    assert result.json()["requires_selection"] is True
    assert client.patch(f"/api/cases/{case_id}/execution", json={
        "contract_planned_date": "2026-09-15",
    }).status_code == 404


def test_candidate_switch_resets_preparation_and_retains_previous_custom_evidence(client):
    case_id, first_id = _case_with_final_candidate(client, "switch-owner@example.com")
    custom = client.post(f"/api/cases/{case_id}/execution/tasks", json={
        "phase": "before_contract", "title": "추가 확인", "required": True,
    }).json()
    client.patch(f"/api/cases/{case_id}/execution/tasks/{custom['id']}", json={
        "status": "done", "checked_by": "본인", "outcome": "첫 후보 방문 완료",
    })
    client.patch(f"/api/cases/{case_id}/execution", json={"contract_planned_date": "2026-12-01"})
    second = client.post(f"/api/cases/{case_id}/properties", json={"name": "두 번째 후보"}).json()
    response = client.post(f"/api/cases/{case_id}/decision", json={"property_id": second["id"], "reason": "두 번째 후보 재검토"})
    assert response.status_code == 200
    result = client.get(f"/api/cases/{case_id}/execution").json()
    assert result["plan"]["property_id"] == second["id"]
    assert result["plan"]["contract_planned_date"] is None
    task = next(t for t in result["tasks"] if t["id"] == custom["id"])
    assert task["status"] == "scheduled" and task["completed_at"] is None
    assert "첫 후보 방문 완료" in task["evidence_note"]
    assert str(first_id) in task["evidence_note"]
    again = client.post(f"/api/cases/{case_id}/decision", json={"property_id": second["id"], "reason": "같은 후보 근거 보완"})
    assert again.status_code == 200
    assert len(client.get(f"/api/cases/{case_id}/execution").json()["tasks"]) == 19


def test_clear_decision_reopen_and_reselect_preserves_same_candidate_work(client):
    case_id, candidate_id = _case_with_final_candidate(client, "reconsider@example.com")
    path = f"/api/cases/{case_id}"
    task = client.get(f"{path}/execution").json()["tasks"][0]
    assert client.patch(f"{path}/execution/tasks/{task['id']}", json={
        "status": "done", "checked_by": "본인", "outcome": "현장 확인 완료",
    }).status_code == 200
    assert client.delete(f"{path}/decision").status_code == 200
    assert client.get(f"{path}/execution").json()["requires_selection"] is True
    assert client.patch(f"{path}/execution/tasks/{task['id']}", json={"status": "in_progress"}).status_code == 404
    assert client.get(path).json()["status"] == "reviewing"
    assert client.post(f"{path}/decision", json={"property_id": candidate_id, "reason": "조건 재확인 후 유지"}).status_code == 200
    restored = client.get(f"{path}/execution").json()
    assert next(t for t in restored["tasks"] if t["id"] == task["id"])["outcome"] == "현장 확인 완료"
    client.cookies.clear()
    _register(client, "reconsider-attacker@example.com")
    assert client.delete(f"{path}/decision").status_code == 404


def test_purchase_journey_from_budget_to_recorded_preparation_completion(client):
    """가상 매수 조건을 실제 API·DB로 연결한다. 실거래 성과나 문서 정확도 평가는 아니다."""
    _register(client, "journey@example.com")
    case = client.post("/api/cases", json={"title": "매수 흐름 검증", "budget_max": 900_000_000}).json()
    path = f"/api/cases/{case['id']}"
    candidate = client.post(f"{path}/properties", json={"name": "가상 후보", "asking_price": 950_000_000}).json()
    assert {item["code"] for item in client.get(path).json()["properties"][0]["next_actions"]} >= {"budget", "source_unverified"}
    assert client.patch(f"{path}/properties/{candidate['id']}", json={"asking_price": 880_000_000}).status_code == 200
    comparison = client.get(f"{path}/comparison").json()["rows"][0]
    assert not comparison["decision_ready"]
    assert "시세분석 필요" in comparison["missing"]
    assert client.post(f"{path}/decision", json={"property_id": candidate["id"], "reason": "미확인 자료를 추가 검토할 우선 후보"}).status_code == 200
    assert client.patch(f"{path}/execution", json={"contract_planned_date": "2026-12-01", "closing_planned_date": "2027-01-15"}).status_code == 200
    for task in client.get(f"{path}/execution").json()["tasks"]:
        response = client.patch(f"{path}/execution/tasks/{task['id']}", json={
            "status": "done", "checked_by": "평가용 가상 확인자", "outcome": "가상 시나리오의 확인 기록",
        })
        assert response.status_code == 200
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "journey@example.com", "password": "test-password-1234"}).status_code == 200
    result = client.get(f"{path}/execution").json()
    assert result["plan"]["property_id"] == candidate["id"]
    assert result["summary"]["done"] == result["summary"]["total"] == 18
    assert result["summary"]["progress_percent"] == 100
    # 실행 기록을 모두 완료해도 누락된 분석 자체가 완료로 바뀌지는 않는다.
    assert client.get(f"{path}/comparison").json()["rows"][0]["decision_ready"] is False


def test_next_actions_refresh_after_price_edit_and_enforce_ownership(client):
    _register(client, "next-action-owner@example.com")
    case_id = client.post("/api/cases", json={"title": "다음 행동", "budget_max": 900_000_000}).json()["id"]
    candidate_id = client.post(f"/api/cases/{case_id}/properties", json={"name": "후보"}).json()["id"]
    def actions():
        return client.get(f"/api/cases/{case_id}").json()["properties"][0]["next_actions"]
    assert {item["code"] for item in actions()} >= {"asking_price", "source_unverified"}
    endpoint = f"/api/cases/{case_id}/properties/{candidate_id}"
    assert client.patch(endpoint, json={"asking_price": -1}).status_code == 422
    assert client.patch(endpoint, json={"asking_price": 1_000_000_000}).status_code == 200
    assert {item["code"] for item in actions()} >= {"budget", "source_unverified"}
    assert "asking_price" not in {item["code"] for item in actions()}
    assert client.patch(endpoint, json={"status": "rejected"}).status_code == 200
    assert actions() == []
    client.cookies.clear()
    _register(client, "next-action-other@example.com")
    assert client.patch(endpoint, json={"asking_price": 1}).status_code == 404
    assert client.get(f"/api/cases/{case_id}").status_code == 404
