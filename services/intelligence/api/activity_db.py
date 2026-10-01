"""activity 내부 계약 클라이언트. 저장·권한·트랜잭션은 Kotlin에서 처리한다."""
from __future__ import annotations

from typing import Optional
from api.core_bridge import core_store


@core_store("activity")
def save(type_: str, title: str, summary: str = "",
         meta: Optional[dict] = None, user_id=None) -> int:
    ...

@core_store("activity")
def count_today(type_: str, user_id) -> int:
    ...

@core_store("activity")
def delete_all(user_id) -> None:
    ...

@core_store("activity")
def load_recent(limit: int = 10, user_id=None) -> list[dict]:
    ...


def init():
    """Alembic 없이 띄우는 경로의 공통 스키마 안전망만 유지한다."""
    from db.base import init_db
    init_db()
