"""공식 필지 보완은 거래를 삭제하거나 금액을 변경하지 않아야 한다."""
import time
import xml.etree.ElementTree as ET

import pytest
from sqlalchemy import select

from db.base import session_scope
from db.models import ComplexCatalog, Transaction
from services import complex_parcel_service as parcels
from tests.conftest import truncate_tables


@pytest.mark.parametrize("value,expected", [("0012-03", "12-3"), ("산12-0", "산 12"),
                                          ("12**", ""), ("서울 상계동", ""), (None, "")])
def test_parcel_normalization_never_guesses_masked_numbers(value, expected):
    assert parcels.normalize_parcel(value) == expected


def test_parser_and_store_preserve_official_parcel():
    from price_engine import _parse_items
    import transaction_store
    truncate_tables(Transaction)
    item = ET.fromstring("<item><aptNm>검증단지</aptNm><umdNm>상계동</umdNm><jibun>666-1</jibun>"
        "<dealAmount>50,000</dealAmount><excluUseAr>84</excluUseAr>"
        "<dealYear>2026</dealYear><dealMonth>7</dealMonth></item>")
    parsed = _parse_items([item], "주거용", "아파트", "11350")
    transaction_store.put_month("RTMSDataSvcAptTrade", "주거용", "11350", "202607", parsed)
    stored = transaction_store.get_month("RTMSDataSvcAptTrade", "주거용", "11350", "202607")
    assert stored[0]["jibun"] == "666-1" and stored[0]["price"] == 50000


def test_backfill_preserves_rows_money_and_ambiguous_or_other_region_records(monkeypatch):
    import price_engine
    truncate_tables(Transaction)
    with session_scope() as session:
        rows = [Transaction(endpoint="RTMSDataSvcAptTrade", category="주거용", lawd_cd=lawd,
                deal_ym="202607", dong="상계동", apt_name=name, price=price, is_cancelled=False)
                for lawd, name, price in [("11350", "검증단지", 50000), ("11350", "검증단지", 55000),
                                          ("11350", "동명단지", 80000), ("11680", "검증단지", 90000)]]
        session.add_all(rows)
        session.flush()
        original = {row.id: row.price for row in rows}
    samples = [{"dong": "상계동", "apt_name": name, "jibun": parcel, "is_cancelled": cancelled}
               for name, parcel, cancelled in [("검증단지", "666", False), ("검증단지", "999", True),
                                               ("동명단지", "1", False), ("동명단지", "2", False)]]
    monkeypatch.setattr(price_engine, "MOLIT_API_KEY", "test-key")
    monkeypatch.setattr(price_engine, "_fetch_one_month_api", lambda *args: samples)
    monkeypatch.setattr(parcels, "cache_get", lambda *a, **kw: None)
    monkeypatch.setattr(parcels, "cache_set", lambda *a, **kw: None)
    index = parcels.official_month_parcels("11350", "202607")
    assert len(index) == 2
    with session_scope() as session:
        rows = session.scalars(select(Transaction)).all()
        assert {row.id: row.price for row in rows} == original
        for row in rows:
            assert row.jibun == ("666" if row.lawd_cd == "11350" and row.apt_name == "검증단지" else None)


def test_partial_legacy_catalog_entry_is_rechecked_even_before_expiry(monkeypatch):
    from services import complex_address_service as addresses
    from services.complex_catalog import lookup
    truncate_tables(ComplexCatalog, Transaction)
    with session_scope() as session:
        row = ComplexCatalog(lawd_code="11350", dong="상계동", canonical_name=addresses._name("검증단지"),
            name="검증단지", region="서울 노원구", aliases=["검증단지"],
            address={"address_status": "matched", "jibun_address": "서울 노원구 상계동 666", "road_address": ""},
            status="matched", checked_at=time.time())
        session.add(row)
        session.flush()
        original_id = row.id
    calls = []
    def resolve(*args, **kwargs):
        calls.append(1)
        return {"address_status": "matched", "jibun_address": "서울 노원구 상계동 666", "road_address": "서울 노원구 노원로 564"}
    monkeypatch.setattr(addresses, "resolve_complex_address", resolve)
    result = lookup("서울 노원구", "11350", "상계동", "검증단지")
    assert result["complex_id"] == original_id and calls == [1]
    assert result["road_address"]


def test_source_month_is_fetched_once_for_several_candidates(monkeypatch):
    monkeypatch.setattr(parcels, "known_parcels", lambda *args: [])
    calls = []
    def load(lawd, month):
        calls.append((lawd, month))
        return [{"dong": "상계동", "name": "단지1", "jibuns": ["666"]}]
    monkeypatch.setattr(parcels, "official_month_parcels", load)
    items = [{"complex_name": name, "dong": "상계동", "last_deal_ym": "202607"} for name in ["단지1", "단지2"]]
    parcels.attach_official_parcels(items, "11350")
    assert calls == [("11350", "202607")]
    assert items[0]["official_jibuns"] == ["666"] and items[1]["official_jibuns"] == []
