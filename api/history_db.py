"""history 내부 계약 클라이언트. 저장·권한·트랜잭션은 Kotlin에서 처리한다."""
from __future__ import annotations

from typing import Optional
from api.core_bridge import core_store


@core_store("history")
def save(query: str, result: dict, user_id=None, job_id: str | None = None) -> int:
    ...

@core_store("history")
def count_all(user_id=None) -> int:
    ...

@core_store("history")
def load_all(limit: int = 100, offset: int = 0, user_id=None) -> list[dict]:
    ...

@core_store("history")
def load_one(record_id: int, user_id=None) -> Optional[dict]:
    ...

@core_store("history")
def search_by_query(keyword: str, limit: int = 50, user_id=None) -> list[dict]:
    ...

@core_store("history")
def delete_one(record_id: int, user_id=None):
    ...

@core_store("history")
def delete_all(user_id=None):
    ...


def init():
    """Alembic 없이 띄우는 경로의 공통 스키마 안전망만 유지한다."""
    from db.base import init_db
    init_db()
