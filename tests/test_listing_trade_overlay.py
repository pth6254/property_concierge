"""타임라인에 겹치는 동일 단지 실거래: 추측 연결·기간/면적 밖·해제 거래를 배제한다."""
from datetime import date

import pytest

from backend.services.listing_trade_overlay import find_trades
from db.models import Transaction
from tests.conftest import truncate_tables

TODAY = date(2026, 10, 1)


def trade(name="메이플자이", ym="202609", day="5", area=84.9, price=300_000, bjdong="1165010700", cancelled=False, floor="10", **kw):
    return Transaction(endpoint="RTMSDataSvcAptTrade", category="주거용", lawd_cd="11650", deal_ym=ym, price=price, area_sqm=area,
        floor=floor, apt_name=name, deal_year=ym[:4], deal_month=str(int(ym[4:])), deal_day=day, bjdong_code=bjdong,
        is_cancelled=cancelled, **kw)


@pytest.fixture()
def store():
    from db.base import session_scope
    truncate_tables(Transaction)
    def put(*rows):
        with session_scope() as session:
            session.add_all(rows)
    return put


def run(**kw):
    return find_trades(legal_region_code="1165010700", name="메이플자이", area_sqm=84.9, today=TODAY, **kw)


def test_same_complex_trades_are_filtered_by_period_area_cancellation_and_dong(store):
    store(trade(), trade(day="9", price=310_000), trade(ym="202301"),  # 24개월 밖
          trade(area=120), trade(cancelled=True), trade(name="다른단지"), trade(bjdong="1165010800"),
          trade(day="5"))  # 중복 신고
    result = run()
    assert result["available"] and result["match"] == "exact" and result["complex_name"] == "메이플자이"
    assert [t["deal_date"] for t in result["trades"]] == ["2026-09-09", "2026-09-05"]
    assert result["trades"][0]["price_won"] == 3_100_000_000
    assert result["data_through"] == "202609" and result["median_per_sqm_won"] > 0


def test_unmatched_ambiguous_or_missing_inputs_are_not_guessed(store):
    store(trade(name="래미안A단지"), trade(name="래미안B단지"))
    assert not find_trades(legal_region_code="1165010700", name="래미안", area_sqm=84.9, today=TODAY)["available"]
    assert "여러" in find_trades(legal_region_code="1165010700", name="래미안", area_sqm=84.9, today=TODAY)["reason"]
    assert not run()["available"]
    assert not find_trades(legal_region_code="", name="x", area_sqm=84.9)["available"]
    assert not find_trades(legal_region_code="1165010700", name="메이플자이", area_sqm=0)["available"]
    store(trade(ym="202301"))
    assert not run()["available"]  # 기간 밖 거래만 있으면 연결하지 않는다
    store(trade(area=120))
    wrong_area = run()
    assert not wrong_area["available"] and wrong_area["trades"] == [] and "면적" in wrong_area["reason"]


def test_unique_partial_name_is_flagged_not_called_exact(store):
    store(trade(name="메이플자이아파트"), trade(name="메이플자이", day="7"))
    assert run()["match"] == "exact"
    truncate_tables(Transaction)
    store(trade(name="메이플자이주상복합동", day="7"))
    partial = run()
    assert partial["match"] == "partial_unique" and partial["available"]
