"""세그먼트 등록표와 연립·다세대(R-RH) 비교사례 단계의 누수 방지 규칙."""
from datetime import date

from backend.valuation.segments import SEGMENTS, resolve
from backend.valuation.segments.row_house import ComparableIndex, MarketIndex, normalize


def _row(i, day, jibun="593-63", dong="방화동", area=40.0, price=29000, year=2018, cancelled=False, kind="중개거래"):
    return {"id": i, "lawd_cd": "11500", "dong": dong, "jibun": jibun, "deal_year": day.year, "deal_month": day.month,
            "deal_day": day.day, "area_sqm": area, "price": price, "floor": "3", "year_built": str(year),
            "land_area_sqm": 20.0, "building_use": "다세대", "transaction_type": kind, "is_cancelled": cancelled}


def test_registry_covers_each_subtype_once_per_scope_and_keeps_current_status():
    assert resolve("apartment").id == "R-APT" and resolve("apartment").status == "active"
    assert resolve("row_house").id == "R-RH" and resolve("row_house").status == "withheld"
    assert resolve("commercial", "whole_building").id == "C-BLDG"
    assert resolve("commercial", "single_unit").id == "C-UNIT"
    assert resolve("factory").status == "unsupported"
    assert resolve("unknown") is None
    assert len({segment.id for segment in SEGMENTS}) == len(SEGMENTS)


def test_normalize_drops_cancelled_missing_jibun_and_duplicate_reports_and_converts_manwon():
    rows = [_row(1, date(2026, 1, 5)), _row(2, date(2026, 1, 5)), _row(3, date(2026, 2, 1), cancelled=True),
            _row(4, date(2026, 2, 1), jibun="")]
    trades = normalize(rows)
    assert [t.id for t in trades] == [1]
    assert trades[0].price == 290_000_000


def test_evidence_uses_only_earlier_trades_and_never_the_target_itself():
    rows = [_row(1, date(2025, 6, 1), price=27000), _row(2, date(2025, 9, 1), price=28000),
            _row(3, date(2026, 3, 1), price=30000), _row(4, date(2026, 5, 1), price=99000)]  # 대상보다 늦은 거래
    trades = normalize(rows)
    index = ComparableIndex(trades, MarketIndex(trades))
    target = next(t for t in trades if t.id == 3)
    evidence = index.evidence(target)
    assert evidence.level == "L1" and evidence.l1_count == 2  # id 1·2만. 자신(3)과 이후 거래(4)는 제외
    assert evidence.estimate is not None and abs(evidence.estimate - target.log_per_sqm) < .2


def test_similar_trades_in_the_same_dong_and_block_are_separate_from_the_same_building():
    rows = [_row(i, date(2026, 1, i), jibun=f"593-{i}", year=2017) for i in range(1, 6)]
    rows.append(_row(10, date(2026, 4, 1), jibun="593-99", year=2018))
    trades = normalize(rows)
    evidence = ComparableIndex(trades, MarketIndex(trades)).evidence(next(t for t in trades if t.id == 10))
    assert evidence.level == "L2" and evidence.l1_count == 0
    assert evidence.l2_count == 5 and evidence.block_count == 5   # 같은 본번(593) 블록


def test_without_any_comparable_the_level_is_l3_and_no_estimate_is_made():
    trades = normalize([_row(1, date(2026, 4, 1))])
    evidence = ComparableIndex(trades, MarketIndex(trades)).evidence(trades[0])
    assert evidence.level == "L3" and evidence.estimate is None


def test_policy_records_segment_without_changing_result_kind():
    from backend.valuation.policy import plan
    state = {"raw_inputs": {"property_category": "주거용", "property_detail": "연립다세대", "area_sqm": 40.0,
                            "address": "서울특별시 강서구 방화동 593-63", "appraisal_date": "20261001",
                            "valuation_context": {"scope": "single_unit", "area_basis": "exclusive", "transaction_type": "sale"}}}
    assessment = plan(state)
    assert assessment["segment"] == "R-RH"
    assert assessment["result_kind"] == "withheld"
