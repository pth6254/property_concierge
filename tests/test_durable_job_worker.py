"""실행 프로세스가 사라진 작업을 다른 소비자가 가져오고 결과를 중복 저장하지 않는지 확인한다."""
import uuid

from tests.test_purchase_cases import client, _register


def test_pending_stream_job_is_recovered_by_another_worker(client, monkeypatch):
    from api import jobs, job_worker

    stream = f"property-jobs-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(jobs, "STREAM", stream)
    monkeypatch.setattr(jobs, "GROUP", "recovery")
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    job_worker.ensure_group()
    called = []
    monkeypatch.setattr(job_worker, "run_task", lambda task_type, payload, owner_id, job_id, set_step:
                        (called.append((task_type, payload, owner_id)) or {"ok": True}, {}))
    owner_id = _register(client, "recovered-worker@example.com")
    job_id = jobs.create_task("fixture", {"value": 7}, owner_id=owner_id)
    redis = jobs.get_redis()
    abandoned = redis.xreadgroup(jobs.GROUP, "terminated-worker", {stream: ">"}, count=1)[0][1]
    assert abandoned[0][1]["job_id"] == job_id
    claimed = redis.xautoclaim(stream, jobs.GROUP, "replacement-worker", 0, "0-0", count=1)[1]
    assert claimed[0][0] == abandoned[0][0]
    job_worker.process_record(*claimed[0])
    assert jobs.get(job_id, requester_id=owner_id)["status"] == "done"
    assert jobs.get(job_id, requester_id=owner_id)["result"] == {"ok": True}
    assert called == [("fixture", {"value": 7}, owner_id)]
    # ACK 이후 같은 메시지를 다시 전달해도 실행 결과를 중복 생성하지 않는다.
    job_worker.process_record(*claimed[0])
    assert len(called) == 1
    redis.delete(stream, jobs._key(job_id))


def test_appraisal_history_save_is_idempotent_for_job(client):
    from api import history_db
    from db.base import session_scope
    from db.models import HistoryRecord
    from sqlalchemy import select

    owner_id = _register(client, "idempotent-history@example.com")
    first = history_db.save("첫 입력", {"analysis_result": {"estimated_value": 100}}, user_id=owner_id,
                            job_id="replayed-appraisal-1")
    second = history_db.save("다른 재실행 결과", {"analysis_result": {"estimated_value": 200}}, user_id=owner_id,
                             job_id="replayed-appraisal-1")
    assert first == second
    with session_scope() as session:
        records = session.scalars(select(HistoryRecord).where(HistoryRecord.job_id == "replayed-appraisal-1")).all()
        assert len(records) == 1
        assert records[0].result["analysis_result"]["estimated_value"] == 100


def test_interrupted_chat_does_not_generate_second_answer(client, monkeypatch):
    from api import jobs, job_worker

    stream = f"property-jobs-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(jobs, "STREAM", stream)
    monkeypatch.setattr(jobs, "GROUP", "chat-recovery")
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    job_worker.ensure_group()
    owner_id = _register(client, "chat-restart@example.com")
    job_id = jobs.create_task("chat", {"request": {"message": "질문"}}, owner_id=owner_id)
    redis = jobs.get_redis()
    record = redis.xreadgroup(jobs.GROUP, "stopped", {stream: ">"}, count=1)[0][1][0]
    job = jobs._load(job_id)
    job["status"] = "running"
    jobs._save(job_id, job, jobs.PENDING_TTL)
    monkeypatch.setattr(job_worker, "run_task", lambda *args: (_ for _ in ()).throw(
        AssertionError("대화가 중복 생성되면 안 됩니다")))
    job_worker.process_record(*record)
    result = jobs.get(job_id, requester_id=owner_id)
    assert result["status"] == "error" and "다시 보내주세요" in result["error"]
    redis.delete(stream, jobs._key(job_id))
