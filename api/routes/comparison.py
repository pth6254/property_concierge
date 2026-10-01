"""POST /api/comparison — 매물 비교"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)
from api.internal_contracts import require_service

router = APIRouter(prefix="/internal/v1/ai", dependencies=[Depends(require_service)], tags=["comparison"])


class ComparisonRequest(BaseModel):
    listings: list[dict]
    recommendation_results: Optional[list[dict]] = None
    simulation_results: Optional[list[dict]] = None


@router.post("/comparison")
async def run_comparison_endpoint(req: ComparisonRequest):
    from backend.router import run_comparison
    from schemas.property_listing import PropertyListing

    listings = [PropertyListing(**l) for l in req.listings]

    logger.info("비교 요청 — %d건", len(listings))
    result = await asyncio.to_thread(
        run_comparison,
        listings,
        req.recommendation_results,
        req.simulation_results,
    )
    return result
