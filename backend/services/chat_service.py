"""
chat_service.py — 부동산 법률·세금 AI 정보 안내 챗봇

⚖️ 포지셔닝: 변호사법·세무사법상 "상담"이 아닌 "일반 정보 안내".
   모든 답변에 면책 고지를 부착하고, 개별 사안 판단을 하지 않도록
   시스템 프롬프트로 제한한다.

아키텍처 (검증된 패턴 재사용):
  1. 도구 라우팅 — LLM JSON 모드로 세금 계산 필요 여부·파라미터 추출
  2. 도구 실행   — tax_rules.py 결정론 계산기 (증여·상속·양도·보유세)
  3. RAG 검색    — chat_corpus.py (법령·분쟁사례)
  4. 답변 생성   — 도구 결과 + 근거 청크 주입
  5. 수치 가드   — opinion_guard: 주입한 숫자 외의 수치가 든 문장 제거
"""

from __future__ import annotations

import json
import os
import re
import sys
from time import perf_counter

_SVC_DIR      = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_SVC_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

DISCLAIMER = ("본 답변은 일반적인 법령·세금 정보 안내이며, 법률 상담·세무 상담이 아닙니다. "
              "개별 사안은 변호사·세무사·법무사 등 전문가와 상담하시기 바랍니다.")

# ─────────────────────────────────────────
#  1. 도구 라우팅
# ─────────────────────────────────────────

ROUTER_PROMPT = """당신은 부동산 세금 질문에서 계산 파라미터를 추출하는 라우터입니다.
사용자 질문에 세금 '계산'이 필요하면 도구와 파라미터를, 아니면 tool="none"을 반환하세요.

반드시 JSON만 응답:
{
  "tool": "gift_tax | inheritance_tax | capital_gains_tax | holding_tax | none",
  "params": {
    // gift_tax: gift_value(원), relation(배우자|직계존속|직계존속미성년|직계비속|기타친족|타인), prior_gifts_10yr(원)
    // inheritance_tax: estate_value(원), has_spouse(bool), debts(원)
    // capital_gains_tax: purchase_price(원), sale_price(원), holding_years(정수), owned_homes(정수), residence_years(정수)
    // holding_tax: official_price(원, 공시가격), owned_homes(정수)
  }
}
금액은 원 단위 정수로 변환하세요 (예: "5억" → 500000000). 언급되지 않은 파라미터는 생략하세요.
계산에 필수적인 금액이 질문에 없으면 tool="none"으로 하세요.
이전 사용자 발언이 제공되면 현재 질문의 생략된 조건만 보완하세요. 현재 질문의 변경값이 우선입니다.
현재 질문이 다른 주제이거나 계산을 요청하지 않으면 이전 계산을 다시 실행하지 마세요."""


def _route_tool(question: str, trace: dict | None = None) -> dict:
    """질문 → {tool, params}. 실패 시 none."""
    try:
        from model_factory import get_chat_llm
        llm = get_chat_llm(json_mode=True)
        res = llm.invoke([("system", ROUTER_PROMPT), ("human", question)])
        raw = res.content.strip()
        try:
            out = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            out = json.loads(m.group()) if m else {}
        if isinstance(out, dict) and out.get("tool") in (
                "gift_tax", "inheritance_tax", "capital_gains_tax", "holding_tax"):
            return {"tool": out["tool"], "params": out.get("params") or {}}
    except Exception as e:
        if trace is not None:
            trace["routing_error"] = type(e).__name__
        print(f"[chat] 도구 라우팅 실패: {e}")
    return {"tool": "none", "params": {}}


def _run_tool(tool: str, params: dict, trace: dict | None = None) -> dict | None:
    """결정론 계산기 실행. 반환: {name, inputs, outputs, summary} | None"""
    import tax_rules as tr

    try:
        if tool == "gift_tax" and params.get("gift_value"):
            r = tr.calc_gift_tax(
                int(params["gift_value"]),
                relation=str(params.get("relation", "직계존속")),
                prior_gifts_10yr=int(params.get("prior_gifts_10yr", 0) or 0),
            )
            return {"name": "증여세 계산", "inputs": params, "outputs": r,
                    "summary": f"증여세 약 {r['tax']:,}원 ({r['note']})"}

        if tool == "inheritance_tax" and params.get("estate_value"):
            r = tr.calc_inheritance_tax(
                int(params["estate_value"]),
                has_spouse=bool(params.get("has_spouse", True)),
                debts=int(params.get("debts", 0) or 0),
            )
            return {"name": "상속세 계산", "inputs": params, "outputs": r,
                    "summary": f"상속세 약 {r['tax']:,}원 ({r['note']})"}

        if tool == "capital_gains_tax" and params.get("purchase_price") and params.get("sale_price"):
            r = tr.calc_capital_gains_tax(
                int(params["purchase_price"]), int(params["sale_price"]),
                int(params.get("holding_years", 2) or 2),
                owned_homes=int(params.get("owned_homes", 1) or 1),
                residence_years=int(params.get("residence_years", 0) or 0),
            )
            return {"name": "양도소득세 계산", "inputs": params, "outputs": r,
                    "summary": f"양도소득세 약 {r['tax']:,}원 ({r['note']})"}

        if tool == "holding_tax" and params.get("official_price"):
            r = tr.calc_annual_holding_tax(
                int(params["official_price"]),
                owned_homes=int(params.get("owned_homes", 1) or 1),
            )
            return {"name": "보유세 계산", "inputs": params, "outputs": r,
                    "summary": f"연간 보유세 약 {r['total']:,}원 "
                               f"(재산세 {r['property_tax']:,} + 종부세 {r['jongbu_tax']:,} 외)"}
    except Exception as e:
        if trace is not None:
            trace["tool_error"] = type(e).__name__
        print(f"[chat] 도구 실행 실패 ({tool}): {e}")
    return None


# ─────────────────────────────────────────
#  2. 답변 생성
# ─────────────────────────────────────────

ANSWER_PROMPT = """당신은 부동산 법령·세금 '정보 안내' AI입니다.

규칙:
- 아래 [근거 자료]와 [계산 결과]에 있는 내용만으로 답하세요. 근거에 없으면 "제공된 자료로는 확인이 어렵다"고 말하세요.
- 수치는 근거 자료·계산 결과에 있는 값만 그대로 인용하세요. 새 수치를 만들면 해당 문장은 자동 삭제됩니다.
- "상담", "판단", "~하셔야 합니다" 같은 단정 대신 "일반적으로 ~입니다", "~가 원칙입니다"로 안내하세요.
- 스스로를 변호사·세무사로 칭하지 마세요.
- 답변 끝에 개별 사안은 전문가 확인이 필요하다는 점을 한 문장으로 안내하세요.
- 한국어로 명확하고 간결하게, 필요하면 번호 목록으로 답하세요."""


def _build_context(chunks: list[dict], tool_result: dict | None) -> str:
    parts = []
    if tool_result:
        parts.append(f"[계산 결과 — {tool_result['name']} (간이, 세법 기준)]")
        parts.append(json.dumps(tool_result["outputs"], ensure_ascii=False))
        parts.append(f"요약: {tool_result['summary']}")
    if chunks:
        parts.append("\n[근거 자료]")
        for i, c in enumerate(chunks, 1):
            provenance = f" / 시행일 {c['effective_date']} / 수집일 {c.get('collected_at', '')}" if c.get("effective_date") else ""
            parts.append(f"({i}) {c['title']} — 출처: {c['source']}{provenance}\n{c['text']}")
    return "\n".join(parts) if parts else "[근거 자료 없음]"


def answer_question(question: str, history: list[dict] | None = None, *, trace: dict | None = None) -> dict:
    """
    질문 → 답변.

    반환: {answer, sources: [{title, source}], tool_used, disclaimer, blocked: [...]}
    """
    import chat_corpus
    import opinion_guard

    # 평가는 실제 서비스 경로를 재사용하되 원문·도구 입력은 공개 API 응답에 섞지 않는다.
    started = perf_counter()
    if trace is not None:
        trace.clear()

    question = (question or "").strip()
    if not question:
        return {"answer": "질문을 입력해 주세요.", "sources": [], "tool_used": None,
                "disclaimer": DISCLAIMER, "blocked": []}

    # 1) 도구 라우팅 + 실행
    if trace is not None:
        trace["stage"] = "routing"
    user_context = "\n".join(str(h.get("content", ""))[:2000] for h in (history or [])[-6:] if h.get("role") == "user")
    routing_question = f"[이전 사용자 발언 — 현재 질문의 조건 보완용]\n{user_context}\n[현재 질문]\n{question}" if user_context else question
    route = _route_tool(routing_question, trace=trace)
    tool_result = _run_tool(route["tool"], route["params"], trace=trace) if route["tool"] != "none" else None
    if trace is not None:
        trace.update(route=route, tool_result=tool_result)

    # 2) RAG 검색
    retrieval_trace = {} if trace is not None else None
    if trace is not None:
        trace["stage"] = "retrieval"
    from backend.services.law_retrieval import retrieve_chat_evidence
    # 지시어가 있는 후속 질문은 사용자 발언으로 검색을 보완한다. 과거 AI 답변은 검색 근거가 아니다.
    followup = bool(re.match(r"^(그럼|그러면|그\s|그때|이\s*경우|이때|그것|그건|여기서|그렇다면|그러니까)", question))
    search_question = f"{user_context}\n{question}" if followup and user_context else question
    try:
        chunks = retrieve_chat_evidence(search_question, k=4, trace=retrieval_trace)
    except Exception as exc:
        chunks = []
        if trace is not None:
            trace["retrieval_error"] = type(exc).__name__
    if trace is not None:
        trace["chunks"] = chunks
        trace["retrieval"] = retrieval_trace

    # 3) 답변 생성
    context = _build_context(chunks, tool_result)
    allowed = opinion_guard.extract_numbers(context) | opinion_guard.extract_numbers(question)

    messages: list[tuple[str, str]] = [("system", ANSWER_PROMPT)]
    for h in (history or [])[-6:]:                      # 최근 3턴만 유지
        role = "human" if h.get("role") == "user" else "ai"
        messages.append((role, str(h.get("content", ""))[:1000]))
    messages.append(("human", f"{context}\n\n[질문]\n{question}"))

    answer, blocked = "", []
    if trace is not None:
        trace["stage"] = "generation"
    try:
        from model_factory import get_chat_llm
        if not chunks and not tool_result:
            raise ValueError("확인 가능한 근거 없음")
        res = get_chat_llm().invoke(messages)
        raw_answer = res.content.strip()
        if trace is not None:
            trace["raw_answer"] = raw_answer
        # 4) 수치 가드 — 근거·계산 결과에 없는 숫자가 든 문장 제거
        answer, blocked = opinion_guard.sanitize_text(raw_answer, allowed)
        if blocked:
            print(f"[chat] 수치 가드 차단: {blocked[:5]}")
    except Exception as e:
        if trace is not None:
            trace["generation_error"] = type(e).__name__
        print(f"[chat] 답변 생성 실패: {e}")

    # 5) 폴백 — LLM 실패·전량 차단 시 근거 자료 직접 제시
    if not answer:
        if trace is not None:
            trace["fallback"] = "tool" if tool_result else "corpus" if chunks else "no_evidence"
        if tool_result:
            answer = tool_result["summary"] + "\n(상세 설명 생성에 실패해 계산 결과만 안내드립니다.)"
        elif chunks:
            top = chunks[0]
            answer = (f"관련 자료를 안내드립니다.\n\n**{top['title']}** ({top['source']})\n{top['text']}")
        else:
            answer = "죄송합니다. 해당 질문에 대한 자료를 찾지 못했습니다. 질문을 조금 더 구체적으로 해주시겠어요?"

    if trace is not None:
        trace.update(elapsed_seconds=perf_counter() - started, blocked=blocked,
                     allowed_numbers=sorted(allowed), context=context, stage="completed")

    return {
        "answer":     answer,
        "sources":    [{key: c[key] for key in ("title", "source", "url", "effective_date", "collected_at", "origin") if key in c} for c in chunks],
        "tool_used":  tool_result["name"] if tool_result else None,
        "disclaimer": DISCLAIMER,
        "blocked":    blocked,
    }
