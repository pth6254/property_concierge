"""거래 준비 작업 템플릿, 권장일과 준비도를 계산한다."""
from __future__ import annotations

from datetime import date, timedelta

PHASES = ("before_contract", "before_closing", "closing_day", "after_closing")
SATISFIED_STATUSES = {"done", "not_applicable"}

# anchor는 법정기한이 아니라 사용자가 준비를 놓치지 않도록 제시하는 서비스 권장일이다.
TASK_TEMPLATES = [
    ("site_visit", "before_contract", "현장 방문 및 하자 확인", "self", "contract", -7, True),
    ("appraisal_review", "before_contract", "시세분석 확인", "self", "contract", -7, True),
    ("rights_check", "before_contract", "최신 등기부·건축물대장 확인", "self", "contract", -1, True),
    ("funding_check", "before_contract", "대출 가능 금액 확인", "bank", "contract", -7, True),
    ("extra_costs", "before_contract", "취득세·중개보수 등 부대비용 확인", "self", "contract", -5, True),
    ("broker_explanation", "before_contract", "중개대상물 확인설명서 검토", "broker", "contract", -1, True),
    ("contract_review", "before_contract", "계약서·특약 초안 검토", "self", "contract", -3, True),
    ("loan_approval", "before_closing", "대출 본심사 완료 확인", "bank", "closing", -14, True),
    ("closing_funds", "before_closing", "잔금 자금 확보", "self", "closing", -7, True),
    ("management_fees", "before_closing", "체납 관리비 확인", "broker", "closing", -1, True),
    ("fixtures", "before_closing", "시설물 인수 목록 확인", "self", "closing", -3, False),
    ("registration_schedule", "before_closing", "법무사 등기 일정 확인", "legal_agent", "closing", -7, True),
    ("final_registry", "closing_day", "잔금 지급 전 권리변동 재확인", "legal_agent", "closing", 0, True),
    ("closing_payment", "closing_day", "잔금 지급", "self", "closing", 0, True),
    ("handover", "closing_day", "열쇠·시설물 인수", "self", "closing", 0, True),
    ("registration_filing", "closing_day", "소유권이전등기 접수 확인", "legal_agent", "closing", 0, True),
    ("acquisition_tax", "after_closing", "취득세 신고·납부 확인", "tax_agent", "closing", 30, True),
    ("registration_complete", "after_closing", "소유권이전등기 완료 확인", "legal_agent", "closing", 30, True),
]


def due_date_for(anchor: str, offset_days: int, contract_date: str | None, closing_date: str | None) -> str | None:
    value = contract_date if anchor == "contract" else closing_date
    if not value:
        return None
    return (date.fromisoformat(value) + timedelta(days=offset_days)).isoformat()


def readiness_summary(tasks: list[dict], today: date | None = None) -> dict:
    current = today or date.today()
    total_weight = sum(2 if task.get("required") else 1 for task in tasks)
    done_weight = sum(
        (2 if task.get("required") else 1)
        for task in tasks if task.get("status") in SATISFIED_STATUSES
    )
    overdue = [task for task in tasks if task.get("due_date") and date.fromisoformat(task["due_date"]) < current and task.get("status") not in SATISFIED_STATUSES]
    problems = [task for task in tasks if task.get("status") == "problem"]
    waiting = [task for task in tasks if task.get("status") == "waiting_external"]
    blockers = [
        {"task_id": task["id"], "title": task["title"], "reason": "문제 발견"}
        for task in problems
    ] + [
        {"task_id": task["id"], "title": task["title"], "reason": "권장일 경과"}
        for task in overdue if task not in problems
    ]
    return {
        "progress_percent": round(done_weight / total_weight * 100) if total_weight else 0,
        "total": len(tasks),
        "done": sum(task.get("status") in SATISFIED_STATUSES for task in tasks),
        "overdue": len(overdue), "problems": len(problems), "waiting_external": len(waiting),
        "blockers": blockers,
    }
