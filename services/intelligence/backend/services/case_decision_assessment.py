"""추가 외부 조회나 LLM 없이 같은 케이스 스냅샷의 다섯 판단 축을 정리한다."""
from __future__ import annotations

from datetime import datetime
from math import isfinite

from backend.services.analysis_freshness import analysis_freshness
from backend.services.candidate_funding import funding_issues
from backend.services.candidate_next_actions import candidate_next_actions
from schemas.decision_assessment import (
    CandidateDecisionAssessment, CaseDecisionAssessment, DecisionAxis, DecisionEvidence, DecisionMetrics,
)

TYPE_ALIASES = {
    "아파트": "apartment", "오피스텔": "officetel", "연립다세대": "row_house",
    "단독다가구": "detached", "상가": "non_residential", "사무실": "non_residential",
    "오피스": "non_residential", "공장": "industrial", "창고": "industrial", "토지": "land",
}


def _number(value, *, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < minimum:
        return None
    return value


def _evidence(key, label, value, source, *, as_of=None, unit="", usable=True, reference_url=None, provenance=None):
    return DecisionEvidence(key=key, label=label, value=value, source=source,
                            as_of=as_of, unit=unit, usable=usable, reference_url=reference_url, provenance=provenance)


def _analysis(candidate, kind, now):
    value = next((row for row in candidate.get("analyses", []) if row["analysis_type"] == kind), {})
    if value.get("status") == "completed":
        # 이전 결과의 상태 문자열만으로 만료되거나 기준일 없는 분석을 유효하다고 표시하지 않는다.
        try:
            analyzed = datetime.fromisoformat(value.get("analyzed_at") or "")
            if analyzed.tzinfo or analyzed > now:
                raise ValueError("기준 시각을 확인할 수 없는 분석")
            freshness = analysis_freshness(kind, value.get("analyzed_at"), value.get("expires_at"), now=now)
        except (TypeError, ValueError):
            freshness = {"status": "stale"}
        value = {**value, **freshness}
    return value


def _analysis_status(analysis):
    return {"completed": "confirmed", "stale": "stale", "failed": "error", "pending": "pending"}.get(analysis.get("status"), "unknown")


def _source_changed(candidate):
    return (candidate.get("source_status") or {}).get("status") in {"changed", "needs_confirmation", "missing"}


def _fit(case, candidate):
    profile = case.get("buyer_profile") or {}
    evidence, missing, failures = [], [], []
    configured = 0
    asking = _number(candidate.get("asking_price"), minimum=1)
    for field, label in (("address", "입력 주소"), ("category", "입력 물건 유형"), ("area_sqm", "입력 면적")):
        value = candidate.get(field)
        evidence.append(_evidence(field, label, value, "user_input", as_of=candidate.get("updated"), unit="㎡" if field == "area_sqm" else ""))
    budget = _number(case.get("budget_max"))
    if budget is not None:
        configured += 1
        evidence.append(_evidence("budget_max", "최대 예산", budget, "user_input", as_of=case.get("updated"), unit="원"))
        if asking is None:
            missing.append("양수 희망가")
        elif asking > budget:
            failures.append("희망가가 최대 예산을 초과합니다.")
    types = profile.get("property_types") or []
    if types:
        configured += 1
        category = candidate.get("category") or ""
        canonical = TYPE_ALIASES.get(category, category)
        evidence.append(_evidence("preferred_types", "희망 물건 유형", ", ".join(types), "user_input", as_of=case.get("updated")))
        if canonical not in set(TYPE_ALIASES.values()):
            missing.append("후보의 세부 물건 유형")
        elif canonical not in types:
            failures.append("후보의 물건 유형이 희망 유형과 다릅니다.")
    for lower, upper, field, title, unit in (
        ("min_area_sqm", "max_area_sqm", "area_sqm", "면적", "㎡"),
        ("min_build_year", "max_build_year", "build_year", "준공연도", "년"),
    ):
        lo, hi = profile.get(lower), profile.get(upper)
        if lo is None and hi is None:
            continue
        configured += 1
        evidence.append(_evidence(field + "_range", f"희망 {title}", f"{lo if lo is not None else '제한 없음'} ~ {hi if hi is not None else '제한 없음'}", "user_input", as_of=case.get("updated"), unit=unit))
        value = _number(candidate.get(field), minimum=1)
        if value is None:
            missing.append(f"후보 {title}")
        elif (lo is not None and value < lo) or (hi is not None and value > hi):
            failures.append(f"후보 {title}가 설정한 범위를 벗어납니다.")
    regions = case.get("regions") or []
    if regions or case.get("target_regions"):
        configured += 1
        code = candidate.get("legal_region_code")
        codes = [row["region_code"] for row in regions]
        if not code or not codes:
            missing.append("후보와 관심 지역의 법정동 코드 연결")
        else:
            def matches(target):
                prefix = target[:2] if target[2:] == "0" * 8 else target[:5] if target[5:] == "0" * 5 else target
                return code.startswith(prefix)
            if not any(matches(target) for target in codes):
                failures.append("후보 법정동이 저장한 관심 지역에 포함되지 않습니다.")
        evidence.append(_evidence("target_regions", "관심 지역", ", ".join(case.get("target_regions") or [row["region_name"] for row in regions]), "user_input", as_of=case.get("updated")))
    if not configured:
        missing.append("예산·면적·물건 유형 등 공통 매수 조건")
    state = "warning" if failures else "unknown" if missing else "confirmed"
    if _source_changed(candidate) and not failures:
        state = "stale"
        missing.append("최신 원본 매물 확인")
    return DecisionAxis(key="fit", label="적합성", status=state,
        headline="입력 조건 재검토" if failures else "조건 확인 필요" if missing else "입력한 조건 범위에 포함",
        explanation=" ".join(failures) or "사용자가 설정한 예산·면적·유형·관심 지역만 비교했습니다.",
        evidence=evidence, missing=missing,
        limitations=["통근·학군·소음·주차·생활 편의는 현재 자료로 평가하지 않았습니다. 임장과 별도 확인이 필요합니다."],
        review_target="profile", review_label="공통 매수 조건 확인")


def _price(candidate, analysis):
    summary = analysis.get("summary") or {}
    state = _analysis_status(analysis)
    asking = _number(candidate.get("asking_price"), minimum=1)
    valuation = summary.get("valuation") or {}
    limited = summary.get("result_kind") in {"conditional_scenario", "public_reference", "partial_reference", "withheld", "unsupported"} or bool(valuation and not valuation.get("comparison_eligible"))
    estimate = None if limited else _number(summary.get("estimated_value"), minimum=1)
    confidence = _number(summary.get("confidence"))
    count = _number(summary.get("comparable_count"), minimum=1)
    missing = list(valuation.get("next_actions") or [])
    if asking is None:
        missing.append("양수 희망가")
    if estimate is None:
        missing.append("AVM 추정가")
    if confidence is None or confidence < 0.5 or confidence > 1:
        missing.append("50% 이상으로 확인된 AVM 신뢰도")
    if count is None:
        missing.append("실거래 비교사례 수")
    if state == "confirmed" and missing:
        state = "unknown"
    if _source_changed(candidate) and state == "confirmed":
        state = "stale"
        missing.append("최신 원본 매물 확인")
    usable = state == "confirmed"
    gap = int(asking - estimate) if usable else None
    ratio = round(gap / estimate * 100, 1) if gap is not None else None
    if ratio is not None and ratio > 5:
        state = "warning"
    reference = f"/report/{analysis['reference_id']}" if analysis.get("reference_id") else None
    evidence = [
        _evidence("asking_price", "희망가", asking, "user_input", as_of=candidate.get("updated"), unit="원", usable=not _source_changed(candidate)),
        _evidence("estimated_value", "AVM 추정가", estimate, "calculation", as_of=analysis.get("analyzed_at"), unit="원", usable=usable, reference_url=reference),
        _evidence("confidence", "AVM 신뢰도", round(confidence * 100, 1) if confidence is not None and confidence <= 1 else None, "calculation", as_of=analysis.get("analyzed_at"), unit="%", usable=usable, reference_url=reference),
        _evidence("comparable_count", "실거래 비교사례", count, "calculation", as_of=analysis.get("analyzed_at"), unit="건", usable=usable, reference_url=reference),
        _evidence("match_level", "사례 매칭 수준", summary.get("match_level"), "calculation", as_of=analysis.get("analyzed_at"), usable=usable, reference_url=reference),
    ]
    if valuation:
        evidence.append(_evidence("valuation_policy", "평가 기준·결과 종류", f"{valuation['policy_version']} · {valuation['result_kind']}",
                                  "calculation", as_of=analysis.get("analyzed_at"), usable=usable, reference_url=reference, provenance=valuation))
    for index, comp in enumerate((summary.get("comparables") or [])[:10]):
        label = f"실거래 사례 {index + 1} · {comp.get('complex_name') or '이름 미확인'}"
        value = f"{comp.get('deal_date') or '거래일 미확인'} · {comp.get('area_m2') or '면적 미확인'}㎡ · 원거래 {comp.get('original_price') or comp.get('deal_price') or '가격 미확인'}원"
        evidence.append(_evidence(f"comparable_{index}", label, value, "official_data", as_of=comp.get("observed_at"),
                                  usable=usable, reference_url=reference, provenance=comp))
    if gap is not None:
        evidence.append(_evidence("price_gap", "희망가 − AVM 추정가", gap, "calculation", as_of=analysis.get("analyzed_at"), unit="원"))
    return DecisionAxis(key="price", label="가격성", status=state,
        headline=f"희망가가 AVM 추정가 대비 {ratio:+.1f}%" if ratio is not None else "유효한 가격 비교 필요",
        explanation="5% 초과 차이는 추가 확인을 위한 서비스 기준입니다. 매수 적정가격을 확정하는 기준은 아닙니다." if state == "warning" else "유효기간·신뢰도·비교사례가 확인된 AVM에 한해 희망가 차이를 계산합니다.",
        evidence=evidence, missing=missing,
        limitations=["AVM은 법정 감정평가가 아니며 호가와 현재 매물 존재를 독립 검증하지 않습니다.",
                     *(["수익 시나리오·필지 공개정보는 시장 시세로 비교하지 않습니다."] if limited else [])],
        review_target="appraisal", review_label="시세 분석·근거 확인"), gap, ratio


def _funding(candidate, analysis):
    summary = analysis.get("summary") or {}
    inputs = summary.get("inputs") or {}
    state = _analysis_status(analysis)
    missing = []
    issues = funding_issues(summary) if analysis else []
    if not analysis:
        missing.append("후보에 연결된 자금 분석")
    for field, label in (("loan_amount", "계산된 대출금"), ("required_cash", "필요 현금"),
                         ("monthly_payment", "첫 달 상환액"), ("cash_available", "매수 가능 현금"),
                         ("cash_shortfall", "현금 부족액")):
        if _number(summary.get(field)) is None:
            missing.append(label)
    homes = _number(inputs.get("owned_homes"), minimum=1)
    if homes is None or homes > 100 or homes != int(homes):
        missing.append("취득 후 주택 수 입력")
    if state == "confirmed":
        if _source_changed(candidate) or summary.get("purchase_price") != candidate.get("asking_price"):
            state = "stale"
            missing.append("현재 희망가로 계산한 자금 결과")
        elif summary.get("home_count_basis") != "after_purchase":
            state = "unknown"
            missing.append("취득 후 주택 수 기준 재확인")
        elif issues:
            state = "warning" if any(issue[3] == "warning" for issue in issues) else "unknown"
        if state == "confirmed" and missing:
            state = "unknown"
    missing.extend(issue[1] for issue in issues if issue[3] != "warning")
    usable = state in {"confirmed", "warning"}
    evidence = []
    for key, label in (("required_cash", "필요 현금"), ("cash_available", "매수 가용 현금"),
                       ("cash_shortfall", "현금 부족액"), ("monthly_payment", "첫 달 대출 상환액"),
                       ("monthly_payment_limit", "월 상환 한도")):
        evidence.append(_evidence(key, label, _number(summary.get(key)), "user_input" if key in {"cash_available", "monthly_payment_limit"} else "calculation", as_of=analysis.get("analyzed_at"), unit="원", usable=usable))
    evidence.append(_evidence("owned_homes", "취득 후 주택 수", inputs.get("owned_homes"), "user_input", as_of=analysis.get("analyzed_at"), unit="주택", usable=summary.get("home_count_basis") == "after_purchase"))
    for key, label, unit in (("annual_interest_rate", "가정 금리", "%"), ("loan_years", "대출 기간", "년"), ("annual_income", "연소득", "원")):
        evidence.append(_evidence(key, label, inputs.get(key), "user_input", as_of=analysis.get("analyzed_at"), unit=unit, usable=usable))
    finance = summary.get("finance_check") or {}
    for key, label in (("ltv", "계산 LTV"), ("dsr", "계산 DSR")):
        number = _number(finance.get(key))
        evidence.append(_evidence(key, label, round(number * 100, 1) if number is not None else None, "calculation", as_of=analysis.get("analyzed_at"), unit="%", usable=usable))
    return DecisionAxis(key="funding", label="자금성", status=state,
        headline="자금 조건 재검토" if state == "warning" else "입력한 현금·상환 기준 확인" if state == "confirmed" else "자금 조건 확인 필요",
        explanation="이 후보에 저장된 자금 분석이 없습니다. 조건을 입력해 계산하세요." if not analysis else " ".join(issue[2] for issue in issues) or "이 후보의 분석에 저장된 개별 금융 조건을 기준으로 계산했습니다.",
        evidence=evidence, missing=list(dict.fromkeys(missing)),
        limitations=["비상자금을 제외한 가용 현금과 첫 달 상환액을 비교합니다. 생활비·관리비는 별도이며 금융기관의 대출 승인이 아닙니다.", "현재 간이 세금·대출 모델의 결과입니다. 실제 조건은 별도 확인해야 합니다."],
        review_target="simulation", review_label="자금 조건 확인·재계산"), usable


def _risk(candidate, analysis):
    summary = analysis.get("summary") or {}
    state = _analysis_status(analysis)
    grade = summary.get("risk_grade")
    missing = []
    for key, label in (("registry_parsed", "등기부등본 판독 결과"), ("building_parsed", "건축물대장 판독 결과")):
        if summary.get(key) is not True:
            missing.append(label)
    if grade in {"danger", "caution"}:
        # 만료된 과거 결과의 위험 신호도 해결됐다는 근거가 생기기 전까지 남긴다.
        state = "warning"
    elif summary.get("analysis_status") == "failed":
        state = "error"
    elif state == "confirmed" and (grade != "safe" or missing):
        state = "unknown"
    evidence = [_evidence("risk_label", "업로드 문서 점검 결과", summary.get("risk_label"), "document", as_of=analysis.get("analyzed_at"), usable=_analysis_status(analysis) == "confirmed")]
    for key, label in (("registry_supplied", "등기부등본 제공"), ("building_supplied", "건축물대장 제공")):
        evidence.append(_evidence(key, label, summary.get(key), "document", as_of=analysis.get("analyzed_at")))
    for index, reason in enumerate(summary.get("reasons") or []):
        evidence.append(_evidence(f"risk_reason_{index}", "문서에서 확인한 신호", reason, "document", as_of=analysis.get("analyzed_at"), usable=_analysis_status(analysis) == "confirmed"))
    for index, item in enumerate((summary.get("evidence") or [])[:200]):
        evidence.append(_evidence(f"document_{index}", f"{'등기부' if item.get('document_type') == 'registry' else '건축물대장'} {item.get('page')}쪽 · {item.get('item')}",
                                  item.get("excerpt"), "document", as_of=item.get("issued_at"),
                                  usable=_analysis_status(analysis) == "confirmed" and (summary.get("subject_match") or {}).get("status") not in {"mismatch", "unknown"}, provenance=item))
    source = candidate.get("source_status") or {}
    current = source.get("current") or {}
    evidence.append(_evidence("listing_confirmation", "매물 원본 확인 상태", source.get("status", "미확인"), "user_input", as_of=current.get("confirmed_at"), usable=source.get("status") == "current"))
    if _source_changed(candidate):
        missing.append("원본 매물의 가격·주소·거래 가능 상태 재확인")
        if state == "confirmed":
            state = "stale"
    elif not candidate.get("source_listing_id") or source.get("status") != "current" or not current.get("confirmed_at"):
        missing.append("현재 거래 가능한 매물의 출처·확인 시각")
        if state == "confirmed":
            state = "unknown"
    return DecisionAxis(key="risk", label="위험성", status=state,
        headline="문서 위험 신호 확인 필요" if grade in {"danger", "caution"} else "업로드 문서 내 위험 신호 미검출" if state == "confirmed" else "문서·매물 확인 필요",
        explanation="업로드한 문서에서 탐지한 신호와 확인하지 못한 정보를 구분합니다. 문서가 없거나 판독하지 못한 경우 안전으로 표시하지 않습니다.",
        evidence=evidence, missing=missing,
        limitations=["문서 발급일과 실제 현재 권리관계의 일치, 소유자·현장 하자·공실·규제 전체는 검증하지 않았습니다.", *(summary.get("limitations") or [])],
        review_target="rights", review_label="권리 문서 확인·분석")


def assess_case_decision(case: dict, *, now: datetime | None = None) -> CaseDecisionAssessment:
    current = now or datetime.now()
    candidates = []
    for candidate in case.get("properties") or []:
        appraisal = _analysis(candidate, "appraisal", current)
        simulation = _analysis(candidate, "simulation", current)
        rights = _analysis(candidate, "rights", current)
        fit = _fit(case, candidate)
        price, gap, ratio = _price(candidate, appraisal)
        funding, usable_funding = _funding(candidate, simulation)
        risk = _risk(candidate, rights)
        axes = [fit, price, funding, risk]
        # 만료 여부를 다시 계산한 상태를 다음 행동에도 사용해 화면 간 안내가 엇갈리지 않게 한다.
        actions = candidate_next_actions(case, {**candidate, "analyses": [
            {**value, "analysis_type": kind} for kind, value in (
                ("appraisal", appraisal), ("simulation", simulation), ("rights", rights)
            ) if value
        ]})
        # 현재 비교에 쓸 수 없는 추정값으로 가격 차이 경고를 만들지 않는다.
        actions = [action for action in actions if action["code"] != "price_gap" or gap is not None]
        if candidate.get("status") != "rejected":
            # 근거가 부족한 항목도 기존 입력·분석 화면으로 돌아가 보완할 수 있게 한다.
            for axis, target in ((fit, "profile"), (price, "appraisal"), (funding, "simulation"), (risk, "rights")):
                if axis.status != "confirmed" and not any(action["target"] == target for action in actions):
                    actions.append({"code": f"decision_{axis.key}", "title": axis.review_label,
                        "reason": ", ".join(axis.missing) or axis.explanation, "target": target,
                        "priority": "warning" if axis.status == "warning" else "input", "checklist_id": None})
        priority = {"warning": 0, "input": 1, "normal": 2}
        actions = sorted(actions, key=lambda action: priority[action["priority"]])
        states = {axis.status for axis in axes}
        ready = not actions and states == {"confirmed"} and candidate.get("status") != "rejected"
        state = "confirmed" if ready else next((s for s in ("warning", "error", "stale", "pending", "unknown") if s in states), "unknown")
        if any(action["priority"] == "warning" for action in actions):
            state = "warning"
        selected = case.get("selected_property_id") == candidate["id"]
        execution = DecisionAxis(key="execution", label="실행성", status=state,
            headline="검토에서 제외한 후보" if candidate.get("status") == "rejected" else "등록된 검토 항목 확인" if ready else f"다음 확인 행동 {len(actions)}개",
            explanation="필수 확인 사항을 해결한 뒤 임장·은행 조회·서류 검토로 이어가세요. 후보 선택과 거래 안전의 확인은 별개입니다.",
            evidence=[_evidence("review_progress", "체크리스트 완료율", candidate.get("review_progress", 0), "workflow", as_of=candidate.get("updated"), unit="%"),
                      _evidence("selected", "사용자가 선택한 후보", selected, "user_input", as_of=case.get("decided_at"))],
            limitations=["체크리스트 완료율은 작업 기록이며 거래 안전도나 추천 점수가 아닙니다."],
            review_target="execution" if selected else "checklist", review_label="거래 준비 작업 확인" if selected else "후보 검토 항목 확인")
        if candidate.get("status") == "rejected":
            execution.status = "unknown"
        summary = simulation.get("summary") or {}
        candidates.append(CandidateDecisionAssessment(property_id=candidate["id"], name=candidate["name"], status=candidate.get("status", "reviewing"), review_ready=ready,
            metrics=DecisionMetrics(asking_price=_number(candidate.get("asking_price")), price_gap=gap, price_gap_ratio=ratio,
                required_cash=_number(summary.get("required_cash")) if usable_funding else None,
                monthly_payment=_number(summary.get("monthly_payment")) if usable_funding else None,
                cash_shortfall=_number(summary.get("cash_shortfall")) if usable_funding else None),
            identity=candidate.get("identity"), axes=[*axes, execution], next_actions=actions))
    return CaseDecisionAssessment(case_id=case["id"], evaluated_at=current.isoformat(sep=" ", timespec="seconds"), candidates=candidates)
