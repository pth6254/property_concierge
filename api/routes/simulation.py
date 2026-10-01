"""POST /api/simulation — 투자 시뮬레이션"""
from __future__ import annotations

import asyncio
from decimal import Decimal
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api import case_db
from api.deps import get_optional_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["simulation"])


class SimulationRequest(BaseModel):
    case_id: int | None = None
    candidate_id: int | None = None
    purchase_price: int = Field(..., gt=0)
    cash_available: int | None = Field(None, ge=0)
    monthly_payment_limit: int | None = Field(None, ge=0)
    loan_ratio: float = Field(0.5, ge=0.0, le=0.9)
    annual_interest_rate: float = Field(4.0, ge=0.0, le=30.0)
    loan_years: int = Field(30, ge=1, le=50)
    repayment_type: Literal["equal_payment", "equal_principal", "interest_only"] = "equal_payment"
    holding_years: int = Field(3, ge=1, le=50)
    expected_annual_growth_rate: float = Field(0.0, ge=-20.0, le=50.0)
    rent_deposit: Optional[int] = None
    rent_fee: Optional[int] = None
    monthly_management_fee: Optional[int] = None
    property_type: str = "아파트"
    owned_homes: int = Field(1, ge=1, le=100, description="취득 후 주택 수. 첫 주택 취득은 1")
    # 세금·규제 (선택)
    official_price: Optional[int] = None            # 공시가격 (원)
    residence_years: Optional[int] = None           # 거주 연수
    vacancy_rate: float = Field(5.0, ge=0.0, le=50.0)
    adjusted_area: bool = False                     # 조정대상지역
    annual_income: Optional[int] = None             # 연소득 (원, DSR)
    existing_loan_annual_payment: int = Field(0, ge=0)

    def to_simulation_input(self):
        from schemas.simulation import SimulationInput

        # 화면·대화·시나리오에서 필드를 따로 복사하면 같은 조건도 서로 다른 계산이 된다.
        values = self.model_dump(exclude={"case_id", "candidate_id", "loan_ratio", "monthly_payment_limit"})
        return SimulationInput(**values, loan_amount=int(Decimal(self.purchase_price) * Decimal(str(self.loan_ratio))))


class SimulationFromListingRequest(BaseModel):
    listing_id: str
    overrides: Optional[dict] = None


@router.get("/simulation/market-rate")
async def get_market_rate():
    """최신 주담대 평균금리 (한국은행 ECOS, 24h 캐시). 미연결 시 기본값."""
    import asyncio as _asyncio
    from backend.bok_rates import get_mortgage_rate
    return await _asyncio.to_thread(get_mortgage_rate)


@router.post("/simulation")
async def run_simulation_endpoint(req: SimulationRequest, user: dict | None = Depends(get_optional_user)):
    return await asyncio.to_thread(execute_simulation, req, user)


def execute_simulation(req: SimulationRequest, user: dict | None):
    """화면과 대화가 동일한 계산 및 후보 저장 경로를 사용한다."""
    from backend.router import run_simulation

    if req.case_id is not None or req.candidate_id is not None:
        if req.case_id is None or req.candidate_id is None or not user or not case_db.validate_candidate(req.case_id, req.candidate_id, user["id"]):
            raise HTTPException(status_code=404, detail="검토 후보가 없습니다")
    inp = req.to_simulation_input()

    logger.info("시뮬레이션 요청 — 매수가 %s원, 대출비율 %.0f%%", req.purchase_price, req.loan_ratio * 100)
    result = run_simulation(inp)
    if req.case_id is not None and req.candidate_id is not None and user and isinstance(result, dict) and not result.get("error"):
        calculated_raw = result.get("result")
        calculated = calculated_raw.model_dump(mode="json") if hasattr(calculated_raw, "model_dump") else (calculated_raw or {})
        from backend.services.candidate_funding import funding_summary, funding_issues
        summary = funding_summary(req, calculated)
        issues = funding_issues(summary)
        linked = case_db.link_candidate_analysis(
            req.case_id, req.candidate_id, user["id"], "simulation",
            summary,
            checklist_status="warning" if issues else "done",
            evidence="사용자가 입력한 금융 조건으로 자금 시뮬레이션 완료",
        )
        if not linked:
            raise HTTPException(status_code=404, detail="계산 결과를 저장할 검토 후보가 없습니다")
        result["candidate_funding"] = summary
    return result
