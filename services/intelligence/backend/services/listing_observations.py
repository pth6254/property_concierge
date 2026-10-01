"""observations 내부 계약 클라이언트. 저장·권한·트랜잭션은 Kotlin에서 처리한다."""
from __future__ import annotations

from typing import Optional
from api.core_bridge import core_store
import asyncio
from backend.services.naver_listing_collector import collect_page


@core_store("observations")
def record_observation(user_id, result, job_id=None):
    ...

@core_store("observations")
def history(user_id, url):
    ...

@core_store("observations")
def get_observation(user_id, observation_id):
    ...


def collect(user_id, url, job_id=None):
    return record_observation(user_id, asyncio.run(collect_page(url)), job_id=job_id)
