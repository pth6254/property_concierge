"""핵심 매수 판단의 근거·상태 변화와 가격 추정 오차를 평가한다."""
from __future__ import annotations

from statistics import mean
from time import perf_counter

from evaluation.schema import Check, expected_checks
from evaluation.suites import finish, fingerprint
from evaluation.decision_schema import DecisionCase, AvmCase, IntentCase


def decision(case: DecisionCase) -> dict:
    from backend.services.analysis_freshness import analysis_freshness
    from backend.services.case_comparison_service import compare_case_candidates
    from backend.services.candidate_next_actions import candidate_next_actions
    from backend.services.execution_plan_service import TASK_TEMPLATES, due_date_for, readiness_summary
    started = perf_counter()
    checks, snapshots = [], []
    for index, step in enumerate(case.steps, 1):
        prefix = f"step_{index}"
        candidates = []
        for source in step.candidates:
            candidate = source.model_dump(mode="json")
            for analysis in candidate["analyses"]:
                analysis.update(analysis_freshness(analysis["analysis_type"], analysis["analyzed_at"],
                                                  analysis["expires_at"], analysis["status"], now=step.as_of))
            candidate["review_progress"] = round(sum(c["status"] == "done" for c in candidate["checklist"]) / len(candidate["checklist"]) * 100)
            candidates.append(candidate)
        workspace = {"id": 1, "title": case.id, "budget_max": step.budget_max_won,
                     "properties": candidates, "selected_property_id": step.selected_property_id}
        comparison = compare_case_candidates(workspace, now=step.as_of)
        rows = {str(row["property_id"]): row for row in comparison["rows"]}
        actions = {str(c["id"]): candidate_next_actions(workspace, c) for c in candidates}
        actual_ready = sorted(row["property_id"] for row in rows.values() if row["decision_ready"])
        checks += expected_checks({"ready_ids": sorted(step.expected.ready_ids)}, {"ready_ids": actual_ready}, prefix)
        for candidate_id, required in step.expected.required_actions.items():
            actual = {a["code"] for a in actions[candidate_id]}
            for code in required:
                checks.append(Check(name=f"{prefix}.{candidate_id}.required.{code}", passed=code in actual,
                                    expected=code, actual=sorted(actual)).model_dump())
        for candidate_id, forbidden in step.expected.forbidden_actions.items():
            actual = {a["code"] for a in actions[candidate_id]}
            for code in forbidden:
                checks.append(Check(name=f"{prefix}.{candidate_id}.forbidden.{code}", passed=code not in actual,
                                    expected=f"제외: {code}", actual=sorted(actual)).model_dump())
        for candidate_id, first in step.expected.first_actions.items():
            actual = actions[candidate_id][0]["code"] if actions[candidate_id] else None
            checks += expected_checks({"first_action": first}, {"first_action": actual}, f"{prefix}.{candidate_id}")
        for candidate_id, values in step.expected.comparison_values.items():
            checks += expected_checks(values, rows[candidate_id], f"{prefix}.{candidate_id}.comparison")
        tasks = []
        statuses = {t.template_key: t.status for t in step.execution_tasks}
        known = {t[0] for t in TASK_TEMPLATES}
        if not (set(statuses) | set(step.expected.due_dates)) <= known:
            raise ValueError("실행 작업 키 오타")
        if step.selected_property_id is not None:
            for task_id, (key, phase, title, actor, anchor, offset, required) in enumerate(TASK_TEMPLATES, 1):
                tasks.append({"id": task_id, "template_key": key, "phase": phase, "title": title, "actor_type": actor,
                              "required": required, "status": statuses.get(key, "scheduled"),
                              "due_date": due_date_for(anchor, offset, step.contract_date.isoformat() if step.contract_date else None,
                                                       step.closing_date.isoformat() if step.closing_date else None)})
        summary = readiness_summary(tasks, today=step.as_of.date())
        checks += expected_checks(step.expected.execution_summary, summary, f"{prefix}.execution")
        checks += expected_checks(step.expected.due_dates, {t["template_key"]: t["due_date"] for t in tasks}, f"{prefix}.due_dates")
        snapshots.append({"name": step.name, "as_of": step.as_of.isoformat(), "comparison": comparison,
                          "next_actions": actions, "execution": {"tasks": tasks, "summary": summary}})
    return finish(case.id, "decision", started, checks, {"rationale": case.rationale, "steps": snapshots,
        "scope": "가상 입력 상태 재생: 최신성·비교·다음 행동·실행 일정의 실제 서비스 규칙. DB 저장·UI·매수 성과 평가는 아님."},
        metrics={"steps": len(snapshots), "checks": len(checks), "failed_checks": sum(not c["passed"] for c in checks)})


def avm(case: AvmCase, *, live: bool) -> dict:
    from backend.tools import backtest_avm
    started = perf_counter()
    if live:
        store = backtest_avm.transaction_store
        months = {ym: store.get_month(backtest_avm.ENDPOINT, backtest_avm.CATEGORY, case.lawd_cd, ym, ignore_ttl=True) or []
                  for ym in store.list_ingested_months(backtest_avm.ENDPOINT, backtest_avm.CATEGORY, case.lawd_cd)}
        source = "stored_transactions"
    else:
        months = {ym: [{"apt_name": deal.apt_name, "dong": deal.dong, "area_sqm": deal.area_sqm,
                        "price": deal.price_manwon, "per_sqm": deal.price_manwon / deal.area_sqm} for deal in deals]
                  for ym, deals in case.months.items()}
        source = "synthetic_fixture"
    rate = backtest_avm._TIME_ADJ_MONTHLY_RATE.get(backtest_avm.CATEGORY, 0.002)
    result = backtest_avm.evaluate_months(months, region_name=case.region_name, target_months=case.target_months,
        window=case.window, time_factor=lambda before, after: backtest_avm._time_adj_factor(backtest_avm._months_diff(before, after), rate))
    samples = result["cases"]
    mape = mean(c["ape"] for c in samples) if samples else None
    checks = [Check(name="sample_count", passed=len(samples) >= case.min_samples, expected=case.min_samples, actual=len(samples)).model_dump(),
              Check(name="coverage", passed=result["coverage"] >= case.min_coverage, expected=case.min_coverage, actual=result["coverage"]).model_dump(),
              Check(name="mape", passed=mape is not None and mape <= case.max_mape, expected=case.max_mape, actual=mape).model_dump(),
              Check(name="no_future_comparables", passed=all(all(ym < c["target_ym"] for ym in c["prior_months"]) for c in samples)).model_dump()]
    return finish(case.id, "avm", started, checks, {"source": source, "data_sha256": fingerprint(months),
        "method": "기존 backtest_avm 축약 매칭·평균단가 추정, 근사 시점수정. 전체 실서비스 AVM과 동일하지 않음.",
        "region": case.region_name, "lawd_cd": case.lawd_cd, "time_adjustment": "approximate_monthly_rate",
        "monthly_rate": rate, "coverage": result, "by_match_and_count": backtest_avm.summarize(samples)["buckets"] if samples else {}},
        metrics={"sample_count": len(samples), "coverage": result["coverage"], "unestimated": result["unestimated"],
                 "mape": mape, "hit10": mean(c["ape"] <= 0.1 for c in samples) if samples else None})


def intent(case: IntentCase, *, on_progress=None) -> dict:
    from backend.graphs.concierge_graph import decide_node
    from backend.concierge.tools import TOOL_REGISTRY
    started = perf_counter()
    previous, checks, turns = {}, [], []
    for index, turn in enumerate(case.turns, 1):
        if on_progress:
            on_progress({"active_turn": index, "stage": "concierge_routing", "intent_turns": turns})
        state = decide_node({"message": turn.message, "previous_criteria": previous})
        decision_value = state["decision"]
        criteria = decision_value.criteria.model_dump(mode="json")
        prefix = f"turn_{index}"
        checks += expected_checks({"intent": turn.expected_intent}, {"intent": decision_value.intent.value}, prefix)
        checks += expected_checks(turn.expected_criteria, criteria, f"{prefix}.criteria")
        checks.append(Check(name=f"{prefix}.routing_success", passed=not state.get("routing_error"), actual=state.get("routing_error")).model_dump())
        definition = TOOL_REGISTRY[decision_value.intent]
        turns.append({"message": turn.message, "criteria": criteria, "intent": decision_value.intent.value,
                      "tool_enabled": definition.enabled, "routing_error": state.get("routing_error")})
        previous = criteria
    result = finish(case.id, "intent", started, checks, {"intent_turns": turns,
        "scope": "실제 조건·의도 추출만 평가. 도구 실행·주소 확정·Redis 대화 저장은 포함하지 않음."},
        metrics={"turns": len(turns), "unconnected_tools": sum(not t["tool_enabled"] for t in turns)})
    if any(t["routing_error"] for t in turns):
        result["status"] = "error"
    return result
