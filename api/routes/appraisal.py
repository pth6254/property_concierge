"""POST /api/appraisal — 시세추정 실행 (동기 + 비동기 job)"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api import case_db, history_db, jobs
from api.deps import get_optional_user
from api.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["appraisal"])


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


def _validate_candidate_link(req: AppraisalRequest, user: Optional[dict]) -> None:
    if req.case_id is None and req.candidate_id is None:
        return
    if req.case_id is None or req.candidate_id is None or not user:
        raise HTTPException(status_code=404, detail="검토 후보가 없습니다")
    if not case_db.validate_candidate(req.case_id, req.candidate_id, user["id"]):
        raise HTTPException(status_code=404, detail="검토 후보가 없습니다")
    if not req.save_history:
        raise HTTPException(status_code=422, detail="후보 연결 분석은 이력 저장이 필요합니다")


def _save_history(req: AppraisalRequest, user: Optional[dict]):
    """성공 결과 → history DB 영속화 콜백 생성. 반환: job extra dict"""
    def on_done(result: dict) -> dict:
        if not req.save_history:
            return {}
        history_id = history_db.save(
            req.user_input, result, user_id=user["id"] if user else None
        )
        if req.case_id is not None and req.candidate_id is not None and user:
            if not case_db.link_appraisal(req.case_id, req.candidate_id, history_id, user["id"], result):
                raise ValueError("candidate_link_failed")
        return {"history_id": history_id}
    return on_done


# ─────────────────────────────────────────
#  동기 실행 (하위 호환)
# ─────────────────────────────────────────

@router.post("/appraisal")
@limiter.limit("5/minute")
async def run_appraisal_endpoint(request: Request, req: AppraisalRequest, user: Optional[dict] = Depends(get_optional_user)):
    from backend.router import run_appraisal

    _validate_candidate_link(req, user)

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
    )

    if req.save_history and not result.get("error"):
        try:
            result["history_id"] = history_db.save(
                req.user_input, result, user_id=user["id"] if user else None
            )
            if req.case_id is not None and req.candidate_id is not None and user:
                case_db.link_appraisal(req.case_id, req.candidate_id, result["history_id"], user["id"], result)
        except Exception as e:
            logger.warning("이력 저장 실패: %s", e)

    return result


# ─────────────────────────────────────────
#  비동기 job 실행
# ─────────────────────────────────────────

@router.post("/appraisal/jobs")
@limiter.limit("5/minute")
async def create_appraisal_job(request: Request, req: AppraisalRequest, user: Optional[dict] = Depends(get_optional_user)):
    """작업 생성 → 즉시 job_id 반환. 진행 상태는 GET /appraisal/jobs/{id} 폴링."""
    from backend.router import run_appraisal

    _validate_candidate_link(req, user)

    logger.info("시세추정 요청(job) — %s / %s", req.user_input, req.building_name)

    expected_inputs = (case_db.candidate_inputs(req.case_id, req.candidate_id, user["id"])
                        if req.case_id is not None and req.candidate_id is not None and user else None)
    job_id = jobs.create_task("appraisal", {"request": req.model_dump(mode="json"),
                                                  "expected_candidate_inputs": expected_inputs},
                              owner_id=user["id"] if user else None)
    return {"job_id": job_id}


@router.get("/appraisal/jobs/{job_id}")
def get_appraisal_job(job_id: str, user: Optional[dict] = Depends(get_optional_user)):
    """작업 상태 조회. done이면 result + history_id 포함. 로그인 상태로 생성한 작업은 본인만 조회 가능."""
    job = jobs.get(job_id, requester_id=user["id"] if user else None)
    if job is None:
        raise HTTPException(status_code=404, detail="작업 없음 (만료되었을 수 있음)")
    return job
