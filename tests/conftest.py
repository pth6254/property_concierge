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
os.environ["DATABASE_URL"] = _test_database_url
os.environ["REDIS_URL"] = _test_redis_url

_root    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_backend = os.path.join(_root, "backend")

for _p in [_backend, _root]:
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
