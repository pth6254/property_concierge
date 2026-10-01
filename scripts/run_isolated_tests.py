"""서비스 DB와 분리된 PostgreSQL·Redis에서 마이그레이션과 pytest를 실행한다."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)


def main() -> int:
    database_url = os.getenv("TEST_DATABASE_URL", "")
    if not database_url:
        password = os.getenv("POSTGRES_PASSWORD", "")
        if not password:
            raise SystemExit("POSTGRES_PASSWORD 또는 TEST_DATABASE_URL이 필요합니다.")
        database_url = URL.create(
            "postgresql", username=os.getenv("POSTGRES_USER", "postgres"), password=password,
            host=os.getenv("TEST_POSTGRES_HOST", "localhost"), port=int(os.getenv("TEST_POSTGRES_PORT", "5432")),
            database="real_estate_test",
        ).render_as_string(hide_password=False)
    parsed = make_url(database_url)
    if parsed.drivername not in {"postgresql", "postgresql+psycopg2"} or parsed.database != "real_estate_test":
        raise SystemExit("TEST_DATABASE_URL은 real_estate_test PostgreSQL DB만 가리켜야 합니다.")
    redis_url = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")
    if urlsplit(redis_url).path != "/15":
        raise SystemExit("TEST_REDIS_URL은 격리된 Redis DB 15를 가리켜야 합니다.")

    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.exec_driver_sql(
                "SELECT 1 FROM pg_database WHERE datname = 'real_estate_test'"
            ).scalar()
            if not exists:
                connection.exec_driver_sql("CREATE DATABASE real_estate_test")
    finally:
        admin.dispose()

    from redis import Redis

    Redis.from_url(redis_url).flushdb()
    env = os.environ.copy()
    env.update({
        "TEST_DATABASE_URL": database_url, "DATABASE_URL": database_url,
        "TEST_REDIS_URL": redis_url, "REDIS_URL": redis_url,
        "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false",
        "DISABLE_RATE_LIMIT": "1", "APP_ENV": "development",
        "JWT_SECRET_KEY": "isolated-test-secret-not-used-in-production",
        # 실행기가 별도 Spring을 만들기 전까지 서비스 주소를 상속하지 않는다.
        "CORE_STORAGE_URL": "", "REQUIRE_INTERNAL_SERVICE_AUTH": "0", "CORE_HEALTH_URL": "",
    })
    print("격리 DB real_estate_test에 마이그레이션을 적용합니다.", flush=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)
    return subprocess.call([sys.executable, "scripts/run_spring_tests.py", "--pytest",
                            *(sys.argv[1:] or ["tests/", "-q"])], cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
