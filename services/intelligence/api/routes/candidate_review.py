"""후보 한 번에 검토. Spring이 세션과 후보 소유를 확인한 뒤 행위자 ID와 함께 호출한다."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from api.ai_context import get_current_user
from api.internal_contracts import require_service
from schemas.candidate_review import CandidateQuickReviewRequest, CandidateQuickReviewResponse

router = APIRouter(prefix="/internal/v1/ai", dependencies=[Depends(require_service)], tags=["candidate-review"])


@router.post("/candidate-review", response_model=CandidateQuickReviewResponse)
async def candidate_review(request: CandidateQuickReviewRequest, user: dict = Depends(get_current_user)):
    from backend.services.candidate_quick_review import run_quick_review
    try:
        # 자금 계산·작업 접수가 Spring 내부 계약을 동기 호출하므로 이벤트 루프 밖에서 실행한다.
        return await asyncio.to_thread(run_quick_review, user["id"], request.case_id, request.candidate_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="검토 후보가 없습니다") from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
