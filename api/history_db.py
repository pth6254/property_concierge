"""
history_db.py — 시세추정 이력 저장소 (PostgreSQL, SQLAlchemy)

이전에는 SQLite 파일(data/history.db)의 history 테이블이었다. result는
텍스트 컬럼에 json.dumps 해서 넣었지만, 이제는 Postgres JSON 컬럼이라
SQLAlchemy가 dict ↔ JSON 왕복을 대신한다.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.base import init_db, session_scope
from db.models import HistoryRecord


def init():
    init_db()


def _serialize(obj):
    """Pydantic 모델·datetime 등을 JSON 컬럼에 그대로 넣을 수 있는 순수 dict/list/str로 변환."""
    if isinstance(obj, BaseModel):
        return _serialize(obj.model_dump())
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def save(query: str, result: dict, user_id=None, job_id: str | None = None) -> int:
    ar       = result.get("analysis_result") or {}
    category = ar.get("agent_name", "") or result.get("category", "")
    with session_scope() as session:
        if job_id:
            stmt = pg_insert(HistoryRecord).values(query=query, category=category,
                result=_serialize(result), user_id=user_id, job_id=job_id)
            # 작업 재실행이 먼저 끝난 기록을 덮어쓰면 당시 분석 근거가 바뀐다.
            stmt = stmt.on_conflict_do_update(index_elements=[HistoryRecord.job_id],
                set_={"job_id": stmt.excluded.job_id}).returning(HistoryRecord.id)
            return session.scalar(stmt)
        record = HistoryRecord(
            query=query, category=category,
            result=_serialize(result), user_id=user_id,
        )
        session.add(record)
        session.flush()
        return record.id


def count_all(user_id=None) -> int:
    with session_scope() as session:
        stmt = select(func.count()).select_from(HistoryRecord)
        if user_id is not None:
            stmt = stmt.where(HistoryRecord.user_id == user_id)
        return session.scalar(stmt)


def load_all(limit: int = 100, offset: int = 0, user_id=None) -> list[dict]:
    with session_scope() as session:
        stmt = select(HistoryRecord).order_by(HistoryRecord.created.desc()).limit(limit).offset(offset)
        if user_id is not None:
            stmt = stmt.where(HistoryRecord.user_id == user_id)
        return [_row_to_dict(r) for r in session.scalars(stmt)]


def load_one(record_id: int, user_id=None) -> Optional[dict]:
    """
    이력 1건 조회.

    user_id를 넘기면 해당 사용자의 레코드만 반환한다(소유자 검증).
    id가 순차 정수이므로 필터 없이 조회하면 타인의 리포트가 노출된다 —
    사용자 요청 경로에서는 반드시 user_id를 함께 넘길 것.
    """
    with session_scope() as session:
        stmt = select(HistoryRecord).where(HistoryRecord.id == record_id)
        if user_id is not None:
            stmt = stmt.where(HistoryRecord.user_id == user_id)
        record = session.scalar(stmt)
    if not record:
        return None
    d = dict(record.result)
    d["query"] = record.query
    return d


def search_by_query(keyword: str, limit: int = 50, user_id=None) -> list[dict]:
    with session_scope() as session:
        stmt = (
            select(HistoryRecord)
            .where(HistoryRecord.query.ilike(f"%{keyword}%"))
            .order_by(HistoryRecord.created.desc())
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(HistoryRecord.user_id == user_id)
        return [_row_to_dict(r) for r in session.scalars(stmt)]


def delete_one(record_id: int, user_id=None):
    with session_scope() as session:
        stmt = delete(HistoryRecord).where(HistoryRecord.id == record_id)
        if user_id is not None:
            stmt = stmt.where(HistoryRecord.user_id == user_id)
        session.execute(stmt)


def delete_all(user_id=None):
    with session_scope() as session:
        stmt = delete(HistoryRecord)
        if user_id is not None:
            stmt = stmt.where(HistoryRecord.user_id == user_id)
        session.execute(stmt)


def _row_to_dict(r: HistoryRecord) -> dict:
    item = {
        "id":       r.id,
        "query":    r.query,
        "category": r.category,
        "created":  r.created,
    }
    item.update(r.result)
    ar = item.get("analysis_result") or {}
    for key in (
        "estimated_value", "value_min", "value_max",
        "price_per_pyeong", "regional_avg_per_pyeong",
        "valuation_verdict", "deviation_pct",
        "cap_rate", "investment_grade", "annual_income",
        "appraisal_opinion", "strengths", "risk_factors", "recommendation",
        "comparable_avg", "comparable_count", "roi_5yr",
    ):
        if key not in item and key in ar:
            item[key] = ar[key]
    return item
