"""jobs 내부 계약 클라이언트. 저장·권한·트랜잭션은 Kotlin에서 처리한다."""
from __future__ import annotations

from typing import Optional
from api.core_bridge import core_store
FINISHED_TTL = 3600
PENDING_TTL = 7200
MAX_CONCURRENT = 4
STREAM = "property-jobs"
GROUP = "property-job-workers"


@core_store("jobs")
def create_task(task_type: str, payload: dict, owner_id: int | None = None) -> str:
    ...

@core_store("jobs")
def _load(job_id: str) -> Optional[dict]:
    ...

@core_store("jobs")
def _save(job_id: str, job: dict, ttl: int) -> None:
    # 실제 Pydantic 결과의 JSON 변환은 공통 계약 클라이언트가 담당한다.
    ...

@core_store("jobs")
def get(job_id: str, include_result: bool = True,
        requester_id: Optional[int] = None) -> Optional[dict]:
    ...


def _key(job_id: str) -> str:
    return f"job:{job_id}"
