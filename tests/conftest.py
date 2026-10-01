"""
conftest.py — pytest 공통 설정

backend/와 프로젝트 루트를 sys.path에 추가해
테스트에서 모든 모듈을 직접 import할 수 있게 한다.
"""

import sys
import os
from urllib.parse import urlsplit, unquote


# 일부 통합 테스트가 테이블을 비운다. 기본 서비스 DB를 암묵적으로 사용하면
# 실거래·법령·사용자 데이터까지 삭제되므로 명시적인 격리 DB만 허용한다.
_test_database_url = os.getenv("TEST_DATABASE_URL", "")
_test_redis_url = os.getenv("TEST_REDIS_URL", "")
_database = urlsplit(_test_database_url)
_redis = urlsplit(_test_redis_url)
if _database.scheme not in {"postgresql", "postgresql+psycopg2"} or unquote(_database.path.lstrip("/")) != "real_estate_test":
    raise RuntimeError("pytest는 TEST_DATABASE_URL=postgresql://.../real_estate_test 격리 DB가 필요합니다.")
if _redis.scheme not in {"redis", "rediss"} or _redis.path != "/15":
    raise RuntimeError("pytest는 TEST_REDIS_URL=redis://.../15 격리 Redis DB가 필요합니다.")
_core = os.getenv("CORE_STORAGE_URL", "").strip()
if not _core or _core != os.getenv("TEST_CORE_URL", "").strip():
    raise RuntimeError("pytest는 서비스 Spring 저장 주소를 사용할 수 없습니다. scripts/run_isolated_tests.py를 사용하세요")
import requests
try:
    _storage = requests.get(_core + "/internal/v1/testing/storage",
        headers={"X-Internal-Service-Key": os.environ["INTERNAL_SERVICE_SECRET"]}, timeout=5)
    if _storage.status_code != 200 or _storage.json() != {"database": "real_estate_test", "redis_database": 15}:
        raise RuntimeError("격리 Spring 저장소 검증 실패")
except (requests.RequestException, KeyError, ValueError) as _error:
    raise RuntimeError("격리 Spring 저장소에 연결할 수 없습니다") from _error
os.environ["DATABASE_URL"] = _test_database_url
os.environ["REDIS_URL"] = _test_redis_url

_root    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_intelligence = os.path.join(_root, "services", "intelligence")
_backend = os.path.join(_intelligence, "backend")

for _p in [_backend, _intelligence, _root]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def truncate_tables(*models) -> None:
    """
    지정한 SQLAlchemy 모델의 테이블을 비운다.

    PostgreSQL 전환 전에는 SQLite 파일을 tmp_path로 monkeypatch해서 테스트마다
    DB를 통째로 격리했다 (test_access_control.py, test_transaction_store.py,
    test_rights_and_chat.py 가 이 패턴을 썼다). 이제 모든 워커가 같은 Postgres
    인스턴스를 보므로 파일 스와핑 대신 관련 테이블만 비워 격리한다 — 이 프로젝트
    데이터 규모(테스트용 몇 건)에서는 TRUNCATE로 충분하고 스키마 재생성보다 빠르다.
    DATABASE_URL이 필요하므로, DB에 실제로 접근하는 테스트에서만 호출할 것.
    """
    from db.base import init_db, session_scope

    init_db()
    with session_scope() as session:
        for model in models:
            session.query(model).delete()


import pytest


@pytest.fixture(autouse=True)
def isolated_http_job_worker(request):
    """HTTP 회귀 테스트의 모의 AI를 실제 큐·저장 계약과 연결한다. 운영 코드에는 테스트 분기를 두지 않는다."""
    if "client" not in request.fixturenames or request.node.path.name == "test_durable_job_worker.py":
        yield
        return
    import threading
    from api import jobs, job_worker
    from db.redis_client import get_redis
    original = jobs.create_task
    threads = []
    started = set()
    job_worker.ensure_group()
    def launch(job_id):
        if job_id in started:
            return
        started.add(job_id)
        redis = get_redis()
        record = next((entry for entry in redis.xrange(jobs.STREAM) if entry[1].get("job_id") == job_id), None)
        if record is None:
            raise AssertionError("접수된 작업이 실제 Redis Stream에 없습니다")
        def execute():
            job_worker.process_record(*record)
            redis.xdel(jobs.STREAM, record[0])
        thread = threading.Thread(target=execute)
        threads.append(thread)
        thread.start()
    def submit(*args, **kwargs):
        job_id = original(*args, **kwargs)
        launch(job_id)
        return job_id
    with pytest.MonkeyPatch.context() as worker_patch:
        worker_patch.setattr(jobs, "create_task", submit)
        worker_patch.setattr('tests.service_client.on_job_submitted', launch)
        yield
        for thread in threads:
            thread.join(timeout=30)
            assert not thread.is_alive(), "격리 실행기가 종료되지 않았습니다"
