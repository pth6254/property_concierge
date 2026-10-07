"""자료·평가 범위에 따라 실행을 제한한다. 가격 생성이나 LLM 호출은 하지 않는다."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
import calendar
import hashlib
import json
import math

from schemas.valuation import ValuationAssessment, ValuationContext, ValuationSubject

KINDS_WITHOUT_MARKET_PRICE = {"conditional_scenario", "public_reference", "partial_reference", "withheld", "unsupported"}
DETAILS = {"아파트": "apartment", "오피스텔": "officetel", "연립다세대": "row_house", "빌라": "row_house",
           "연립": "row_house", "다세대": "row_house", "단독": "detached", "단독주택": "detached", "다가구": "multi_household",
           "단독다가구": "detached_unspecified", "상가": "commercial", "사무실": "office", "토지": "land", "공장": "factory", "창고": "warehouse"}
CATEGORIES = {"apartment": "주거용", "officetel": "주거용", "row_house": "주거용", "detached": "주거용",
              "multi_household": "주거용", "detached_unspecified": "주거용", "commercial": "상업용", "office": "업무용",
              "land": "토지", "factory": "산업용", "warehouse": "산업용"}


def _positive(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
    except (ValueError, TypeError):
        return False


def subject(state):
    raw = state.get("raw_inputs") or {}
    intent = state.get("intent")
    category = raw.get("property_category") or getattr(intent, "category", "")
    detail = raw.get("property_detail") or getattr(intent, "category_detail", "") or {"상업용": "상가", "업무용": "사무실", "토지": "토지"}.get(category, "")
    subtype = DETAILS.get(detail, detail if detail in CATEGORIES else "unknown")
    area = raw.get("area_sqm")
    if area is None and getattr(intent, "area_min", None) == getattr(intent, "area_max", None):
        area = getattr(intent, "area_min", None)
    day = raw.get("appraisal_date") or getattr(intent, "appraisal_date", "")
    try:
        as_of = datetime.strptime(day, "%Y%m%d").date() if day else datetime.now(ZoneInfo("Asia/Seoul")).date()
    except ValueError:
        as_of = None
    # 기존 API의 area_sqm은 전용면적 계약이었다. 명시된 미확인/공급면적은 절대 덮어쓰지 않는다.
    context = raw.get("valuation_context")
    if context is None:
        income = raw.get("income_valuation") or {}
        context = {"scope": income.get("valuation_unit") or ("single_unit" if subtype in {"apartment", "officetel", "row_house"} else "single_parcel" if subtype == "land" else "unknown"),
                   "area_basis": "exclusive" if area and subtype in {"apartment", "officetel", "row_house"} else "unknown",
                   "transaction_type": {"매매": "sale", "전세": "jeonse", "월세": "rent"}.get(getattr(intent, "transaction_type", "") or "매매", "unknown")}
    return ValuationSubject(**ValuationContext.model_validate(context).model_dump(), category=category, subtype=subtype,
        address=raw.get("address") or getattr(intent, "location_normalized", ""), building_name=state.get("building_name") or "",
        area_sqm=float(area) if _positive(area) else None, as_of_date=as_of.isoformat() if as_of else "",
        purpose=state.get("appraisal_purpose") or "매매")


def plan(state):
    target = subject(state)
    raw = state.get("raw_inputs") or {}
    fingerprint = hashlib.sha256(json.dumps({"subject": target.model_dump(), "income": raw.get("income_valuation")},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    out = {"subject": target.model_dump(), "input_fingerprint": fingerprint, "result_kind": "withheld",
           "comparison_eligible": False, "checks": [], "methods": [], "next_actions": [],
           "limitations": ["사용자 입력 동·호는 개별 호실 확인을 의미하지 않습니다."]}
    def check(code, ok, message, status="missing"):
        confirmed = {"property_type": f"{target.category} / {target.subtype}", "address": target.address,
            "as_of_date": target.as_of_date, "price_basis": "매매 참고 분석", "area_sqm": f"{target.area_sqm}㎡",
            "area_basis": "전용면적 입력", "scope": f"평가 범위: {target.scope}",
            "building_name": target.building_name, "income_inputs": "임대료 시나리오 입력 수신"}
        out["checks"].append({"code": code, "status": "available" if ok else status, "message": confirmed.get(code, message) if ok else message, "source": "user_input", "reference_date": target.as_of_date or None})
        if not ok: out["next_actions"].append(message)
        return ok
    known = check("property_type", CATEGORIES.get(target.subtype) == target.category, "부동산 종류와 세부 유형을 확인해주세요", "conflict")
    check("address", bool(target.address.strip()), "정확한 주소를 입력해주세요")
    check("as_of_date", bool(target.as_of_date) and target.as_of_date <= datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(), "현재 또는 과거의 유효한 기준일을 선택해주세요", "conflict")
    supported_purpose = target.purpose in {"매매", "임의"} and target.transaction_type == "sale"
    check("price_basis", supported_purpose, "현재 정책은 매매 참고 분석입니다. 임대·담보·과세 등 다른 목적의 가격은 별도 검토해주세요", "conflict")
    method = "sales_comparison"
    if not known or not supported_purpose or target.category == "산업용":
        out["result_kind"] = "unsupported"
        if target.category == "산업용": out["next_actions"].append("공장·창고의 토지·건물·설비 범위와 평가 기준은 후속 지원 대상입니다.")
    elif target.category == "주거용":
        check("area_sqm", target.area_sqm is not None, "분석 대상 면적을 입력해주세요")
        check("area_basis", target.area_basis == "exclusive", "전용면적과 면적 기준을 확인해주세요", "conflict")
        check("scope", target.scope == "single_unit", "개별 호실과 건물 전체의 평가 범위를 구분해주세요", "conflict")
        if target.subtype != "apartment":
            out["next_actions"].append("이 유형의 거래 범위·토지 지분·임대 자료와 별도 평가 기준을 보완해야 합니다. 아파트 모델을 대신 적용하지 않습니다.")
        else:
            check("building_name", bool(target.building_name.strip()), "동일 단지 비교를 위한 정확한 단지명을 입력해주세요")
    elif target.category in {"상업용", "업무용"}:
        method = "income_scenario"
        income = raw.get("income_valuation") or {}
        check("income_inputs", bool(income), "현재 월세·운영비·환원율 가정을 입력해주세요")
        check("scope", bool(income) and target.scope == income.get("valuation_unit"), "평가 범위와 임대료의 호실·건물 범위를 일치시켜주세요", "conflict")
    else:
        method = "land_public_data"
        check("scope", target.scope == "single_parcel", "토지 공개정보는 한 필지씩 조회합니다", "conflict")
    allowed = not out["next_actions"]
    out["methods"] = [
        {"method": method, "status": "selected" if allowed else "blocked", "reason": "입력 조건 확인. 실행 후 수집 근거를 추가 검증합니다." if allowed else "필수 입력 또는 적용 범위 확인 필요"},
        {"method": "catboost", "status": "blocked", "reason": "오프라인 후보 모델로 운영 기준을 통과하지 않았습니다. 거래 부족 시 자동 대체하지 않습니다.", "engine_version": "apartment-catboost-v1"},
    ]
    return ValuationAssessment.model_validate(out).model_dump(mode="json")


def blocked_result(state, assessment):
    target = assessment["subject"]
    return {**state, "analysis_result": {"support_version": "valuation-policy-1.0", "valuation": assessment,
        "result_kind": assessment["result_kind"], "estimated_value": None, "value_min": None, "value_max": None,
        "value_unit": "원", "agent_name": target["category"] or "유형 확인 필요", "address": target["address"],
        "as_of_date": target["as_of_date"], "valuation_method": "평가 자료·지원 범위 확인",
        "limitations": assessment["next_actions"] + assessment["limitations"]}, "error": ""}


def allowed(assessment):
    return any(m["status"] == "selected" for m in assessment["methods"])


def eligible_comparables(state, price_data):
    """PC-AVM-1.0의 동일 단지·6개월·면적 ±10% 기준. 제외 자료로 가격을 계산하지 않는다."""
    from backend.comparable_matching import comparable_match_level
    assessment = state["valuation_plan"]
    target = assessment["subject"]
    as_of = date.fromisoformat(target["as_of_date"])
    month_index = as_of.year * 12 + as_of.month - 1 - 6
    year, month = month_index // 12, month_index % 12 + 1
    start = date(year, month, min(as_of.day, calendar.monthrange(year, month)[1]))
    selected, seen = [], set()
    for row in price_data.get("samples") or []:
        try:
            day = date(int(row["deal_year"]), int(row["deal_month"]), int(row["deal_day"]))
            match = comparable_match_level(row, matched_complex=price_data.get("apt_name_matched", ""),
                target_dong=price_data.get("target_dong", ""), target_sigungu_code=price_data.get("target_sigungu_code", ""))
            if (match != "same_complex" or not start <= day <= as_of or not _positive(row.get("price"))
                    or not _positive(row.get("area_sqm")) or abs(float(row["area_sqm"]) / target["area_sqm"] - 1) > .100001
                    or any(str(row.get(key, "")).strip().lower() in {"true", "1", "y", "yes"} for key in ("cancelled", "is_cancelled"))
                    or row.get("cancel_date")):
                continue
            identity = row.get("transaction_ref") or (day.isoformat(), row.get("apt_name"), row.get("floor"), row.get("area_sqm"), row["price"])
            if identity in seen: continue
            seen.add(identity); selected.append(row)
        except (ValueError, KeyError, TypeError, ZeroDivisionError):
            continue
    ok = len(selected) >= 5
    assessment["checks"].append({"code": "comparables", "status": "available" if ok else "missing", "source": "official_data",
        "message": f"최근 6개월·동일 단지·전용면적 ±10%의 중복 제외 비교사례 {len(selected)}건 / 산출 기준 5건",
        "reference_date": target["as_of_date"], "observed_at": None})
    if not ok:
        assessment["next_actions"].append("동일 단지·유사 전용면적의 최근 거래 근거를 추가 확인해주세요. 구 평균이나 ML로 대체하지 않습니다.")
        assessment["methods"][0].update(status="blocked", reason="유효 비교사례 부족")
        return None
    return {**price_data, "samples": selected, "count": len(selected),
            "avg": round(sum(s["price"] for s in selected) / len(selected)),
            "min": min(s["price"] for s in selected), "max": max(s["price"] for s in selected),
            "per_sqm_avg": round(sum(s["price"] / s["area_sqm"] for s in selected) / len(selected))}


def finalize(state):
    analysis = state.get("analysis_result") or {}
    assessment = state.get("valuation_plan") or plan(state)
    if analysis.get("valuation"): return state
    if not allowed(assessment): return blocked_result(state, assessment)
    kind = analysis.get("result_kind", "market_reference")
    if kind == "market_reference":
        if not _positive(analysis.get("estimated_value")) or not any(c["code"] == "comparables" and c["status"] == "available" for c in assessment["checks"]):
            assessment["next_actions"].append("검증된 비교 근거와 양수 추정가격을 확인하지 못했습니다.")
            return blocked_result(state, assessment)
        assessment["interval_basis"] = "heuristic_range_not_prediction_interval"
        assessment["methods"][0].update(reason="동일 단지·최근 6개월·전용면적 ±10%의 유효 거래 5건 이상을 사용했습니다.", engine_version="residential-comparison-rules-v1")
        assessment["limitations"].append("가격 범위는 기존 규칙의 참고 구간이며 통계적으로 보정된 예측구간이 아닙니다.")
        assessment["subject"]["identity_level"] = "complex_area"
    land = analysis.get("land_information")
    if land:
        assessment["subject"]["identity_level"] = "parcel"
        for source in land["sources"]:
            assessment["checks"].append({"code": source["id"], "status": "available" if source["status"] == "found" else "missing",
                "message": source["title"] + " · " + source["status"], "source": "official_data",
                "reference_date": source.get("reference_year"), "observed_at": source.get("checked_at")})
        if land["status"] != "found": assessment["next_actions"].append("조회하지 못한 토지 자료와 기준연도를 확인해주세요.")
    scenario = analysis.get("income_scenario")
    if scenario:
        assessment["methods"][0]["engine_version"] = scenario["calculation_version"]
        assessment["interval_basis"] = "user_assumption_scenarios"
    assessment.update(result_kind=kind, comparison_eligible=kind == "market_reference")
    assessment["limitations"] += analysis.get("limitations", [])
    if kind == "withheld":
        assessment["next_actions"] += analysis.get("limitations", [])
        assessment["methods"][0].update(status="blocked", reason="계산 또는 자료 조회 조건 부족")
    assessment = ValuationAssessment.model_validate(assessment).model_dump(mode="json")
    return {**state, "analysis_result": {**analysis, "valuation": assessment, "result_kind": kind}}
