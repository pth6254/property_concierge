"""실거래 최초 수집 시각: 월 재수집(삭제 후 삽입)에도 같은 거래는 처음 본 시각을 유지하고, 새로 신고된 거래만 지금 시각을 받는다."""
import time

from sqlalchemy import select

import transaction_store
from db.base import session_scope
from db.models import Transaction
from tests.conftest import truncate_tables

KEY = ("RTMSDataSvcAptTrade", "주거용", "11650", "202610")


def _trade(day, price, floor="8", **extra):
    return {"apt_name": "검증자이", "dong": "반포동", "jibun": "", "price": price, "area_sqm": 84.97, "floor": floor,
            "deal_year": "2026", "deal_month": "10", "deal_day": day, "is_cancelled": False} | extra


def _seen() -> dict:
    with session_scope() as session:
        rows = session.scalars(select(Transaction)).all()
        return {(row.deal_day, row.price, row.is_cancelled): row.first_seen_at for row in rows}


def test_recollection_keeps_first_seen_and_stamps_only_new_reports():
    truncate_tables(Transaction)
    transaction_store.put_month(*KEY, [_trade("3", 500000), _trade("3", 500000)])
    first = set(_seen().values())
    assert len(first) == 1 and None not in first
    first_seen = first.pop()
    later = time.time()

    # 이후 재수집: 기존 거래 하나가 해제되고 지번이 보완됐으며, 월말 계약이 새로 신고됐다.
    transaction_store.put_month(*KEY, [_trade("3", 500000, is_cancelled=True, jibun="1-1"),
                                       _trade("3", 500000, jibun="1-1"), _trade("29", 510000)])
    seen = _seen()
    assert seen[("3", 500000, True)] == first_seen and seen[("3", 500000, False)] == first_seen
    assert seen[("29", 510000, False)] >= later


def test_rows_from_before_tracking_stay_unknown_and_corrections_count_as_new():
    truncate_tables(Transaction)
    with session_scope() as session:  # 마이그레이션 전부터 있던 행: 최초 수집 시각 없음
        session.add(Transaction(endpoint=KEY[0], category=KEY[1], lawd_cd=KEY[2], deal_ym=KEY[3], **_trade("5", 480000)))
    before = time.time()
    # 같은 거래와, 금액·층이 다른 정정본(새 거래로 본다)
    transaction_store.put_month(*KEY, [_trade("5", 480000), _trade("5", 482000, floor="9")])
    seen = _seen()
    assert seen[("5", 480000, False)] is None
    assert seen[("5", 482000, False)] >= before
