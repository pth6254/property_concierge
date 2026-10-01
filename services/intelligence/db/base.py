"""
db/base.py — SQLAlchemy 엔진·세션

이전에는 auth/history/activity/cache/transactions/chat_corpus 가 각자
SQLite 파일(threading.Lock 으로 직렬화)을 열었다. uvicorn을 --workers N
으로 띄우면 워커마다 프로세스가 분리되어 각자 다른 파일을 보게 되므로
스케일아웃이 불가능했다 — 이 문제를 풀기 위해 단일 PostgreSQL 인스턴스로
모든 워커가 같은 데이터를 보게 한다.

DATABASE_URL 이 없으면 기동을 막는다. SQLite 폴백을 일부러 두지 않았다 —
"로컬은 SQLite, 운영은 Postgres"로 갈라지면 로컬에서 검증되지 않은 쿼리가
운영에서만 깨지는 사고가 반복되기 쉽다. 로컬 개발도 docker compose 로
Postgres·Redis를 띄우는 것을 기본 흐름으로 삼는다.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


# 엔진은 지연 생성한다 — 모듈 임포트 시점이 아니라 실제로 DB에 접근하는 첫 호출에서
# DATABASE_URL을 확인한다. 그래야 DB를 전혀 쓰지 않는 테스트(스코어링·시뮬레이션
# 계산 단위 테스트 등)가 Postgres 없이도 그대로 동작한다. auth_db 등 각 모듈은
# 함수 호출 시점에 session_scope()를 여는 기존 `_conn()` 패턴을 그대로 유지한다.
@lru_cache(maxsize=1)
def get_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 설정되지 않았습니다. "
            "PostgreSQL 접속 문자열을 지정하세요 "
            "(예: postgresql://postgres:password@localhost:5432/real_estate_db). "
            "로컬 개발은 `docker compose up pgvector` 로 컨테이너를 먼저 띄우세요."
        )
    return create_engine(database_url, pool_pre_ping=True, future=True, pool_timeout=3,
                         connect_args={"connect_timeout": 3})


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """세션 1개 = 트랜잭션 1개. with 블록이 정상 종료되면 commit, 예외면 rollback."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_initialized = False


def init_db() -> None:
    """앱 테이블 생성 (idempotent — 기존 각 모듈의 init() 이 하던 CREATE TABLE IF NOT EXISTS 와 동등).

    스키마 변경 이력은 Alembic(db/migrations/)이 관리한다. Dockerfile.backend는
    uvicorn을 띄우기 "전에" `alembic upgrade head`를 단일 프로세스로 먼저
    실행한다 — 정상 배포 경로라면 여기 도달했을 때 테이블은 이미 존재한다.

    그럼에도 create_all()을 lifespan에 남겨둔 이유는 안전망이다: alembic을
    거치지 않고 `uvicorn api.main:app`을 직접 실행하는 로컬 개발·테스트
    환경(pytest의 TestClient 등)에서는 이게 유일한 스키마 생성 경로다.
    두 메커니즘이 같은 결과(9개 테이블)를 만들도록 db/migrations/versions/의
    베이스라인 마이그레이션은 db/models.py 를 대상으로 autogenerate 했다.
    새 모델을 추가·변경했다면 `alembic revision --autogenerate`로 마이그레이션도
    함께 만들 것 — create_all()은 컬럼 삭제·타입 변경처럼 alembic이 다루는
    변경은 반영하지 못한다.

    `_initialized` 는 프로세스별 플래그다 — uvicorn을 --workers N 으로 띄우면
    워커마다 별도 프로세스라 최초 기동 시 N개가 동시에 여기 진입할 수 있다.
    SQLAlchemy의 create_all은 "테이블 없음 확인 → CREATE TABLE"을 원자적으로
    하지 않으므로, 여러 워커가 동시에 같은 결론(없음)에 도달하면 뒤늦게 DDL을
    커밋하는 쪽이 죽는다 — 테이블 자체는 ProgrammingError(DuplicateTable,
    Postgres 42P07)로, SERIAL 컬럼의 시퀀스는 IntegrityError(UniqueViolation)로
    실패한다(4 워커로 재현 시 매번 재현됨, race_test 스크래치 DB로 검증).
    두 에러 모두 메시지에 "already exists"가 포함되므로 그 경우만 무시한다
    — 목표(테이블이 존재한다)는 어느 워커가 만들었든 이미 달성됐기 때문이다.
    Alembic을 먼저 돌리는 배포 경로에서는 애초에 이 경합 자체가 발생하지
    않는다(단일 프로세스가 먼저 끝내므로) — 이 방어 코드는 alembic 없이
    직접 uvicorn --workers N 을 띄우는 예외적 경로를 위한 이중 안전망이다.
    """
    global _initialized
    if _initialized:
        return
    from db import models  # noqa: F401  (Base.metadata 에 모델을 등록하기 위한 임포트)
    try:
        Base.metadata.create_all(bind=get_engine())
    except (ProgrammingError, IntegrityError) as e:
        if "already exists" not in str(e.orig):
            raise
    _initialized = True
