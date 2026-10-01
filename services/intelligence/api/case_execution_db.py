"""execution 내부 계약 클라이언트. 저장·권한·트랜잭션은 Kotlin에서 처리한다."""
from __future__ import annotations

from typing import Optional
from api.core_bridge import core_store


@core_store("execution")
def ensure_execution_plan(case_id: int, property_id: int, user_id: int) -> dict | None:
    ...

@core_store("execution")
def get_execution(case_id: int, user_id: int) -> dict | None:
    ...

@core_store("execution")
def update_plan(case_id: int, user_id: int, data: dict) -> dict | None:
    ...

@core_store("execution")
def add_task(case_id: int, user_id: int, data: dict) -> dict | None:
    ...

@core_store("execution")
def update_task(case_id: int, task_id: int, user_id: int, data: dict) -> dict | None:
    ...

@core_store("execution")
def delete_task(case_id: int, task_id: int, user_id: int) -> bool | None:
    ...
