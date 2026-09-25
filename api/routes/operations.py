"""운영 권한이 있는 기존 계정만 시스템 현황과 재처리를 조회·실행한다."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from api.deps import require_operator
from api import jobs
from api.operational_health import snapshot, ALERTS
from db.base import session_scope
from db.models import ComplexCatalog, ListingObservation
from db.redis_client import get_redis

router = APIRouter(prefix="/operations", tags=["operations"], dependencies=[Depends(require_operator)])


@router.get("/status")
def status():
    state = snapshot()
    try:
        state["alerts"] = [{"id": key, **value, "checks": json.loads(value["checks"])}
                           for key, value in get_redis().xrevrange(ALERTS, count=20)]
    except Exception:
        state["alerts"] = []
    return state


@router.get("/complexes")
def complexes(lawd_code: str = Query("11350", pattern=r"^\d{5}$"), page: int = Query(1, ge=1)):
    with session_scope() as session:
        query = select(ComplexCatalog).where(ComplexCatalog.lawd_code == lawd_code)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.scalars(query.order_by(ComplexCatalog.id).offset((page-1)*30).limit(30))
        return {"total": total, "page": page, "items": [{"id": r.id, "name": r.name, "dong": r.dong,
            "aliases": r.aliases, "status": r.status, "address": r.address, "checked_at": r.checked_at} for r in rows]}


def enqueue(task_type, payload, user):
    # 요청 중복으로 외부 API를 반복 호출하지 않도록 작업 예약을 Redis에서 공유한다.
    key = f"ops-request:{task_type}:{json.dumps(payload, sort_keys=True)}"
    client = get_redis()
    if not client.set(key, "reserved", nx=True, ex=600):
        raise HTTPException(409, "이미 요청된 작업입니다. 10분 후 다시 확인하세요.")
    try:
        return {"job_id": jobs.create_task(task_type, payload, user["id"])}
    except Exception:
        client.delete(key)
        raise


@router.post("/complexes/{catalog_id}/refresh")
def refresh(catalog_id: int, user: dict = Depends(require_operator)):
    with session_scope() as session:
        if not session.get(ComplexCatalog, catalog_id):
            raise HTTPException(404, "단지 기준정보가 없습니다")
    return enqueue("complex_refresh", {"catalog_id": catalog_id}, user)


@router.get("/ingestion")
def ingestion(lawd_code: str = Query("11350", pattern=r"^\d{5}$"), months: int = Query(12, ge=1, le=24)):
    from backend.services.ingestion_operations import coverage
    try:
        return coverage(lawd_code, months)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


class RetryIngestion(BaseModel):
    lawd_code: str = Field(pattern=r"^\d{5}$")
    endpoint: str = Field(min_length=1, max_length=80)
    month: str = Field(pattern=r"^\d{4}(0[1-9]|1[0-2])$")


@router.post("/ingestion/retry")
def retry(body: RetryIngestion, user: dict = Depends(require_operator)):
    from backend.services.ingestion_operations import coverage
    try:
        items = coverage(body.lawd_code, 24)["items"]
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not any(r["endpoint"] == body.endpoint and r["month"] == body.month and
               r["status"] in {"failed", "missing", "interrupted", "stale"} for r in items):
        raise HTTPException(422, "실패·누락·중단·만료된 최근 24개월 자료만 재수집할 수 있습니다")
    return enqueue("ingestion_retry", body.model_dump(), user)


@router.get("/jobs/{job_id}")
def job(job_id: str, user: dict = Depends(require_operator)):
    value = jobs.get(job_id, requester_id=user["id"])
    if not value:
        raise HTTPException(404, "작업이 없습니다")
    return value


@router.get("/listing-quality")
def listing_quality():
    # 개별 사용자의 매물 주소·원문·추출값 대신 집계만 운영자에게 제공한다.
    with session_scope() as session:
        rows = session.execute(select(ListingObservation.outcome, func.count()).group_by(ListingObservation.outcome)).all()
    return {"counts": dict(rows), "notice": "원문 추출 상태 집계이며 사람의 정답 대조 결과나 매물 존재율이 아닙니다."}
