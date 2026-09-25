"""
test_transaction_store.py — 실거래가 로컬 스토어 단위 테스트
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:password@localhost:5432/real_estate_db")

import transaction_store
from price_engine import _endpoint_name

SAMPLE = {
    "price": 150000, "area_sqm": 84.97, "area_pyeong": 25.7, "per_sqm": 1765,
    "floor": "15", "year_built": "2008", "dong": "반포동",
    "apt_name": "래미안퍼스티지", "deal_year": "2026", "deal_month": "6",
}

KEY = ("RTMSDataSvcAptTrade", "주거용", "11650", "202606")


@pytest.fixture
def store():
    """
    transactions/ingest_log 테이블을 비운 상태로 스토어 격리.

    이전에는 DB_PATH(SQLite 파일 경로)를 tmp_path로 monkeypatch해 테스트마다
    별개 파일을 썼다. Postgres 전환 후에는 관련 테이블만 비운다.
    """
    from db.models import IngestLog, Transaction
    from tests.conftest import truncate_tables

    truncate_tables(Transaction, IngestLog)
    transaction_store.init_store()
    return transaction_store


def test_miss_returns_none(store):
    assert store.get_month(*KEY) is None


def test_roundtrip(store):
    store.put_month(*KEY, [SAMPLE])
    rows = store.get_month(*KEY)
    assert rows is not None and len(rows) == 1
    assert rows[0]["price"] == 150000
    assert rows[0]["apt_name"] == "래미안퍼스티지"
    assert rows[0]["area_sqm"] == pytest.approx(84.97)


def test_empty_month_is_valid(store):
    """거래 0건 월은 [] — None(미적재)과 구분되어야 한다."""
    store.put_month(*KEY, [])
    assert store.get_month(*KEY) == []
    assert store.is_month_completed(*KEY)


def test_failed_month_is_retried(store):
    store.mark_month_started(*KEY)
    assert not store.is_month_completed(*KEY)
    store.mark_month_failed(*KEY, "일시적인 API 오류")
    assert not store.is_month_completed(*KEY)
    store.put_month(*KEY, [])
    assert store.is_month_completed(*KEY)


def test_completed_old_month_is_refetched_after_ttl(store):
    from sqlalchemy import update
    from db.base import session_scope
    from db.models import IngestLog

    old_key = (*KEY[:3], "202401")
    store.put_month(*old_key, [])
    with session_scope() as session:
        session.execute(
            update(IngestLog).where(IngestLog.deal_ym == "202401").values(fetched_at=0)
        )
    assert not store.should_skip_batch_month(*old_key)


def test_stale_recent_month_is_refetched(store):
    from datetime import datetime
    from sqlalchemy import update
    from db.base import session_scope
    from db.models import IngestLog

    recent_key = (*KEY[:3], datetime.now().strftime("%Y%m"))
    store.put_month(*recent_key, [])
    with session_scope() as session:
        session.execute(
            update(IngestLog).where(IngestLog.deal_ym == recent_key[-1]).values(fetched_at=0)
        )
    assert not store.should_skip_batch_month(*recent_key)


def test_replace_is_idempotent(store):
    store.put_month(*KEY, [SAMPLE, SAMPLE])
    store.put_month(*KEY, [SAMPLE])          # 재수집 → 교체
    rows = store.get_month(*KEY)
    assert len(rows) == 1


def test_key_isolation(store):
    """endpoint·category·지역·월이 다르면 서로 간섭하지 않는다."""
    store.put_month(*KEY, [SAMPLE])
    other = ("RTMSDataSvcOffiTrade", "주거용", "11650", "202606")
    assert store.get_month(*other) is None
    store.put_month(*other, [])
    assert store.get_month(*other) == []
    assert len(store.get_month(*KEY)) == 1


def test_stale_entry_returns_none(store):
    from sqlalchemy import update

    from db.base import session_scope
    from db.models import IngestLog

    store.put_month(*KEY, [SAMPLE])
    # fetched_at을 TTL 최대치(30일) 이전으로 강제 → 만료 판정
    with session_scope() as session:
        session.execute(
            update(IngestLog).values(fetched_at=time.time() - transaction_store.TTL_COMPLETE_MONTH - 1)
        )
    assert store.get_month(*KEY) is None


def test_ttl_policy():
    """완결 월은 30일, 최근 월은 12시간 TTL."""
    from datetime import datetime

    now = datetime.now()
    current_ym = now.strftime("%Y%m")
    old_ym     = f"{now.year - 1}{now.month:02d}"

    assert transaction_store._ttl_for(current_ym) == transaction_store.TTL_RECENT_MONTH
    assert transaction_store._ttl_for(old_ym)     == transaction_store.TTL_COMPLETE_MONTH


def test_endpoint_name():
    url = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
    assert _endpoint_name(url) == "RTMSDataSvcAptTrade"
