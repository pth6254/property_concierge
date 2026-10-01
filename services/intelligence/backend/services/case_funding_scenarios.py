"""한 케이스의 후보를 동일 금융 조건으로 재계산한다. 저장된 분석은 변경하지 않는다."""
from __future__ import annotations

from schemas.funding_request import SimulationRequest
from backend.services.candidate_funding import funding_summary, funding_issues, profile_funding_inputs
from backend.router import run_simulation

PROPERTY_TYPES = {
    "apartment": "아파트", "아파트": "아파트",
    "officetel": "오피스텔", "오피스텔": "오피스텔",
    "row_house": "연립다세대", "연립다세대": "연립다세대",
    "detached": "단독다가구", "단독다가구": "단독다가구",
    "non_residential": "상가", "상가": "상가", "사무실": "사무실",
    "industrial": "공장", "공장": "공장", "창고": "창고",
    "land": "토지", "토지": "토지",
}


def _calculate(candidate: dict, profile: dict, *, price_delta_won: int = 0,
               interest_delta_pct: float = 0.0, reserve_delta_won: int = 0) -> dict:
    price = candidate.get("asking_price")
    if not isinstance(price, int) or price + price_delta_won <= 0:
        return {"status": "needs_input", "missing": ["asking_price"]}
    required = ["cash_available", "monthly_payment_limit", "loan_ratio", "annual_interest_rate",
                "loan_years", "owned_homes", "adjusted_area"]
    missing = [key for key in required if profile.get(key) is None]
    if missing:
        return {"status": "needs_input", "missing": missing}
    property_type = PROPERTY_TYPES.get(candidate.get("category"))
    if not property_type:
        return {"status": "needs_input", "missing": ["property_type"]}
    reserve = profile.get("emergency_reserve", 0) + reserve_delta_won
    cash = profile["cash_available"] - reserve
    if cash < 0 or reserve < 0:
        return {"status": "invalid", "missing": ["emergency_reserve"]}
    rate = profile["annual_interest_rate"] + interest_delta_pct
    if not 0 <= rate <= 30:
        return {"status": "invalid", "missing": ["annual_interest_rate"]}
    values = profile_funding_inputs(profile, {"cash_available": cash, "annual_interest_rate": rate})
    request = SimulationRequest(purchase_price=price + price_delta_won, property_type=property_type, **values)
    result = run_simulation(request.to_simulation_input())
    if not isinstance(result, dict) or result.get("error"):
        return {"status": "failed", "missing": []}
    raw = result.get("result")
    calculated = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
    if not isinstance(calculated, dict):
        return {"status": "failed", "missing": []}
    summary = funding_summary(request, calculated)
    return {"status": "calculated", "summary": summary,
            "warnings": [title for _, title, _, _ in funding_issues(summary)]}


def compare_funding_scenarios(case: dict, *, property_ids: list[int] | None = None,
                              price_delta_won: int = 0, interest_delta_pct: float = 0.0,
                              reserve_delta_won: int = 0) -> dict:
    profile = case.get("buyer_profile") or {}
    selected = set(property_ids or [])
    candidates = [p for p in case.get("properties", []) if p.get("status") != "rejected"
                  and (not selected or p["id"] in selected)][:4]
    rows = []
    for candidate in candidates:
        base = _calculate(candidate, profile)
        changed = _calculate(candidate, profile, price_delta_won=price_delta_won,
                             interest_delta_pct=interest_delta_pct, reserve_delta_won=reserve_delta_won)
        deltas = {}
        if base["status"] == changed["status"] == "calculated":
            for key in ("required_cash", "cash_shortfall", "monthly_payment", "acquisition_cost"):
                before, after = base["summary"].get(key), changed["summary"].get(key)
                deltas[key] = after - before if isinstance(before, (int, float)) and isinstance(after, (int, float)) else None
        rows.append({"property_id": candidate["id"], "name": candidate["name"],
                     "asking_price": candidate.get("asking_price"),
                     "source_status": (candidate.get("source_status") or {}).get("status"),
                     "baseline": base, "scenario": changed, "deltas": deltas})
    return {"case_id": case["id"], "profile": profile,
            "scenario_inputs": {"price_delta_won": price_delta_won,
                                "interest_delta_pct": interest_delta_pct,
                                "reserve_delta_won": reserve_delta_won},
            "rows": rows, "persisted": False,
            "boundary": "시나리오 결과는 저장된 후보 분석이나 선택을 변경하지 않습니다. 대출 승인 결과가 아닙니다."}
