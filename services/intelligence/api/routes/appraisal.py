"""POST /api/appraisal — 시세추정 실행 (동기 + 비동기 job)"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from schemas.income_valuation import IncomeValuationInput
from schemas.valuation import ValuationContext

from api import case_db, history_db, jobs
from api.ai_context import get_optional_user

logger = logging.getLogger(__name__)
from api.internal_contracts import require_service

router = APIRouter(prefix="/internal/v1/ai", dependencies=[Depends(require_service)], tags=["appraisal"])


class AppraisalRequest(BaseModel):
    user_input: str
    building_name: str = ""
    address: str = ""
    property_category: Literal["", "주거용", "상업용", "업무용", "산업용", "토지"] = ""
    property_detail: str = ""
    case_id: int | None = None
    candidate_id: int | None = None
    area_sqm: float | None = Field(default=None, gt=0)
    save_history: bool = True
    appraisal_date: str = ""       # YYYYMMDD (빈 문자열 = 현재 시점)
    appraisal_purpose: str = ""    # 담보 / 경매 / 과세 / 매매 / 보상 / 임의
    income_valuation: IncomeValuationInput | None = None
    valuation_context: ValuationContext | None = None

    @model_validator(mode="after")
    def validate_income(self):
        if self.income_valuation is not None:
            if self.property_category not in {"상업용", "업무용"}:
                raise ValueError("임대료 시나리오는 상업·업무용 유형을 선택해주세요")
            from datetime import datetime
            from zoneinfo import ZoneInfo
            day = datetime.strptime(self.appraisal_date, "%Y%m%d").date() if self.appraisal_date else datetime.now(ZoneInfo("Asia/Seoul")).date()
            if self.income_valuation.as_of_date != day:
                raise ValueError("임대료 확인일과 분석 기준일을 맞춰주세요")
        return self


def _validate_candidate_link(req: AppraisalRequest, user: Optional[dict]) -> None:
    if req.case_id is None and req.candidate_id is None:
        return
    if req.case_id is None or req.candidate_id is None or not user:
        raise HTTPException(status_code=404, detail="검토 후보가 없습니다")
    if not case_db.validate_candidate(req.case_id, req.candidate_id, user["id"]):
        raise HTTPException(status_code=404, detail="검토 후보가 없습니다")
    if not req.save_history:
        raise HTTPException(status_code=422, detail="후보 연결 분석은 이력 저장이 필요합니다")
    inputs = case_db.candidate_inputs(req.case_id, req.candidate_id, user["id"])
    if ((inputs or {}).get("identity") or {}).get("area_basis") == "supply":
        raise HTTPException(status_code=422, detail="후보의 전용면적과 면적 기준을 확인해주세요")




# ─────────────────────────────────────────
#  동기 실행 (하위 호환)
# ─────────────────────────────────────────

@router.post("/appraisal")
async def run_appraisal_endpoint(request: Request, req: AppraisalRequest, user: Optional[dict] = Depends(get_optional_user)):
    from backend.router import run_appraisal

    _validate_candidate_link(req, user)

    expected = case_db.candidate_inputs(req.case_id, req.candidate_id, user["id"]) if req.case_id and req.candidate_id and user else None

    logger.info("시세추정 요청(동기) — %s / %s / 기준시점: %s / 목적: %s",
                req.user_input, req.building_name, req.appraisal_date or "현재", req.appraisal_purpose or "없음")
    result = await asyncio.to_thread(
        run_appraisal,
        req.user_input,
        req.building_name,
        req.appraisal_date,
        req.appraisal_purpose,
        address=req.address,
        property_category=req.property_category,
        property_detail=req.property_detail,
        area_sqm=req.area_sqm,
        income_valuation=req.income_valuation.model_dump(mode="json") if req.income_valuation else None,
        valuation_context=req.valuation_context.model_dump(mode="json") if req.valuation_context else None,
    )

    if req.save_history and not result.get("error"):
        try:
            result["history_id"] = history_db.save(
                req.user_input, result, user_id=user["id"] if user else None
            )
            if req.case_id is not None and req.candidate_id is not None and user:
                case_db.link_appraisal(req.case_id, req.candidate_id, result["history_id"], user["id"], result, expected)
        except Exception as e:
            if req.case_id is not None:
                raise HTTPException(status_code=422, detail="후보 분석 연결에 실패했습니다. 후보 변경 여부를 확인하고 다시 실행해주세요") from e
            logger.warning("이력 저장 실패: %s", e)

    return result


# ─────────────────────────────────────────
#  비동기 job 실행
# ─────────────────────────────────────────
