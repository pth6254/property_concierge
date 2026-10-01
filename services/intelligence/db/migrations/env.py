import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# 프로젝트 루트를 sys.path에 추가 — db.base / db.models 를 import 하기 위함.
# (alembic.ini의 prepend_sys_path = . 가 실행 위치에 따라 못 잡는 경우 대비)
_MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT   = os.path.dirname(os.path.dirname(_MIGRATIONS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# 접속 문자열은 다른 모든 DB 모듈과 동일하게 DATABASE_URL 환경변수를 쓴다.
# alembic.ini에 하드코딩하지 않는 이유는 db/base.py의 주석과 동일 —
# 비밀번호를 저장소에 남기지 않기 위해서다.
_database_url = os.getenv("DATABASE_URL", "")
if not _database_url:
    raise RuntimeError(
        "DATABASE_URL 환경변수가 설정되지 않았습니다. "
        "예: postgresql://postgres:password@localhost:5432/real_estate_db"
    )
config.set_main_option("sqlalchemy.url", _database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# db/models.py 의 모든 모델을 Base.metadata 에 등록시키기 위해 import 한다
# (import 하지 않으면 autogenerate가 새 모델을 인식하지 못한다).
from db import models  # noqa: E402,F401
from db.base import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
