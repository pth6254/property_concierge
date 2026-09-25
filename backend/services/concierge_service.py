"""사용자별 대화 상태와 종합 컨시어지 그래프를 연결한다."""
from __future__ import annotations

import json
import re
from uuid import UUID, uuid4

from backend.graphs.concierge_graph import run_concierge
from db.redis_client import get_redis
from schemas.concierge import ConciergeMessageResponse
from schemas.purchase_case import BuyerProfile

_TTL_SECONDS = 24 * 60 * 60
_SAVED_PROFILE_FIELDS = {
    "cash_available", "monthly_payment_limit", "annual_income",
    "existing_loan_annual_payment", "loan_ratio", "annual_interest_rate",
    "loan_years", "owned_homes", "adjusted_area",
}
_CASE_SAVE_REQUEST = re.compile(r"^\s*(?:이\s*)?(?:케이스|매수)\s*조건.{0,80}(?:저장|변경|수정|바꿔|바꾸|설정)")


def _save_explicit_case_conditions(case: dict | None, user_id: int, message: str,
                                   old_funding: dict, new_funding: dict,
                                   old_criteria: dict, new_criteria: dict) -> dict | None:
    """명시적 저장 요청에서 이번 대화에 새로 추출한 값만 케이스에 반영한다."""
    if not case or not _CASE_SAVE_REQUEST.search(message):
        return None
    from api import case_db

    changes = {key: value for key, value in new_funding.items()
               if key in _SAVED_PROFILE_FIELDS and value is not None and old_funding.get(key) != value}
    budget = new_criteria.get("budget_max_won")
    budget_changed = budget is not None and budget != old_criteria.get("budget_max_won")
    if not changes and not budget_changed:
        return {"status": "needs_input", "answer": "저장할 새 매수 조건을 구체적인 값과 함께 알려주세요. 예: 케이스 조건 보유 현금 4억원으로 변경"}
    try:
        profile = BuyerProfile.model_validate({**(case.get("buyer_profile") or {}), **changes})
        if budget_changed and case.get("budget_min") is not None and budget < case["budget_min"]:
            raise ValueError("최대 예산이 최소 예산보다 작습니다")
    except ValueError:
        return {"status": "needs_input", "answer": "매수 조건을 저장하지 못했습니다. 보유 현금·비상자금·대출 비율·예산을 확인해주세요."}
    updates = {"buyer_profile": profile.model_dump(mode="json")}
    if budget_changed:
        updates["budget_max"] = budget
    saved = case_db.update_case(case["id"], user_id, updates)
    if not saved:
        raise LookupError("case_not_found")
    return {"status": "completed", "answer": "케이스 매수 조건을 저장했습니다. 후보 비교의 자금 시나리오와 이후 챗봇 분석에 적용됩니다.",
            "case_id": case["id"], "result_url": f"/cases/{case['id']}"}


def _conversation_key(user_id: int, conversation_id: str) -> str:
    return f"concierge:{user_id}:{conversation_id}"


def restore_conversation(user_id: int, conversation_id: str) -> dict:
    from api import case_db
    conversation_id = str(UUID(conversation_id))
    saved = get_redis().get(_conversation_key(user_id, conversation_id))
    if not saved:
        raise LookupError("conversation_not_found")
    previous = json.loads(saved)
    context = previous.get("candidate_context") or {}
    if context.get("case_id"):
        if not case_db.get_case(context["case_id"], user_id):
            raise LookupError("case_not_found")
        if context.get("candidate_id") and not case_db.validate_candidate(context["case_id"], context["candidate_id"], user_id):
            raise LookupError("candidate_not_found")
    # 조회만으로 보존 기한을 늘리지 않는다. 다른 사용자의 키를 탐색하지 않는다.
    return {"conversation_id": conversation_id, "candidate_context": context,
            "messages": previous.get("messages", previous.get("history", []))}


def handle_message(*, user_id: int, message: str, conversation_id: str | None, case_id: int | None = None, candidate_id: int | None = None, clear_context: bool = False) -> ConciergeMessageResponse:
    from api import case_db
    if conversation_id:
        # Redis 키 경계를 흔드는 임의 문자열을 받지 않고 UUID만 허용한다.
        conversation_id = str(UUID(conversation_id))
    else:
        conversation_id = str(uuid4())

    redis = get_redis()
    key = _conversation_key(user_id, conversation_id)
    saved = redis.get(key)
    if isinstance(saved, bytes):
        saved = saved.decode("utf-8")
    previous = json.loads(saved) if saved else {}
    context = {} if clear_context else previous.get("candidate_context", {})
    if case_id is not None:
        context = {"case_id": case_id, "candidate_id": candidate_id}
    elif candidate_id is not None:
        raise LookupError("candidate_not_found")
    # Redis에 저장된 ID도 매 턴 재검증한다. 삭제·소유권 변경 후 과거 맥락을 실행하지 않는다.
    case = None
    if context.get("case_id"):
        case = case_db.get_case(context["case_id"], user_id)
        if not case:
            raise LookupError("case_not_found")
        if context.get("candidate_id") and not case_db.validate_candidate(context["case_id"], context["candidate_id"], user_id):
            raise LookupError("candidate_not_found")
    same_candidate = context == previous.get("candidate_context", {})
    funding = previous.get("funding", {}) if same_candidate else {}
    history = previous.get("history", []) if same_candidate else []

    criteria = dict(previous.get("criteria") or {}) if same_candidate else {}
    if case:
        profile = case.get("buyer_profile") or {}
        defaults = {"budget_max_won": case.get("budget_max"),
                    "area_min_sqm": profile.get("min_area_sqm")}
        if len(profile.get("property_types") or []) == 1:
            defaults["property_type"] = profile["property_types"][0]
        for field, value in defaults.items():
            if value is not None and criteria.get(field) is None:
                criteria[field] = value

    state = run_concierge(
        user_id=user_id, message=message,
        previous_criteria=criteria,
        candidate_context=context, funding=funding, history=history,
        last_result=previous.get("last_result", {}) if same_candidate else {},
    )
    saved_conditions = _save_explicit_case_conditions(
        case, user_id, message, funding, state.get("funding") or {},
        criteria, state["decision"].criteria.model_dump(exclude_none=True),
    )
    if saved_conditions:
        from schemas.concierge import ConciergeToolResult
        state["tool_result"] = ConciergeToolResult(
            tool="update_case_profile", status=saved_conditions["status"],
            data=saved_conditions,
        )
        state["answer"] = saved_conditions["answer"]
    decision = state["decision"]
    result = state["tool_result"]
    response = ConciergeMessageResponse(
        conversation_id=conversation_id, status=result.status,
        intent=decision.intent, answer=state["answer"], criteria=decision.criteria,
        data=result.data, missing_fields=result.missing_fields, tool_used=result.tool,
    )
    redis.set(
        key,
        json.dumps({"criteria": decision.criteria.model_dump(), "intent": decision.intent.value,
                    "candidate_context": context, "funding": state.get("funding", funding),
                    "messages": (previous.get("messages", previous.get("history", [])) + [
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": state["answer"], "response": response.model_dump(mode="json")},
                    ])[-40:],
                    "history": (history + [{"role": "user", "content": message},
                                {"role": "assistant", "content": state["answer"][:2000]}])[-8:],
                    "last_result": {"tool": result.tool, "status": result.status,
                                    "missing_fields": result.missing_fields}}, ensure_ascii=False),
        ex=_TTL_SECONDS,
    )

    return response
