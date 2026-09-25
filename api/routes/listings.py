"""사용자별 매물 수입·검색. 공개 매물 공급망이나 외부 수집 API와 구분한다."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from api.deps import get_current_user
from backend.services.listing_store import import_csv, search_listings, listing_history
from schemas.listing_import import ListingImportRequest

router = APIRouter(tags=["imported-listings"])


class CollectionRequest(BaseModel):
    source_url: str = Field(min_length=1, max_length=2000)


@router.post("/listings/collection/jobs", status_code=202)
def start_collection(body: CollectionRequest, user: dict = Depends(get_current_user)):
    from api import jobs
    from db.redis_client import get_redis
    from backend.services.naver_listing_collector import canonical_url
    try:
        url, _ = canonical_url(body.source_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    from backend.services import listing_collection_gate as gate
    wait = gate.remaining()
    if wait:
        raise HTTPException(429, gate.wait_message(wait), headers={"Retry-After": str(wait)})
    # 다중 워커에서도 계정당 1분에 한 번만 시작해 브라우저 실행 누적을 제한한다.
    if not get_redis().set(f"listing-collection-cooldown:{user['id']}", "1", nx=True, ex=60):
        raise HTTPException(429, "수집 요청 후 1분이 지나면 다시 시도해주세요", headers={"Retry-After": "60"})
    return {"job_id": jobs.create_task("listing_collection", {"url": url}, owner_id=user["id"])}


@router.get("/listings/collection/jobs/{job_id}")
def collection_job(job_id: str, user: dict = Depends(get_current_user)):
    from api import jobs
    result = jobs.get(job_id, requester_id=user["id"])
    if result is None:
        raise HTTPException(404, "수집 작업을 찾을 수 없습니다")
    return result


@router.get("/listings/collection/history")
def collection_history(source_url: str = Query(max_length=2000), user: dict = Depends(get_current_user)):
    from backend.services.listing_observations import history
    try:
        return history(user["id"], source_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/listings/import")
def upload(body: ListingImportRequest, user: dict = Depends(get_current_user)):
    return import_csv(user["id"], body.source_name, body.csv_text, commit=body.commit)


@router.get("/listings")
def search(region_code: str | None = Query(None, pattern=r"^\d{10}$"),
           property_type: str | None = Query(None, pattern="^(apartment|officetel|row_house|detached|non_residential|industrial|land)$"),
           transaction_type: str | None = Query(None, pattern="^(purchase|lease|rent)$"),
           status: str | None = Query(None, pattern="^(active|withdrawn|completed|unknown)$"),
           budget_max: int | None = Query(None, ge=0, le=10**15),
           area_min: float | None = Query(None, ge=0, le=100000000), fresh_only: bool = False,
           page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100),
           user: dict = Depends(get_current_user)):
    return search_listings(user["id"], region_code=region_code, property_type=property_type,
        transaction_type=transaction_type, status=status, budget_max=budget_max,
        area_min=area_min, fresh_only=fresh_only, page=page, page_size=page_size)


@router.get("/listings/{listing_id}/history")
def history(listing_id: int, user: dict = Depends(get_current_user)):
    return listing_history(user["id"], listing_id)


@router.get("/listings/{listing_id}")
def get_imported_listing(listing_id: int, user: dict = Depends(get_current_user)):
    from backend.services.listing_store import get_listing
    return get_listing(user["id"], listing_id)


class CandidateTarget(BaseModel):
    case_id: int = Field(gt=0)


@router.post("/listings/{listing_id}/candidate", status_code=201)
def save_candidate(listing_id: int, body: CandidateTarget, response: Response,
                   user: dict = Depends(get_current_user)):
    from api import case_db
    try:
        item = case_db.add_property(body.case_id, user["id"], {"source_listing_id": listing_id})
    except LookupError:
        raise HTTPException(404, "매물을 찾을 수 없습니다") from None
    except ValueError as exc:
        code = 422 if "매매 매물" in str(exc) else 409
        raise HTTPException(code, str(exc)) from None
    if item is None:
        raise HTTPException(404, "검토 케이스가 없습니다")
    if item.pop("_already_linked", False):
        response.status_code = 200
    return item
