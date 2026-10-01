"""
db/redis_client.py — Redis 커넥션 팩토리

세 곳이 공유한다:
  - api/jobs.py           작업 큐 (기존: 프로세스 메모리 dict)
  - api/rate_limit.py      레이트 리밋 카운터 (기존: slowapi 기본 in-memory)
  - api/routes/auth.py     로그인 실패 잠금 카운터 (기존: 프로세스 메모리 dict)

셋 다 이전에는 프로세스 메모리에 있어서, uvicorn --workers N 으로 띄우면
워커마다 다른 상태를 봤다 (한 워커가 만든 job을 다른 워커가 못 찾음,
레이트 리밋·로그인 잠금 한도가 워커 수만큼 실질적으로 늘어남). Redis로
모으면 워커가 몇 개든 동일한 상태를 공유한다.
"""
from __future__ import annotations

import os
from functools import lru_cache

import redis

REDIS_URL = os.getenv("REDIS_URL", "")
if not REDIS_URL:
    raise RuntimeError(
        "REDIS_URL 환경변수가 설정되지 않았습니다. "
        "예: redis://localhost:6379/0 — 로컬 개발은 `docker compose up redis` 로 먼저 띄우세요."
    )


@lru_cache(maxsize=1)
def get_redis() -> "redis.Redis":
    """프로세스당 커넥션 풀 1개를 재사용한다."""
    return redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=5)
