"""Redis Stream 작업 입력·상태 저장과 사용자별 결과 조회.

실제 API 경로는 create_task()로 저장 가능한 입력을 기록하고 api.job_worker가 실행한다.
create()는 callable을 직접 넘기는 기존 테스트·내부 호출의 호환 경로다.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Callable, Optional
from fastapi.encoders import jsonable_encoder

from db.redis_client import get_redis

FINISHED_TTL = 60 * 60       # 완료/실패 작업 Redis 보관 1시간
PENDING_TTL  = 60 * 60 * 2   # queued/running 상태 안전망 TTL — 워커가 죽어도 영구 고아 키로 남지 않게
MAX_CONCURRENT = 4           # 별도 실행기 프로세스당 동시 실행 상한

_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT)
STREAM = "property-jobs:pytest" if os.getenv("PYTEST_CURRENT_TEST") else "property-jobs"
GROUP = "property-job-workers"


def _key(job_id: str) -> str:
    return f"job:{job_id}"


def _save(job_id: str, job: dict, ttl: int) -> None:
    # 실제 파이프라인 결과에는 Pydantic 의도·주소 모델이 포함된다.
    get_redis().set(_key(job_id), json.dumps(jsonable_encoder(job), ensure_ascii=False), ex=ttl)


def _load(job_id: str) -> Optional[dict]:
    raw = get_redis().get(_key(job_id))
    return json.loads(raw) if raw is not None else None


def create_task(task_type: str, payload: dict, owner_id: int | None = None) -> str:
    """재시작 후에도 실행할 수 있도록 작업 입력과 상태를 함께 Redis에 기록한다."""
    job_id = uuid.uuid4().hex[:16]
    job = {"id": job_id, "status": "queued", "step": "", "created_at": time.time(),
           "finished_at": 0.0, "result": None, "error": "", "extra": {}, "owner_id": owner_id}
    client = get_redis()
    with client.pipeline(transaction=True) as pipe:
        pipe.set(_key(job_id), json.dumps(job, ensure_ascii=False), ex=PENDING_TTL)
        pipe.xadd(STREAM, {"job_id": job_id, "task_type": task_type,
                           "payload": json.dumps(jsonable_encoder(payload), ensure_ascii=False)})
        _, stream_id = pipe.execute()
    if os.getenv("PYTEST_CURRENT_TEST"):
        # API 단위 테스트는 별도 OS 프로세스 대신 동일한 실행기를 돌려 패치를 공유한다.
        def _test_worker():
            from api.job_worker import ensure_group, process_record
            ensure_group()
            try:
                process_record(stream_id, {"job_id": job_id, "task_type": task_type,
                                           "payload": json.dumps(payload, ensure_ascii=False)})
            finally:
                client.xdel(STREAM, stream_id)
        threading.Thread(target=_test_worker, daemon=True).start()
    return job_id


def create(runner: Callable[[Callable[[str], None]], dict],
           on_done: Optional[Callable[[dict], Any]] = None,
           owner_id: Optional[int] = None, *, require_on_done: bool = False) -> str:
    """
    작업 생성 및 백그라운드 실행.

    Args:
        runner  : fn(set_step) -> result dict. set_step(str)으로 진행 단계 보고.
                  result에 "error" 키가 있으면 실패로 처리.
        on_done : 성공 시 result를 받아 부가 처리(이력 저장 등) 후
                  job에 병합할 dict를 반환하는 콜백 (예: {"history_id": 3}).
        owner_id: 작업을 생성한 사용자 id. 지정하면 get()에서 소유자만 조회 가능.
                  None(비로그인)이면 추측 불가한 job_id 자체가 접근 토큰이 된다.
    Returns:
        job_id
    """
    job_id = uuid.uuid4().hex[:16]
    job = {
        "id":          job_id,
        "status":      "queued",     # queued | running | done | error
        "step":        "",
        "created_at":  time.time(),
        "finished_at": 0.0,
        "result":      None,
        "error":       "",
        "extra":       {},
        "owner_id":    owner_id,
    }
    _save(job_id, job, ttl=PENDING_TTL)

    def set_step(step: str):
        current = _load(job_id) or job
        current["step"] = step
        _save(job_id, current, ttl=PENDING_TTL)

    def _run():
        with _SEMAPHORE:
            current = _load(job_id) or job
            current["status"] = "running"
            _save(job_id, current, ttl=PENDING_TTL)
            try:
                result = runner(set_step)
                current = _load(job_id) or job
                if isinstance(result, dict) and result.get("error"):
                    current["status"]      = "error"
                    current["error"]       = str(result["error"])
                    current["result"]      = result
                    current["finished_at"] = time.time()
                    _save(job_id, current, ttl=FINISHED_TTL)
                    return

                extra = {}
                if on_done is not None:
                    try:
                        extra = on_done(result) or {}
                    except Exception as e:
                        if require_on_done:
                            raise RuntimeError("분석 결과를 후보에 저장하지 못했습니다. 이력을 확인해주세요.") from e
                        # 부가 처리 실패(이력 저장 등)는 작업 실패로 만들지 않음
                        print(f"[jobs] on_done 오류: {e}")

                current["status"]      = "done"
                current["result"]      = result
                current["extra"]       = extra
                current["finished_at"] = time.time()
                _save(job_id, current, ttl=FINISHED_TTL)
            except Exception as e:
                current = _load(job_id) or job
                current["status"]      = "error"
                current["error"]       = str(e)
                current["finished_at"] = time.time()
                _save(job_id, current, ttl=FINISHED_TTL)

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def get(job_id: str, include_result: bool = True,
        requester_id: Optional[int] = None) -> Optional[dict]:
    """
    작업 상태 조회. 없거나 접근 권한이 없으면 None.

    소유자가 지정된 작업(owner_id is not None)은 동일 사용자만 조회할 수 있다.
    권한 없음도 None으로 반환해 job 존재 여부를 노출하지 않는다.
    """
    job = _load(job_id)
    if job is None:
        return None
    if job.get("owner_id") is not None and job["owner_id"] != requester_id:
        return None
    out = {
        "job_id": job["id"],
        "status": job["status"],
        "step":   job["step"],
        "error":  job["error"],
        **job["extra"],
    }
    if include_result and job["status"] in ("done", "error"):
        out["result"] = job["result"]
    return out
