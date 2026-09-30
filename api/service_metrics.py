"""요청 본문·주소·IP를 저장하지 않는 Redis 운영 집계. 실패해도 사용자 작업을 막지 않는다."""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
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


def record_step(step: str, user_id: int):
    try:
        salt = os.environ.get("JWT_SECRET_KEY", "")
        digest = hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()
        key = f"metrics:step:{_day()}:{step}"
        client = get_redis()
        with client.pipeline() as pipe:
            pipe.sadd(key, digest)
            pipe.expire(key, RETENTION)
            pipe.execute()
    except Exception:
        logger.warning("사용 단계 집계 실패")


def summary(days=7):
    client = get_redis()
    dates = [(datetime.now(timezone.utc)-timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]
    features = set().union(*(client.smembers(f"metrics:features:{day}") for day in dates))
    rows = []
    for feature in sorted(features):
        totals = {}
        for day in dates:
            for key,value in client.hgetall(f"metrics:duration:{day}:{feature}").items():
                totals[key] = totals.get(key, 0)+float(value)
        count = int(totals.get("requests", 0))
        accumulated, p95 = 0, None
        for bucket in BUCKETS:
            accumulated += totals.get(f"bucket:{bucket}", 0)
            if count and accumulated >= count*.95:
                p95 = bucket
                break
        rows.append({"feature":feature,"requests":count,"failures":int(totals.get("failures",0)),
            "failure_rate":totals.get("failures",0)/count if count else None,
            "mean_seconds":totals.get("total_seconds",0)/count if count else None,"p95_upper_seconds":p95})
    steps = {}
    for step in ("case_created","conditions_saved","candidate_added","comparison_viewed","candidate_selected"):
        members = set().union(*(client.smembers(f"metrics:step:{day}:{step}") for day in dates))
        steps[step] = len(members)
    return {"days":days,"features":rows,"steps":steps,
        "notice":"UTC 기준 최근 기간. 단계별 고유 사용자 수이며 동일 코호트의 전환율이 아닙니다. p95는 히스토그램 상한이며 900초 초과는 미표시. HTTP 실패는 5xx, 작업 실패는 작업 결과 기준입니다."}
