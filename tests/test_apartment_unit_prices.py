"""공동주택 공시가격 수집: PNU 변환, 호출 상한에서 멈추고 이어 하기, 저장·중복 갱신·상태 기록."""
from sqlalchemy import text

from backend.tools import ingest_apartment_unit_prices as ingest
from db.base import get_engine


def test_pnu_from_legal_dong_code_and_lot():
    assert ingest.to_pnu("1165010700", "20-43") == "1165010700100200043"
    assert ingest.to_pnu("1165010700", "123") == "1165010700101230000"
    assert ingest.to_pnu("1165010700", "산 7-1") == "1165010700200070001"
    assert ingest.to_pnu("1165010700", "20-43블록") is None and ingest.to_pnu("11650", "20-43") is None


def test_run_stops_at_call_budget_and_reports_remaining():
    calls = []
    def fetcher(pnu, year, key, domain):
        calls.append((pnu, year))
        return [{"x": 1}], 1, 2           # 필지마다 2쪽
    saved = []
    result = ingest.run([(f"p{i}", 2026) for i in range(10)], "k", "d", max_calls=6, workers=1, fetcher=fetcher,
                        saver=lambda *args: saved.append(args) or 1)
    assert result["calls"] >= 6 and result["remaining"] == 10 - len(calls) and result["remaining"] > 0


def test_run_stops_after_consecutive_failures():
    def failing(*args):
        raise RuntimeError("HTTP 429")
    result = ingest.run([(f"p{i}", 2026) for i in range(200)], "k", "d", max_calls=10_000, workers=2, fetcher=failing,
                        saver=lambda *args: 0)
    assert result["stopped"] and result["remaining"] > 0 and result["failed"] < 200


def test_store_upserts_units_and_records_status():
    with get_engine().begin() as connection:
        connection.execute(text("DELETE FROM apartment_unit_prices WHERE pnu = '1165010700100200043'"))
        connection.execute(text("DELETE FROM apartment_unit_price_fetches WHERE pnu = '1165010700100200043'"))
    item = {"aphusCode": "20113618", "aphusNm": "반포자이", "dongNm": "134", "hoNm": "2503", "floorNm": "25", "prvuseAr": "59.98",
            "pblntfPc": "2558000000", "ldCode": "1165010700", "mnnmSlno": "20-43", "lastUpdtDt": "2026-05-14"}
    assert ingest.store("1165010700100200043", 2026, [item, {**item, "pblntfPc": "0", "hoNm": "9999"}], 2) == 1
    assert ingest.store("1165010700100200043", 2026, [{**item, "pblntfPc": "2600000000"}], 1) == 1
    with get_engine().connect() as connection:
        price = connection.execute(text("SELECT official_price FROM apartment_unit_prices WHERE pnu='1165010700100200043' AND ho_name='2503'")).scalar()
        status = connection.execute(text("SELECT status, row_count FROM apartment_unit_price_fetches WHERE pnu='1165010700100200043' AND stdr_year=2026")).one()
    assert price == 2_600_000_000 and tuple(status) == ("done", 1)
    ingest.store("1165010700100200043", 2025, [], 0, "HTTP 500")
    assert ingest.pending(["1165010700100200043"], [2025, 2026], force=False) == [("1165010700100200043", 2025)]  # 실패만 다시
