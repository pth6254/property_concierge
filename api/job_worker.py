"""Redis Stream의 작업을 별도 프로세스에서 실행하고 중단된 작업을 다시 가져온다."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from redis.exceptions import ResponseError

from api import jobs
from db.redis_client import get_redis

logger = logging.getLogger(__name__)
CONSUMER = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
CLAIM_IDLE_MS = 180_000


def run_task(task_type: str, payload: dict, owner_id: int | None, job_id: str, set_step) -> tuple[dict, dict]:
    """저장된 JSON만 사용한다. API 프로세스의 closure는 재시작 후 존재하지 않는다."""
    if task_type == "probe":
        return {"worker": "ready"}, {}
    if task_type == "complex_refresh":
        from backend.services.complex_catalog import refresh
        set_step("단지 주소 출처 재확인")
        return refresh(payload["catalog_id"]), {}
    if task_type == "ingestion_retry":
        from backend.services.ingestion_operations import retry_one
        set_step("선택한 거래월 재수집")
        return retry_one(payload), {}
    if task_type in {"appraisal", "candidate_appraisal"}:
        from backend.router import run_appraisal
        from api import case_db, history_db

        if task_type == "appraisal":
            from api.routes.appraisal import AppraisalRequest
            req = AppraisalRequest.model_validate(payload["request"])
            result = run_appraisal(req.user_input, req.building_name, req.appraisal_date,
                                   req.appraisal_purpose, progress_cb=set_step, address=req.address,
                                   property_category=req.property_category, property_detail=req.property_detail,
                                   area_sqm=req.area_sqm)
            if result.get("error") or not req.save_history:
                return result, {}
            history_id = history_db.save(req.user_input, result, user_id=owner_id, job_id=job_id)
            if req.case_id is not None and req.candidate_id is not None:
                if owner_id is None or not case_db.link_appraisal(req.case_id, req.candidate_id, history_id, owner_id,
                                                                  result, payload.get("expected_candidate_inputs")):
                    raise ValueError("candidate_link_failed")
            return result, {"history_id": history_id}
        result = run_appraisal(payload["query"], payload["building_name"], progress_cb=set_step,
                               address=payload["address"], property_category=payload["category"],
                               property_detail=payload["detail"], area_sqm=payload["area_sqm"])
        if result.get("error"):
            return result, {}
        history_id = history_db.save(payload["query"], result, user_id=owner_id, job_id=job_id)
        if owner_id is None or not case_db.link_appraisal(payload["case_id"], payload["candidate_id"],
                                                           history_id, owner_id, result,
                                                           payload.get("expected_candidate_inputs")):
            raise ValueError("candidate_link_failed")
        return result, {"history_id": history_id, "case_id": payload["case_id"],
                        "candidate_id": payload["candidate_id"]}

    if task_type == "listing_collection":
        from backend.services.listing_observations import collect
        set_step("매물 원문 조회 및 시점 기록")
        return collect(owner_id, payload["url"], job_id=job_id), {}

    if task_type == "chat":
        from api.routes.chat import ChatRequest, _answer
        set_step("법령 검색 및 답변 생성")
        result = asyncio.run(_answer(ChatRequest.model_validate(payload["request"]),
                                     {"id": owner_id} if owner_id is not None else None))
        return result, {}

    if task_type == "concierge":
        from api.routes.concierge import send_message
        from schemas.concierge import ConciergeMessageRequest
        set_step("의도 확인 및 근거 검색")
        result = asyncio.run(send_message(ConciergeMessageRequest.model_validate(payload["request"]),
                                          {"id": owner_id}))
        return result.model_dump(mode="json"), {}
    raise ValueError("지원하지 않는 작업 유형")


def _heartbeat(client, stream_id: str, job_id: str, token: str, stop: threading.Event) -> None:
    while not stop.wait(30):
        try:
            client.xclaim(jobs.STREAM, jobs.GROUP, CONSUMER, min_idle_time=0, message_ids=[stream_id])
            client.expire(jobs._key(job_id), jobs.PENDING_TTL)
            client.eval("if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('EXPIRE', KEYS[1], 180) end return 0",
                        1, f"job-lock:{job_id}", token)
        except Exception:
            logger.exception("작업 임대 갱신 실패: %s", job_id)


def process_record(stream_id: str, fields: dict) -> None:
    client = get_redis()
    job_id = fields["job_id"]
    lock_key, token = f"job-lock:{job_id}", uuid.uuid4().hex
    if not client.set(lock_key, token, nx=True, ex=180):
        return
    stop = threading.Event()
    heartbeat = threading.Thread(target=_heartbeat, args=(client, stream_id, job_id, token, stop), daemon=True)
    heartbeat.start()
    try:
        job = jobs._load(job_id)
        if job is None or job["status"] in {"done", "error"}:
            client.xack(jobs.STREAM, jobs.GROUP, stream_id)
            client.xdel(jobs.STREAM, stream_id)
            return
        if job["status"] == "running" and fields["task_type"] in {"chat", "concierge"}:
            # 답변 저장과 작업 ACK가 서로 다른 저장소에 있어 자동 재실행은 대화를 중복시킬 수 있다.
            job["status"] = "error"
            job["error"] = "답변 생성 중 서버가 재시작됐습니다. 질문을 다시 보내주세요."
            job["finished_at"] = time.time()
            jobs._save(job_id, job, jobs.FINISHED_TTL)
            client.xack(jobs.STREAM, jobs.GROUP, stream_id)
            client.xdel(jobs.STREAM, stream_id)
            return
        job["status"] = "running"
        jobs._save(job_id, job, jobs.PENDING_TTL)

        def set_step(step: str) -> None:
            current = jobs._load(job_id) or job
            current["step"] = step
            jobs._save(job_id, current, jobs.PENDING_TTL)

        try:
            result, extra = run_task(fields["task_type"], json.loads(fields["payload"]),
                                     job["owner_id"], job_id, set_step)
            job = jobs._load(job_id) or job
            job["result"] = result
            job["extra"] = extra
            if isinstance(result, dict) and result.get("error"):
                job["status"], job["error"] = "error", str(result["error"])
            else:
                job["status"] = "done"
        except HTTPException as exc:
            job = jobs._load(job_id) or job
            job["status"], job["error"] = "error", str(exc.detail)
        except Exception:
            logger.exception("작업 실행 실패: %s", job_id)
            job = jobs._load(job_id) or job
            job["status"], job["error"] = "error", "작업을 완료하지 못했습니다. 다시 시도해주세요."
        job["finished_at"] = time.time()
        jobs._save(job_id, job, jobs.FINISHED_TTL)
        client.xack(jobs.STREAM, jobs.GROUP, stream_id)
        client.xdel(jobs.STREAM, stream_id)
    finally:
        stop.set()
        heartbeat.join(timeout=2)
        client.eval("if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0",
                    1, lock_key, token)


def ensure_group() -> None:
    try:
        get_redis().xgroup_create(jobs.STREAM, jobs.GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def serve() -> None:
    logging.basicConfig(level=logging.INFO)
    ensure_group()
    from api.operational_health import worker_heartbeat
    def pulse():
        while True:
            try:
                worker_heartbeat(CONSUMER)
            except Exception:
                logger.error("실행기 생존 신호 기록 실패")
            time.sleep(5)
    threading.Thread(target=pulse, daemon=True).start()
    client = get_redis()
    slots = threading.BoundedSemaphore(jobs.MAX_CONCURRENT)
    claim_cursor = "0-0"
    with ThreadPoolExecutor(max_workers=jobs.MAX_CONCURRENT) as pool:
        while True:
            slots.acquire()
            # 처리 중 프로세스가 종료되면 pending 항목을 다른 worker가 다시 가져간다.
            claim_cursor, pending, *_ = client.xautoclaim(
                jobs.STREAM, jobs.GROUP, CONSUMER, CLAIM_IDLE_MS,
                start_id=claim_cursor, count=1)
            records = pending or client.xreadgroup(jobs.GROUP, CONSUMER, {jobs.STREAM: ">"},
                                                    count=1, block=1000)
            messages = pending if pending else (records[0][1] if records else [])
            for stream_id, fields in messages:
                future = pool.submit(process_record, stream_id, fields)
                future.add_done_callback(lambda _: slots.release())
            if not messages:
                slots.release()


if __name__ == "__main__":
    serve()
