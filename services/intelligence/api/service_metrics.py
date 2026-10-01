"""요청 본문·주소·IP를 저장하지 않는 Redis 운영 집계. 실패해도 사용자 작업을 막지 않는다."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from db.redis_client import get_redis

logger = logging.getLogger(__name__)
BUCKETS = (.1, .5, 1, 3, 10, 30, 60, 120, 300, 900)
RETENTION = 35 * 86400


def _day():
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def record_duration(feature: str, elapsed: float, failed: bool, *, job_id: str | None = None):
    try:
        client = get_redis()
        # 복구 작업의 중복 완료는 같은 job_id로 한 번만 센다.
        if job_id and not client.set(f"metrics:job:{job_id}", "1", ex=RETENTION, nx=True):
            return
        key = f"metrics:duration:{_day()}:{feature}"
        bucket = next((str(b) for b in BUCKETS if elapsed <= b), "overflow")
        with client.pipeline() as pipe:
            pipe.hincrby(key, "requests", 1)
            pipe.hincrby(key, "failures", int(failed))
            pipe.hincrbyfloat(key, "total_seconds", elapsed)
            pipe.hincrby(key, f"bucket:{bucket}", 1)
            pipe.expire(key, RETENTION)
            pipe.sadd(f"metrics:features:{_day()}", feature)
            pipe.expire(f"metrics:features:{_day()}", RETENTION)
            pipe.execute()
    except Exception:
        logger.warning("운영 지표 기록 실패")
