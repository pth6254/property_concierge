"""여러 부동산 기능을 도구로 확장하는 종합 컨시어지 LangGraph."""
from __future__ import annotations

import json
import re
from typing import Any

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from backend.concierge.tools import execute_tool
from schemas.concierge import ConciergeCriteria, ConciergeDecision, ConciergeExtraction, ConciergeFunding, ConciergeIntent, ConciergeToolResult
from backend.concierge.validation import merge_extraction
from backend.concierge.decision_tools import merge_funding, FUNDING_LABELS


class ConciergeState(TypedDict, total=False):
    user_id: int
    message: str
    previous_criteria: dict[str, Any]
    decision: ConciergeDecision
    tool_result: ConciergeToolResult
    answer: str
    blocked: list[str]
    routing_error: str
    validation_fields: list[str]
    candidate_context: dict
    funding: dict
    history: list[dict]
    last_result: dict
    funding_errors: list[str]


ROUTER_PROMPT = """당신은 종합 부동산 컨시어지의 의도 분류기입니다.
사용자의 말에서 확인되는 값만 추출하고 추측하지 마세요. 금액은 원, 면적은 ㎡로 변환하세요.
intent는 find_region, select_property, search_listing, appraise, compare, simulate, rights_check,
tax_legal, general 중 하나입니다. 반드시 아래 형태의 JSON만 반환하세요.
{"intent":"find_region","criteria":{"property_type":"apartment","transaction_type":"purchase",
"budget_max_won":1000000000,"region_name":"서울","region_code":null,"area_min_sqm":null,"purpose":null}}
동네·지역 추천은 find_region, 특정 매물·단지 선택은 select_property, 가격 추정은 appraise,
구체적인 아파트 단지 추천, '그럼 단지 추천해줘'도 select_property입니다. 기존 지역·예산·매매 조건은 유지하고 새로 명시된 조건만 추출하세요.
사용자가 등록·업로드한 매물 검색, 판매 중인 매물·호가 조회 요청은 search_listing입니다. 외부 포털 검색은 제공하지 않습니다. 월세 예산에서 보증금과 월세를 혼동하지 말고 budget_max_won은 보증금 상한만 추출하세요.
동네·구·읍·면·동의 실거래 비교도 find_region입니다. compare는 저장한 개별 후보 물건 비교에만 사용합니다.
region_name에는 사용자가 명시한 가장 구체적인 지역을 넣으세요. 강남구를 서울로 축약하지 마세요.
region_code는 반드시 생략하거나 null로 두세요. 공식 코드는 서버가 지역명으로 조회합니다.
예: '서울특별시 강남구에서 8억 이하 아파트 매매 동네 비교해줘' →
{"intent":"find_region","criteria":{"region_name":"서울특별시 강남구","property_type":"apartment","transaction_type":"purchase","budget_max_won":800000000}}
예: 동네 비교 후 '그럼 역삼동은 어때?' → {"intent":"find_region","criteria":{"region_name":"역삼동"}}
취득세·양도세·보유세·법률 질문은 tax_legal, 인사·사용법은 general입니다.
criteria에는 새 메시지에서 확인되는 변경값만 넣으세요. 모르는 값은 생략하거나 null로 두세요.
transaction_type은 purchase(매매), rent(월세), lease(전세) 중 명시된 값만 넣으세요.
조건 삭제를 명시한 경우에만 clear_fields에 해당 필드명을 넣으세요. null은 삭제가 아닙니다.
자금 계산과 금융 조건 보완은 simulate, 케이스 후보 비교는 compare입니다.
최근 대화와 직전 도구 결과를 참고하여 '그럼', '금리만 바꿔', 조건 보완을 이해하세요.
funding에는 새 메시지에 명시된 금융 조건의 변경값만 넣으세요. 기존 값이나 기본값을 복사하지 마세요.
허용 필드: cash_available(보유 현금 원), monthly_payment_limit(월 상환 한도 원),
loan_ratio(대출 비율 0~0.9, 50%는 0.5), annual_interest_rate(연 금리 %, 4%는 4),
loan_years(대출 기간 년), repayment_type(equal_payment 원리금균등, equal_principal 원금균등,
interest_only 만기일시), owned_homes(취득 후 주택 수, 현재 무주택이면 취득 후 1),
adjusted_area(조정대상지역 여부 true/false), annual_income(연소득 원),
existing_loan_annual_payment(기존 대출 연간 상환액 원, 기존 대출 없음은 0).
후보 희망가는 서버에서 가져오므로 추출하지 마세요. 모르는 금융 조건은 생략하세요.
후보 선택은 화면의 선택을 따릅니다. 다른 후보를 임의로 선택하지 마세요.
예: '현금 3억, 대출 50%로 자금 계산해줘' →
{"intent":"simulate","criteria":{},"funding":{"cash_available":300000000,"loan_ratio":0.5}}
예: '그럼 금리만 5%로' → {"intent":"simulate","criteria":{},"funding":{"annual_interest_rate":5}}
funding은 criteria 안이 아닌 최상위 필드입니다. criteria에 금융 필드를 넣지 마세요.
case_id, candidate_id는 서버가 관리하는 선택 정보입니다. 출력의 어느 필드에도 넣지 마세요."""


def _parse_json(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        return json.loads(match.group()) if match else {}


def decide_node(state: ConciergeState) -> ConciergeState:
    from backend.model_factory import get_chat_llm

    previous = state.get("previous_criteria") or {}
    # 명확한 실행 명령은 모델 응답을 기다리지 않는다. 질문·부정문은 이 규칙에 포함하지 않는다.
    command = re.sub(r"\s+", "", state["message"]).rstrip(".!?").lower()
    direct_intent = {
        "자금분석해줘": ConciergeIntent.SIMULATE, "이후보자금분석해줘": ConciergeIntent.SIMULATE,
        "후보비교해줘": ConciergeIntent.COMPARE, "그럼후보비교해줘": ConciergeIntent.COMPARE,
        "이케이스후보비교해줘": ConciergeIntent.COMPARE,
    }.get(command)
    if direct_intent:
        return {**state, "decision": ConciergeDecision(intent=direct_intent,
                criteria=ConciergeCriteria.model_validate(previous))}
    if command in {"이후보시세를추정해줘", "이후보시세추정해줘", "선택한후보의avm시세를추정해줘",
                   "선택한후보시세를추정해줘", "선택한후보의시세를추정해줘", "avm실행해줘"}:
        return {**state, "decision": ConciergeDecision(intent=ConciergeIntent.APPRAISE,
                criteria=ConciergeCriteria.model_validate(previous))}
    prompt = state["message"]
    if previous:
        prompt = f"이전 조건: {json.dumps(previous, ensure_ascii=False)}\n새 메시지: {prompt}"
    prompt = json.dumps({"최근 대화": state.get("history", []),
                         "직전 결과": state.get("last_result", {}),
                         "선택": state.get("candidate_context", {}),
                         "기존 자금 조건": state.get("funding", {})}, ensure_ascii=False) + "\n" + prompt
    try:
        response = get_chat_llm(json_mode=True).invoke([("system", ROUTER_PROMPT), ("human", prompt)])
        extraction = ConciergeExtraction.model_validate(_parse_json(str(response.content)))
        for key in ("case_id", "candidate_id"):
            if key in extraction.criteria:
                if extraction.criteria.pop(key) != (state.get("candidate_context") or {}).get(key):
                    raise ValueError("candidate_selection_mismatch")
        # 모델이 금융 필드를 검색 조건에 놓는 실제 출력 오류를 허용 필드만 이동해 복구한다.
        # 상충하는 값은 선택하지 않고 검증 오류로 돌려보낸다.
        for key in list(extraction.criteria):
            if key in ConciergeFunding.model_fields:
                value = extraction.criteria.pop(key)
                if key in extraction.funding and extraction.funding[key] != value:
                    raise ValueError("conflicting_funding")
                extraction.funding[key] = value
        criteria, fields = merge_extraction(extraction, previous, state["message"])
        decision = ConciergeDecision(intent=extraction.intent, criteria=criteria)
        funding, funding_errors = merge_funding(extraction.funding, state.get("funding") or {})
    except Exception as exc:
        # LLM 장애 시 숫자나 지역을 추측하지 않고 보완 입력을 받는 안전한 폴백이다.
        decision = ConciergeDecision(
            intent=ConciergeIntent.GENERAL,
            criteria=ConciergeCriteria.model_validate(previous),
        )
        return {**state, "decision": decision, "routing_error": type(exc).__name__}
    return {**state, "decision": decision, "validation_fields": fields,
            "funding": funding, "funding_errors": funding_errors}


def execute_node(state: ConciergeState) -> ConciergeState:
    decision = state["decision"]
    if state.get("routing_error"):
        return {**state, "tool_result": ConciergeToolResult(tool="intent_router", status="error")}
    if state.get("funding_errors"):
        fields = state["funding_errors"]
        return {**state, "tool_result": ConciergeToolResult(tool="funding_validation", status="needs_input",
                missing_fields=fields, data={"answer": ", ".join(FUNDING_LABELS.get(f, "금융 조건") for f in fields)
                + "을(를) 확인해주세요. 잘못된 조건으로 계산하지 않았습니다."})}
    if state.get("validation_fields"):
        return {**state, "tool_result": ConciergeToolResult(tool="criteria_validation", status="needs_input",
                missing_fields=state["validation_fields"])}
    result = execute_tool(decision.intent, decision.criteria, state["user_id"], state.get("candidate_context"), message=state["message"], funding=state.get("funding"), history=state.get("history"))
    return {**state, "tool_result": result, "decision": decision}


def _fallback_answer(result: ConciergeToolResult) -> str:
    if result.status == "error":
        return "요청 의도를 확인하지 못했습니다. 원하는 기능이나 조건을 조금 더 구체적으로 알려주세요."
    if result.tool == "general_help":
        return result.data["answer"]
    if result.status == "queued":
        return "선택한 후보의 AVM 시세추정을 시작했습니다. 완료되면 결과와 후보 연결 상태를 안내하겠습니다."
    if result.tool == "appraise_property" and result.status == "needs_input":
        return "분석할 케이스와 후보를 선택해주세요." if "candidate" in result.missing_fields else "후보의 주소·면적·물건 종류를 시세추정 화면에서 확인해주세요."
    if result.status == "needs_input":
        labels = {"region": "희망 지역", "region_code": "정확한 지역",
                  "property_type": "부동산 유형", "budget_max_won": "최대 예산",
                  "transaction_type": "거래 유형(매매·전세·월세)", "region_name": "정확한 지역명",
                  "area_min_sqm": "최소 면적", "purpose": "거주·투자 목적", "criteria": "검색 조건"}
        fields = ", ".join(labels.get(field, field) for field in result.missing_fields)
        if result.tool == "criteria_validation":
            return f"{fields}을(를) 확인하지 못했습니다. 조건을 다시 알려주세요. 해당 조건으로 분석을 실행하지 않았습니다."
        if result.data.get("region_candidates"):
            names = ", ".join(item["full_name"] for item in result.data["region_candidates"])
            return f"같은 이름의 지역이 여러 곳입니다. 다음 중 선택해 주세요: {names}"
        return f"동네를 비교하려면 {fields}을(를) 알려주세요."
    if result.status == "not_available":
        return "이 요청을 처리할 도구는 종합 컨시어지 구조에 등록되어 있지만 아직 연결 준비 중입니다."
    items = result.data.get("items", [])
    if not items:
        return "선택한 조건으로 수집된 실거래 데이터를 찾지 못했습니다."
    names = ", ".join(item["region_name"] for item in items[:3])
    return f"수집된 실거래를 기준으로 우선 살펴볼 지역은 {names}입니다. 상세 수치는 지역 카드에서 확인해 주세요."


def explain_node(state: ConciergeState) -> ConciergeState:
    import backend.opinion_guard as opinion_guard
    from backend.model_factory import get_llm

    result = state["tool_result"]
    if result.tool in {"simulate_investment", "compare_properties", "funding_validation", "select_properties", "search_listings"}:
        return {**state, "answer": result.data["answer"], "blocked": []}
    if result.tool == "answer_tax_legal":
        return {**state, "answer": result.data["answer"], "blocked": result.data.get("blocked", [])}
    if result.status != "completed" or result.tool == "general_help":
        return {**state, "answer": _fallback_answer(result), "blocked": []}

    context = json.dumps(result.data, ensure_ascii=False)
    allowed = opinion_guard.extract_numbers(context) | opinion_guard.extract_numbers(state["message"])
    prompt = ("아래 도구 결과에 있는 사실과 숫자만 사용해 한국어로 간결히 설명하세요. "
              "새 가격·비율·거래량을 만들지 말고, 실거래 출처와 기간을 밝히세요. "
              "현재 매물 호가라고 표현하지 마세요.\n" + context)
    try:
        raw = str(get_llm().invoke([("system", prompt), ("human", state["message"])]).content).strip()
        answer, blocked = opinion_guard.sanitize_text(raw, allowed)
    except Exception:
        answer, blocked = "", []
    return {**state, "answer": answer or _fallback_answer(result), "blocked": blocked}


def build_concierge_graph():
    graph = StateGraph(ConciergeState)
    graph.add_node("의도_조건_추출", decide_node)
    graph.add_node("허용_도구_실행", execute_node)
    graph.add_node("근거_결과_설명", explain_node)
    graph.set_entry_point("의도_조건_추출")
    graph.add_edge("의도_조건_추출", "허용_도구_실행")
    graph.add_edge("허용_도구_실행", "근거_결과_설명")
    graph.add_edge("근거_결과_설명", END)
    return graph.compile()


_GRAPH = None


def run_concierge(*, user_id: int, message: str, previous_criteria: dict | None = None, candidate_context: dict | None = None,
                  funding: dict | None = None, history: list | None = None, last_result: dict | None = None) -> ConciergeState:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_concierge_graph()
    return _GRAPH.invoke({
        "user_id": user_id, "message": message,
        "previous_criteria": previous_criteria or {},
        "candidate_context": candidate_context or {},
        "funding": funding or {}, "history": history or [], "last_result": last_result or {},
    })
