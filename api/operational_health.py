"""기동 여부와 서비스 준비 상태를 분리한다. 외부 호출·사용자 데이터는 조회하지 않는다."""
from __future__ import annotations

import logging
import time
from sqlalchemy import text

from api import jobs
from db.base import get_engine
from db.redis_client import get_redis

logger = logging.getLogger(__name__)
WORKERS = f"{jobs.STREAM}:workers"
ALERTS = f"{jobs.STREAM}:ops-alerts"


def worker_heartbeat(consumer: str) -> None:
    client = get_redis()
    now = time.time()
    with client.pipeline() as pipe:
        pipe.zadd(WORKERS, {consumer: now})
        pipe.zremrangebyscore(WORKERS, "-inf", now - 300)
        pipe.expire(WORKERS, 300)
        pipe.execute()


def snapshot() -> dict:
    checks = {"database": "down", "redis": "down", "worker": "down", "queue": "unknown"}
    queue = {"waiting": None, "in_progress": None, "oldest_wait_seconds": None}
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        pass
    try:
        client = get_redis()
        client.ping()
        checks["redis"] = "ok"
        if client.zcount(WORKERS, time.time() - 30, "+inf"):
            checks["worker"] = "ok"
        if client.exists(jobs.STREAM):
            groups = client.xinfo_groups(jobs.STREAM)
            group = next((g for g in groups if g["name"] == jobs.GROUP), None)
            if group:
                waiting = group.get("lag")
                first = client.xrange(jobs.STREAM, min=f"({group['last-delivered-id']}", max="+", count=1)
                age = max(0, time.time() - int(first[0][0].split("-")[0]) / 1000) if first else 0
                queue = {"waiting": waiting, "in_progress": group["pending"], "oldest_wait_seconds": round(age)}
                checks["queue"] = "delayed" if age > 120 or (waiting or 0) > 100 else "ok"
    except Exception:
        pass
    return {"status": "ready" if all(v == "ok" for v in checks.values()) else "degraded",
            "checks": checks, "queue": queue, "checked_at": time.time()}


def record_transition(state: dict) -> None:
    """같은 장애를 반복 알리지 않고 장애·복구 전환을 운영 알림함에 남긴다."""
    import json
    client = get_redis()
    value = json.dumps(state["checks"], sort_keys=True)
    previous = client.getset(f"{ALERTS}:state", value)
    if previous != value:
        client.xadd(ALERTS, {"status": state["status"], "checks": value, "at": str(state["checked_at"])},
                    maxlen=200, approximate=False)
        logger.warning("운영 상태 변경: %s", value)


def monitor(stop) -> None:
    # 실행기와 독립된 프로세스에서 관찰해야 실행기 자체의 종료도 감지한다.
    while not stop.is_set():
        try:
            record_transition(snapshot())
        except Exception:
            logger.error("운영 상태 저장 실패: Redis 연결을 확인하세요")
        stop.wait(15)


if __name__ == "__main__":
    import threading
    monitor(threading.Event())
