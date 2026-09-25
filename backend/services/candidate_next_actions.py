"""저장된 후보 정보로 다음 확인 행동을 정한다. 매수 안전성을 판정하지 않는다."""
from __future__ import annotations
from backend.services.candidate_funding import funding_issues


def candidate_next_actions(case: dict, candidate: dict) -> list[dict]:
    if candidate.get("status") == "rejected":
        return []
    actions = []

    def add(code, title, reason, target, priority="normal", checklist_id=None):
        actions.append(dict(code=code, title=title, reason=reason, target=target,
                            priority=priority, checklist_id=checklist_id))

    asking = candidate.get("asking_price")
    source_status = candidate.get("source_status") or {}
    if source_status.get("status") in {"changed", "needs_confirmation", "missing"}:
        add("source_listing", "원본 매물 재확인", "저장 당시의 매물 정보와 현재 원본 또는 확인 상태가 다릅니다. 가격·거래 가능 여부를 다시 확인하세요.", "price", "warning")
    budget = case.get("budget_max")
    if asking is None:
        add("asking_price", "희망가 입력", "예산과 추정가를 비교할 가격이 없습니다.", "price", "input")
    elif budget is not None and asking > budget:
        add("budget", "예산 초과 확인", "희망가가 케이스 최대 예산을 초과합니다. 자금 조달 조건을 확인하세요.", "simulation", "warning")

    analyses = {item["analysis_type"]: item for item in candidate.get("analyses", [])}
    unresolved = set()
    for kind, label in (("appraisal", "시세"), ("simulation", "자금"), ("rights", "권리")):
        analysis = analyses.get(kind)
        status = (analysis or {}).get("status")
        if status != "completed":
            unresolved.add(kind)
            if status == "stale":
                title, reason = f"{label}분석 갱신", "분석 유효기간이 지났습니다. 최신 조건으로 다시 확인하세요."
            elif status == "failed":
                title, reason = f"{label}분석 재시도", "이전 분석이 실패해 확인 가능한 결과가 없습니다."
            elif status == "pending":
                title, reason = f"{label}분석 진행 확인", "분석이 아직 완료되지 않았습니다."
            else:
                title = {"appraisal": "시세분석 실행", "simulation": "자금 조건 입력", "rights": "권리서류 분석"}[kind]
                reason = "후보에 연결된 분석 결과가 없습니다."
            add(kind, title, reason, kind)
        if kind == "rights" and analysis:
            grade = (analysis.get("summary") or {}).get("risk_grade")
            if grade != "safe":
                unresolved.add(kind)
                add("rights_risk", "권리 위험 확인", "권리 위험 또는 미확인 결과가 있습니다. 분석 내용과 전문가 확인이 필요합니다.", kind, "warning")

    appraisal = analyses.get("appraisal") or {}
    confidence = (appraisal.get("summary") or {}).get("confidence")
    if appraisal.get("status") == "completed" and isinstance(confidence, (int, float)) and confidence < 0.5:
        add("appraisal_confidence", "시세추정 근거 확인", "AVM 추정의 ±10% 적중 신뢰도가 낮습니다. 비교사례와 추정 근거를 확인하세요.", "appraisal", "warning")
    simulation = analyses.get("simulation") or {}
    if simulation.get("status") == "completed":
        for code, title, reason, priority in funding_issues(simulation.get("summary") or {}):
            unresolved.add("simulation")
            add(code, title, reason, "simulation", priority)
    simulated_price = (simulation.get("summary") or {}).get("purchase_price")
    if simulation.get("status") == "completed" and asking is not None and simulated_price is not None and asking != simulated_price:
        unresolved.add("simulation")
        add("simulation_price", "변경된 가격으로 자금 조건 확인", "자금분석의 매수가와 현재 희망가가 다릅니다. 적용할 가격을 확인하세요.", "simulation", "warning")
    estimated = (appraisal.get("summary") or {}).get("estimated_value")
    if appraisal.get("status") == "completed" and (confidence is None or confidence >= 0.5) and isinstance(estimated, (int, float)) and estimated > 0 and asking is not None and asking > estimated * 1.05:
        add("price_gap", "추정가 대비 희망가 확인", "희망가가 AVM 추정가보다 5% 넘게 높습니다. 가격 차이의 근거를 확인하세요.", "appraisal", "warning")

    category_analysis = {"price": "appraisal", "funding": "simulation", "rights": "rights"}
    for check in candidate.get("checklist", []):
        if check.get("status") == "done":
            continue
        # 분석 누락과 동일한 할 일을 중복 안내하지 않되, 별도로 기록한 경고는 보존한다.
        warning = check.get("status") in {"warning", "blocked"}
        if not warning and category_analysis.get(check.get("category")) in unresolved:
            continue
        add(f"checklist_{check['id']}", check["title"],
            check.get("evidence") or "실제 확인 후 아래 검토 항목의 상태를 갱신하세요.",
            "checklist", "warning" if warning else "normal", check["id"])

    order = {"warning": 0, "input": 1, "normal": 2}
    return sorted(actions, key=lambda action: order[action["priority"]])
