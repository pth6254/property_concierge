"""변화 알림 조건: 분석 만료·원본 변경·매물 재확인·새 실거래를 기존 화면 기준으로 계산하고, 저장·읽음은 실제 Spring으로 확인한다."""
from datetime import datetime, timedelta

from backend.services import notification_conditions as rules
from tests.test_purchase_cases import client, _register

NOW = 1_800_000_000.0


def stamp(seconds_ago: float) -> str:
    return datetime.fromtimestamp(NOW - seconds_ago).strftime("%Y-%m-%d %H:%M:%S")


def candidate(**fields):
    base = {"id": 7, "name": "래미안퍼스티지", "alias": "", "status": "reviewing", "category": "아파트",
            "legal_region_code": "1165010700", "area_sqm": 84.9, "identity": {"area_basis": "exclusive"},
            "analyses": [], "source_status": None}
    return {**base, **fields}


def test_money_is_written_in_korean_units():
    assert rules.won(910_000_000) == "9억 1,000만원"
    assert rules.won(1_200_000_000) == "12억원"
    assert rules.won(35_000_000) == "3,500만원"
    assert rules.won(None) == "미확인"


def test_stale_analysis_is_split_into_expiry_and_changed_inputs():
    case = {"id": 3}
    expired = {"analysis_type": "rights", "status": "stale", "analyzed_at": stamp(8 * 86400), "expires_at": stamp(86400)}
    changed = {"analysis_type": "appraisal", "status": "stale", "analyzed_at": stamp(86400), "expires_at": stamp(-29 * 86400)}
    current = {"analysis_type": "simulation", "status": "completed", "analyzed_at": stamp(60), "expires_at": stamp(-13 * 86400)}
    found = rules._candidate_conditions(case, candidate(analyses=[expired, changed, current]), NOW)
    assert [(item["subject_key"], item["fingerprint"].split("|")[1]) for item in found] == [
        ("candidate:7:rights", "expired"), ("candidate:7:appraisal", "changed")]
    assert "유효기간(7일)이 지났습니다" in found[0]["body"] and "물건 정보가 바뀌어" in found[1]["body"]
    assert found[0]["link"] == "/cases/3#candidate-7" and found[0]["case_id"] == 3 and found[0]["property_id"] == 7


def test_source_change_lists_changed_values_and_missing_source():
    case = {"id": 3}
    changed = candidate(source_status={"status": "changed", "current": {"revision_id": 12}, "changes": {
        "asking_price": {"saved": 900_000_000, "current": 880_000_000}, "status": {"saved": "active", "current": "completed"}}})
    [item] = rules._candidate_conditions(case, changed, NOW)
    assert item["kind"] == "source_changed" and item["fingerprint"] == "rev:12:asking_price,status"
    assert "희망가 9억원 → 8억 8,000만원" in item["body"] and "거래 상태 거래 가능 → 거래 완료" in item["body"]
    [missing] = rules._candidate_conditions(case, candidate(source_status={"status": "missing"}), NOW)
    assert missing["fingerprint"] == "missing"
    # 재확인만 필요한 원본은 매물 재확인 알림이 맡으므로 여기서 중복으로 만들지 않는다.
    assert rules._candidate_conditions(case, candidate(source_status={"status": "needs_confirmation"}), NOW) == []


def test_trade_updates_use_first_collection_time_and_skip_unrecorded_trades():
    calls = []

    def find_trades(**kwargs):
        calls.append(kwargs)
        return {"complex_name": "래미안퍼스티지", "trades": [
            {"deal_date": "2026-10-15", "area_sqm": 84.9, "price_won": 910_000_000, "first_seen_at": NOW - 3600},
            {"deal_date": "2026-10-20", "area_sqm": 84.97, "price_won": 930_000_000, "first_seen_at": NOW - 2 * 86400},
            {"deal_date": "2026-09-01", "area_sqm": 84.9, "price_won": 880_000_000, "first_seen_at": NOW - 20 * 86400},  # 14일 밖
            {"deal_date": "2026-10-25", "area_sqm": 84.9, "price_won": 999_000_000, "first_seen_at": None},  # 기록 시작 전
        ]}
    case = {"id": 3}
    targets = [rules._trade_target(case, candidate(analyses=[{"analysis_type": "appraisal"}]), NOW),
               rules._trade_target(case, candidate(id=8), NOW)]
    found = rules._trade_conditions(targets, find_trades)
    assert len(calls) == 1, "같은 단지·면적은 한 번만 조회"
    assert [item["subject_key"] for item in found] == ["candidate:7:trades", "candidate:8:trades"]
    item = found[0]
    assert item["title"].endswith("실거래 2건 새로 반영") and item["fingerprint"] == str(int(NOW - 3600))
    assert "최근 계약 2026-10-20" in item["body"] and "9억 3,000만원" in item["body"] and "현재 시세가 아닙니다" in item["body"]
    assert "시세 분석을 다시 확인" in item["body"] and "시세 분석을 다시 확인" not in found[1]["body"]


def test_trade_targets_require_apartment_region_and_exclusive_area():
    case = {"id": 3}
    assert rules._trade_target(case, candidate(), NOW)["since"] == NOW - 14 * 86400
    for fields in ({"category": "오피스텔"}, {"legal_region_code": "11650"}, {"area_sqm": None},
                   {"identity": {"area_basis": "supply"}}, {"identity": {"area_basis": "unknown"}}):
        assert rules._trade_target(case, candidate(**fields), NOW) is None


def test_listing_reconfirmation_distinguishes_age_and_newer_collection():
    confirmed = datetime.fromtimestamp(NOW - 9 * 86400).astimezone().isoformat()
    listings = [
        {"id": 1, "name": "오래된 매물", "alias": "", "status": "active", "confirmed_at": confirmed, "needs_confirmation": True, "last_collection_at": None},
        {"id": 2, "name": "재수집 매물", "alias": "임장", "status": "active", "confirmed_at": confirmed, "needs_confirmation": True,
         "last_collection_at": NOW - 86400},
        {"id": 3, "name": "철회 매물", "alias": "", "status": "withdrawn", "confirmed_at": confirmed, "needs_confirmation": True, "last_collection_at": None},
        {"id": 4, "name": "최근 매물", "alias": "", "status": "active", "confirmed_at": confirmed, "needs_confirmation": False, "last_collection_at": None},
    ]
    found = rules._listing_conditions(listings, NOW)
    assert [item["listing_id"] for item in found] == [1, 2]
    assert "9일이 지났습니다" in found[0]["body"] and found[0]["fingerprint"].endswith("|age")
    assert found[1]["title"].startswith("임장") and "다시 수집한 기록" in found[1]["body"]
    assert found[0]["link"] == "/listings?listing_id=1#saved-listings"


def test_trade_overlay_exposes_first_collection_time():
    from datetime import date
    from db.base import session_scope
    from db.models import Transaction
    from backend.services.listing_trade_overlay import find_trades
    from tests.conftest import truncate_tables
    truncate_tables(Transaction)
    with session_scope() as session:
        session.add_all([Transaction(endpoint="RTMSDataSvcAptTrade", category="주거용", lawd_cd="11650", deal_ym="202609", price=300_000,
                                     area_sqm=84.9, floor="10", apt_name="메이플자이", deal_year="2026", deal_month="9", deal_day=str(day),
                                     bjdong_code="1165010700", is_cancelled=False, first_seen_at=seen)
                         for day, seen in ((5, 1_790_000_000.0), (9, None))])
    trades = find_trades(legal_region_code="1165010700", name="메이플자이", area_sqm=84.9, today=date(2026, 10, 1))["trades"]
    assert {trade["deal_date"]: trade["first_seen_at"] for trade in trades} == {"2026-09-09": None, "2026-09-05": 1_790_000_000.0}


def test_inbox_through_spring_reports_expired_analysis_and_resolves_after_rerun(client):
    """실제 Spring 저장·스냅샷과 Python 계산을 거쳐 만료 알림이 생기고, 다시 분석하면 해결되는지 확인한다."""
    from db.base import session_scope
    from db.models import CandidateAnalysis
    _register(client, "notification-owner@example.com")
    case_id = client.post("/api/cases", json={"title": "알림 확인"}).json()["id"]
    candidate_id = client.post(f"/api/cases/{case_id}/properties", json={
        "name": "알림 후보", "category": "아파트", "asking_price": 600_000_000}).json()["id"]
    saved = client.post("/api/simulation", json={"case_id": case_id, "candidate_id": candidate_id, "purchase_price": 600_000_000,
        "cash_available": 300_000_000, "loan_ratio": 0.5, "annual_interest_rate": 4.0, "loan_years": 30, "owned_homes": 1})
    assert saved.status_code == 200, saved.text
    assert client.get("/api/notifications").json()["items"] == []

    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    with session_scope() as session:
        analysis = session.query(CandidateAnalysis).filter_by(property_id=candidate_id, analysis_type="simulation").one()
        analysis.expires_at = past
    from db.redis_client import get_redis
    get_redis().flushdb()  # 동기화 최소 간격을 비운다
    inbox = client.get("/api/notifications").json()
    [item] = inbox["items"]
    assert item["kind"] == "analysis_expired" and item["title"] == "알림 후보 · 자금 분석 다시 확인"
    assert item["link"] == f"/cases/{case_id}#candidate-{candidate_id}" and inbox["unread_count"] == 1

    rerun = client.post("/api/simulation", json={"case_id": case_id, "candidate_id": candidate_id, "purchase_price": 600_000_000,
        "cash_available": 300_000_000, "loan_ratio": 0.5, "annual_interest_rate": 4.0, "loan_years": 30, "owned_homes": 1})
    assert rerun.status_code == 200
    get_redis().flushdb()
    assert client.get("/api/notifications").json()["items"] == []

    client.cookies.clear()
    _register(client, "notification-other@example.com")
    assert client.get("/api/notifications").json()["items"] == []
    assert client.post(f"/api/notifications/{item['id']}/read").status_code == 404
