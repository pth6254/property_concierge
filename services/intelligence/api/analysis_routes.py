"""Spring이 소유권을 확인한 케이스로만 분석한다. 저장은 하지 않는다."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from api.internal_contracts import require_service
router = APIRouter(prefix="/internal/v1/analysis", dependencies=[Depends(require_service)])
class FundingScenarioRequest(BaseModel):
    property_ids: list[int] = Field(default_factory=list, max_length=4)
    price_delta_won: int = Field(default=0, ge=-10**13, le=10**13)
    interest_delta_pct: float = Field(default=0, ge=-10, le=10)
    reserve_delta_won: int = Field(default=0, ge=-10**13, le=10**13)

class FundingSnapshot(BaseModel):
    case: dict
    request: FundingScenarioRequest

@router.post("/funding-scenarios")
def funding_scenarios(body: FundingSnapshot):
    from backend.services.case_funding_scenarios import compare_funding_scenarios
    case, request = body.case, body.request
    if set(request.property_ids) - {item["id"] for item in case["properties"]}:
        raise HTTPException(404, "검토 후보가 없습니다")
    return compare_funding_scenarios(case, **request.model_dump())

class RecommendationSnapshot(BaseModel):
    case: dict
    region_code: str = Field(pattern=r"^\d{10}$")
    require_complete_address: bool = False

@router.post("/case-recommendations")
def personalized_complexes(body: RecommendationSnapshot):
    case, region_code, require_complete_address = body.case, body.region_code, body.require_complete_address
    from backend.services.complex_recommend_service import recommend_complexes
    profile = case.get("buyer_profile") or {}
    if profile.get("property_types") and "apartment" not in profile["property_types"]:
        return {"results": [], "error": "이 케이스의 희망 유형에 아파트가 없습니다.", "source": "case_profile"}
    result = recommend_complexes("", region_code=region_code, months=profile.get("market_months", 12), limit=10,
        budget_max=(case.get("budget_max") or 0)//10000,
        area_min_sqm=profile.get("min_area_sqm") or 0,
        min_build_year=profile.get("min_build_year") or 0,
        area_max_sqm=profile.get("max_area_sqm") or 0, max_build_year=profile.get("max_build_year") or 0,
        buyer_profile=profile,
        strict_budget=True, priority=profile.get("priority"), require_complete_address=require_complete_address)
    result["criteria"] = {"budget_max_won": case.get("budget_max"),
        "min_area_sqm": profile.get("min_area_sqm"), "min_build_year": profile.get("min_build_year"),
        "max_area_sqm": profile.get("max_area_sqm"), "max_build_year": profile.get("max_build_year"),
        "market_months": profile.get("market_months", 12), "priority": profile.get("priority")}
    return result
