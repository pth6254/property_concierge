"""accounts 내부 계약 클라이언트. 저장·권한·트랜잭션은 Kotlin에서 처리한다."""
from __future__ import annotations

from typing import Optional
from api.core_bridge import core_store


@core_store("accounts")
def create_local_user(email: str, password_hash: str, name: str = "") -> dict:
    ...

@core_store("accounts")
def get_or_create_oauth_user(
    email: str, name: str, avatar_url: str, provider: str, provider_id: str
) -> dict:
    ...

@core_store("accounts")
def get_by_email(email: str) -> Optional[dict]:
    ...

@core_store("accounts")
def get_by_id(user_id: int) -> Optional[dict]:
    ...

@core_store("accounts")
def update_password(user_id: int, password_hash: str) -> Optional[dict]:
    ...

@core_store("accounts")
def delete_user(user_id: int) -> None:
    ...


def init():
    """Alembic 없이 띄우는 경로의 공통 스키마 안전망만 유지한다."""
    from db.base import init_db
    init_db()
