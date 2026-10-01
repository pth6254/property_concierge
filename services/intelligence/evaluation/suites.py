"""각 평가 영역의 실행과 판정. 오류와 폴백을 정답으로 숨기지 않는다."""
from __future__ import annotations

import hashlib
import json
from time import perf_counter

from evaluation.metrics import retrieval_metrics
from evaluation.schema import CalculatorCase, ChatCase, RagCase, Check, expected_checks


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def finish(case_id, suite, started, checks, details, metrics=None, review_required=False):
    return {"id": case_id, "suite": suite, "status": "pass" if all(c["passed"] for c in checks) else "fail",
            "elapsed_seconds": round(perf_counter() - started, 4), "checks": checks,
            "details": details, "metrics": metrics or {}, "review_required": review_required}


def calculator(case: CalculatorCase) -> dict:
    from backend import tax_rules
    started = perf_counter()
    value = getattr(tax_rules, case.function)(**case.inputs)
    actual = value if isinstance(value, dict) else {"value": value}
    checks = expected_checks(case.expected, actual, "output", case.tolerance)
    checks.append(Check(name="rules_as_of", passed=case.reference.as_of == tax_rules.TAX_RULES_AS_OF,
                        expected=case.reference.as_of, actual=tax_rules.TAX_RULES_AS_OF).model_dump())
    # 합계 검사는 고정 기대값 대조와 독립적으로 구성요소의 누락을 잡는다.
    parts = {"calc_annual_holding_tax": ["property_tax", "urban_tax", "edu_tax", "jongbu_tax", "nongteuk"],
             "calc_capital_gains_tax": ["national_tax", "local_tax"]}.get(case.function)
    if parts:
        key = "total" if case.function == "calc_annual_holding_tax" else "tax"
        checks += expected_checks({key: sum(actual[p] for p in parts)}, actual, "sum")
    return finish(case.id, "calculator", started, checks, {"inputs": case.inputs, "outputs": actual,
                  "reference": case.reference.model_dump(), "function": case.function})


def rag(case: RagCase, *, live: bool, k: int) -> dict:
    from backend import chat_corpus
    started = perf_counter()
    if live:
        retrieval_trace = {}
        if case.retrieval_backend == "service":
            from backend.services.law_retrieval import retrieve_chat_evidence
            chunks = retrieve_chat_evidence(case.question, k=k, trace=retrieval_trace)
        else:
            chunks = chat_corpus.search(case.question, k=k, trace=retrieval_trace)
        mode = retrieval_trace["mode"]
        corpus_hash = retrieval_trace.get("corpus_sha256")
    else:
        if case.relevant_articles or case.require_official_law:
            raise ValueError("공식 조문 검색 평가는 --live가 필요합니다")
        # 서비스의 키워드 점수를 동일하게 사용하되 DB를 만들거나 메모리 DB 폴백을 도입하지 않는다.
        ranked = [dict(chunk, score=chat_corpus._keyword_score(case.question, chunk["title"] + " " + chunk["text"]))
                  for chunk in chat_corpus.SEED_CHUNKS]
        chunks = sorted((c for c in ranked if c["score"] > 0), key=lambda c: c["score"], reverse=True)[:k]
        mode = "seed_keyword_only"
        retrieval_trace = {}
        corpus_hash = fingerprint(chat_corpus.SEED_CHUNKS)
    titles = [f"{chunk.get('law_id')}:{chunk.get('article')}" for chunk in chunks] if case.relevant_articles else [chunk["title"] for chunk in chunks]
    gold = [f"{item.law_id}:{item.article}" for item in case.relevant_articles] if case.relevant_articles else case.relevant_titles
    metrics = retrieval_metrics(titles, gold, k)
    check = Check(name="no_results" if case.expect_no_results else "recall_threshold",
                  passed=not chunks if case.expect_no_results else metrics["recall_at_k"] >= case.min_recall,
                  expected=0 if case.expect_no_results else case.min_recall,
                  actual=len(chunks) if case.expect_no_results else metrics["recall_at_k"])
    checks = [check.model_dump()]
    if case.require_official_law:
        checks.append(Check(name="official_law_path", passed=retrieval_trace.get("mode") == "pgvector_law", actual=retrieval_trace.get("mode")).model_dump())
    return finish(case.id, "rag", started, checks, {"question": case.question,
                  "relevant_articles": [item.model_dump() for item in case.relevant_articles],
                  "reference": case.reference.model_dump() if case.reference else None,
                  "relevant_titles": case.relevant_titles, "retrieved": chunks, "mode": mode,
                  "corpus_sha256": corpus_hash, "retrieval": retrieval_trace}, metrics)


class _ProgressTrace(dict):
    """중단된 호출도 마지막 단계가 남도록 내부 추적 변경을 실행기에 전달한다."""
    def __init__(self, notify):
        super().__init__()
        self.notify = notify

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.notify(dict(self))

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self.notify(dict(self))


def chat(case: ChatCase, *, answer_fn=None, on_progress=None) -> dict:
    if answer_fn is None:
        from backend.services.chat_service import answer_question
        answer_fn = answer_question
    started = perf_counter()
    history, turns, checks = [], [], []
    for index, turn in enumerate(case.turns, 1):
        def notify(trace_value):
            if on_progress:
                on_progress({"turns": turns, "active_turn": index, "question": turn.question, "trace": trace_value})
        trace = _ProgressTrace(notify)
        notify({"stage": "starting"})
        output = answer_fn(turn.question, history, trace=trace)
        answer = output.get("answer", "")
        route = trace.get("route") or {}
        tool_result = trace.get("tool_result") or {}
        prefix = f"turn_{index}"
        turn_checks = expected_checks({"tool": turn.expected_tool}, route, prefix)
        turn_checks += expected_checks(turn.expected_params, route.get("params") or {}, f"{prefix}.params")
        turn_checks += expected_checks(turn.expected_outputs, tool_result.get("outputs") or {}, f"{prefix}.outputs")
        turn_checks += [Check(name=f"{prefix}.answer_present", passed=bool(answer.strip())).model_dump(),
                        Check(name=f"{prefix}.pipeline_errors", passed=not any(trace.get(key) for key in
                              ("routing_error", "tool_error", "generation_error"))).model_dump(),
                        Check(name=f"{prefix}.fallback", passed=turn.allow_fallback or not trace.get("fallback"),
                              expected=turn.allow_fallback, actual=trace.get("fallback")).model_dump()]
        if turn.expected_tool != "none":
            turn_checks.append(Check(name=f"{prefix}.tool_executed", passed=bool(tool_result)).model_dump())
        if turn.relevant_titles:
            titles = {c["title"] for c in trace.get("chunks", [])}
            turn_checks.append(Check(name=f"{prefix}.sources", passed=set(turn.relevant_titles) <= titles,
                                     expected=turn.relevant_titles, actual=sorted(titles)).model_dump())
        if turn.answer_contains_any:
            turn_checks.append(Check(name=f"{prefix}.answer_keywords", passed=any(word in answer for word in turn.answer_contains_any),
                                     expected=turn.answer_contains_any).model_dump())
        if turn.answer_required_numbers:
            from backend.opinion_guard import extract_numbers
            numbers = extract_numbers(answer)
            turn_checks.append(Check(name=f"{prefix}.answer_numbers", passed=all(number in numbers for number in turn.answer_required_numbers),
                                     expected=turn.answer_required_numbers, actual=sorted(numbers)).model_dump())
        for phrase in turn.answer_forbids:
            turn_checks.append(Check(name=f"{prefix}.forbidden_phrase", passed=phrase not in answer,
                                     expected=f"포함 금지: {phrase}").model_dump())
        turns.append({"turn": index, "question": turn.question, "answer": answer, "trace": dict(trace),
                      "checks": turn_checks, "review_focus": turn.review_focus})
        checks.extend(turn_checks)
        notify(dict(trace))
        # 매 턴 정답 답변을 주입하지 않고 실제 응답을 다음 턴에 전달한다.
        history.extend([{"role": "user", "content": turn.question}, {"role": "assistant", "content": answer}])
        history = history[-6:]
    return finish(case.id, "chat", started, checks, {"turns": turns}, metrics={
        "turn_count": len(turns), "fallback_turns": sum(bool(t["trace"].get("fallback")) for t in turns),
        "guard_blocked_items": sum(len(t["trace"].get("blocked", [])) for t in turns),
    }, review_required=True)
