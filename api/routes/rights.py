"""POST /api/rights/analyze — 등기부등본·건축물대장 PDF 권리관계 위험 점검

개인정보 처리 원칙:
  - 업로드된 PDF는 메모리에서만 처리되며 디스크·DB에 저장하지 않는다 (분석 후 즉시 파기).
  - 활동 피드에는 등기부상 상세 주소 대신 마스킹된 주소만 기록한다.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api import activity_db, case_db
from api.deps import get_optional_user
from api.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rights"])

MAX_PDF_BYTES = 10 * 1024 * 1024   # 10MB

PRIVACY_NOTICE = "업로드된 문서는 분석 후 즉시 파기되며 서버에 저장되지 않습니다."


class RightsAnalyzeRequest(BaseModel):
    """PDF는 base64 인코딩 문자열로 전달 (multipart 불필요)"""
    case_id: int | None = None
    candidate_id: int | None = None
    registry_pdf_b64: Optional[str] = None   # 등기사항전부증명서
    building_pdf_b64: Optional[str] = None   # 건축물대장
    my_deposit: int = Field(0, ge=0, description="내 보증금 (원)")
    market_price: int = Field(0, ge=0, description="시세 (원) — AVM 추정치 또는 직접 입력")


def _decode(b64: Optional[str], name: str) -> bytes | None:
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64.split(",")[-1])   # dataURL 접두사 허용
    except Exception:
        raise HTTPException(status_code=400, detail=f"{name}: base64 디코딩 실패")
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail=f"{name}: 10MB 초과")
    if not raw.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail=f"{name}: PDF 파일이 아닙니다")
    return raw


def _mask_address(address: str) -> str:
    """상세 주소 마스킹 — 행정구역(시·구·동)까지만 남기고 번지·건물·호수는 제거"""
    tokens = address.split()
    if len(tokens) <= 3:
        return address
    return " ".join(tokens[:3]) + " ***"


@router.post("/rights/analyze")
@limiter.limit("5/minute")
async def analyze_rights_endpoint(
    request: Request,
    req: RightsAnalyzeRequest,
    user: Optional[dict] = Depends(get_optional_user),
):
    from backend.services.rights_analysis_service import analyze_rights

    if req.case_id is not None or req.candidate_id is not None:
        if req.case_id is None or req.candidate_id is None or not user or not case_db.validate_candidate(req.case_id, req.candidate_id, user["id"]):
            raise HTTPException(status_code=404, detail="검토 후보가 없습니다")

    registry = _decode(req.registry_pdf_b64, "등기부등본")
    building = _decode(req.building_pdf_b64, "건축물대장")
    if registry is None and building is None:
        raise HTTPException(status_code=400, detail="분석할 PDF가 없습니다")

    logger.info("권리 점검 요청 — 등기부 %s / 대장 %s / 보증금 %s",
                bool(registry), bool(building), req.my_deposit or "-")
    result = await asyncio.to_thread(
        analyze_rights, registry, building, req.my_deposit, req.market_price,
    )

    # 홈 '최근 활동' 피드용 기록 (실패해도 분석 결과 반환에는 영향 없음)
    # 개인정보 최소화: 상세 주소는 마스킹해서 저장
    if isinstance(result, dict) and not result.get("error"):
        try:
            reg = result.get("registry") or {}
            title = _mask_address(reg["address"]) if reg.get("address") else "등기부등본 권리 분석"
            activity_db.save(
                "rights",
                title,
                summary=result.get("risk_label", ""),
                meta={
                    "risk_grade": result.get("risk_grade"),
                    "risk_score": result.get("risk_score"),
                },
                user_id=user["id"] if user else None,
            )
        except Exception:
            logger.warning("권리 점검 활동 기록 실패", exc_info=True)

    if isinstance(result, dict):
        result["privacy_notice"] = PRIVACY_NOTICE
        if not result.get("error") and req.case_id is not None and req.candidate_id is not None and user:
            grade = result.get("risk_grade")
            case_db.link_candidate_analysis(
                req.case_id, req.candidate_id, user["id"], "rights",
                {"risk_grade": grade, "risk_label": result.get("risk_label"),
                 "risk_score": result.get("risk_score"), "reasons": result.get("reasons") or [],
                 "registry_supplied": registry is not None, "building_supplied": building is not None,
                 "registry_parsed": bool(result.get("registry") and not result["registry"].get("error")),
                 "building_parsed": bool(result.get("building") and not result["building"].get("error"))},
                checklist_status="done" if grade == "safe" else "warning",
                evidence=f"업로드 문서 기반 권리분석 완료 · {result.get('risk_label') or grade}",
            )
    return result
