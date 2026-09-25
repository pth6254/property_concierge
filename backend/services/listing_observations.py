"""수집 시점과 사용자 확인 시점을 분리한다. 실패로 가격·거래 상태를 덮어쓰지 않는다."""
import asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from fastapi import HTTPException
from db.base import session_scope
from db.models import ListingObservation
from backend.services.naver_listing_collector import collect_page, canonical_url


def record_observation(user_id, result, job_id=None):
    with session_scope() as session:
        if job_id:
            stmt = pg_insert(ListingObservation).values(user_id=user_id, external_id=result["external_id"],
                requested_at=result["requested_at"], fetched_at=result["fetched_at"],
                outcome=result["outcome"], payload=result, job_id=job_id)
            stmt = stmt.on_conflict_do_update(index_elements=[ListingObservation.job_id],
                set_={"job_id": stmt.excluded.job_id}).returning(ListingObservation.id)
            observation_id = session.scalar(stmt)
            original = session.get(ListingObservation, observation_id)
            return {"observation_id": observation_id, **original.payload}
        row = ListingObservation(user_id=user_id, external_id=result["external_id"],
            requested_at=result["requested_at"], fetched_at=result["fetched_at"],
            outcome=result["outcome"], payload=result)
        session.add(row)
        session.flush()
        return {"observation_id": row.id, **result}


def collect(user_id, url, job_id=None):
    return record_observation(user_id, asyncio.run(collect_page(url)), job_id=job_id)


def history(user_id, url):
    _, external_id = canonical_url(url)
    with session_scope() as session:
        rows = session.scalars(select(ListingObservation).where(
            ListingObservation.user_id == user_id, ListingObservation.external_id == external_id
        ).order_by(ListingObservation.fetched_at.desc(), ListingObservation.id.desc()).limit(100)).all()
        return {"items": [{"observation_id": r.id, **r.payload} for r in rows]}


def get_observation(user_id, observation_id):
    with session_scope() as session:
        row = session.scalar(select(ListingObservation).where(ListingObservation.user_id == user_id, ListingObservation.id == observation_id))
        if not row:
            raise HTTPException(404, "수집 기록을 찾을 수 없습니다")
        return {"observation_id": row.id, **row.payload}
