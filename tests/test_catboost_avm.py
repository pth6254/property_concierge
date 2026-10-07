"""모델 정확도를 가상 자료로 주장하지 않고 시간 분리·비교 분모·아티팩트 계약을 검사한다."""
from copy import deepcopy
from dataclasses import replace
import json
import math

import pytest

from backend.valuation.catboost_avm import CatBoostAvm, complex_key, feature_values
from evaluation.catboost_avm import ComparisonConfig, comparison_metrics, evaluate, load_transactions, select_targets, split_rows


def transaction(identifier=1, month="202604", region="11650", **values):
    return dict(id=identifier, deal_ym=month, lawd_cd=region, price=50000, area_sqm=84.9,
                floor="10", year_built="2010", dong="검증동", apt_name="검증단지", jibun="1-1",
                bjdong_code=region + "10100", is_cancelled=False) | values


def dataset():
    return [transaction(index, month, region, area_sqm=area, price=area * 600)
            for index, (month, region, area) in enumerate(
                (m, r, a) for m in ("202604", "202605", "202606", "202607", "202608")
                for r in ("11650", "11350") for a in (50, 84, 110))]


def config(**values):
    return replace(ComparisonConfig("202607", "202608", train_months=2, max_cases=12,
                   min_train=2, min_validation=2, min_paired=4, min_region_cases=2), **values)


class FeatureOnlyModel:
    def fit(self, train, validation):
        self.train, self.validation = deepcopy(train), deepcopy(validation)
        return self

    def predict(self, rows):
        return [row["area_sqm"] * 600 for row in rows]


def baseline(target, history, code, name):
    assert set(history) <= {"202604", "202605", "202606"}
    assert all(row["deal_ym"] < "202607" for rows in history.values() for row in rows)
    return dict(estimated=True, estimated_manwon=target["price"] * 1.1, match_level="same_complex",
                comparable_count=3, build_year_band="2000to2014", prior_months=sorted(history))


def test_price_and_price_derived_values_never_enter_model_features():
    row = transaction()
    contaminated = row | {"price": 99999999, "per_sqm": 9999999, "asking_price": 9999999, "estimated_value": 1}
    assert feature_values(row) == feature_values(contaminated)
    assert complex_key(row) != complex_key(row | {"lawd_cd": "11350"})
    assert complex_key(row) != complex_key(row | {"jibun": "1-2"})
    missing = feature_values(row | {"floor": None, "year_built": "2099"})
    assert math.isnan(missing[1]) and math.isnan(missing[2])


def test_temporal_split_excludes_cancellations_bad_prices_and_future_rows():
    rows = dataset()
    rows += [transaction(900, "202604", is_cancelled=True), transaction(901, "202609"),
             transaction(902, "202604", price=float("inf")), transaction(903, "202604", area_sqm=0),
             transaction(904, "202613")]
    groups, excluded = split_rows(rows, config())
    assert {r["deal_ym"] for r in groups["train"]} == {"202604", "202605"}
    assert {r["deal_ym"] for r in groups["validation"]} == {"202606"}
    assert {r["deal_ym"] for r in groups["test"]} == {"202607", "202608"}
    assert excluded == {"cancelled": 1, "outside_period": 1, "invalid_price_or_area": 2, "invalid_month": 1}
    with pytest.raises(ValueError, match="최소 표본"):
        split_rows(rows, config(min_train=1000))


def test_target_sample_is_stable_and_covers_regions_months_and_area_bands():
    groups, _ = split_rows(dataset(), config())
    selected = select_targets(groups["test"], config(max_cases=8))
    assert selected == select_targets(list(reversed(groups["test"])), config(max_cases=8))
    assert len(selected) == 8
    assert {r["lawd_cd"] for r in selected} == {"11650", "11350"}
    assert {r["deal_ym"] for r in selected} == {"202607", "202608"}
    assert {r["area_sqm"] for r in selected} == {50, 84, 110}


def test_models_use_same_held_out_targets_and_no_test_month_enters_training():
    rows = dataset()
    original = deepcopy(rows)
    model = FeatureOnlyModel()
    result, _ = evaluate(rows, {"11650": "서초", "11350": "노원"}, config(), model=model, baseline=baseline)
    assert rows == original
    assert result["status"] == "pass"
    assert max(r["deal_ym"] for r in model.train) < min(r["deal_ym"] for r in model.validation) < "202607"
    records = result["details"]["records"]
    assert {r["transaction_id"] for r in records} == {r["id"] for r in rows if r["deal_ym"] >= "202607"}
    assert result["details"]["scores"]["paired"]["count"] == 12
    assert result["metrics"]["catboost_mape"] == 0
    assert result["metrics"]["baseline_mape"] == pytest.approx(.1)
    assert result["details"]["deployment"] == "evaluation_only"


def test_missing_baseline_prices_remain_in_coverage_and_block_quality_gate():
    def absent(*args):
        return baseline(*args) | {"estimated": False, "estimated_manwon": 0}
    result, _ = evaluate(dataset(), {"11650": "서초"}, config(), model=FeatureOnlyModel(), baseline=absent)
    assert result["status"] == "fail"
    scores = result["details"]["scores"]
    assert scores["baseline"]["targets"] == 12 and scores["baseline"]["coverage"] == 0
    assert scores["catboost"]["coverage"] == 1
    assert scores["paired"]["count"] == 0 and scores["paired"]["catboost"]["mape"] is None
    invalid = comparison_metrics([dict(actual_manwon=100, baseline_manwon=float("nan"), catboost_manwon=100)])
    assert invalid["paired"]["count"] == 0


def test_requested_region_without_targets_cannot_pass():
    result, _ = evaluate(dataset(), {"11110": "자료 없음"}, config(), model=FeatureOnlyModel(), baseline=baseline)
    assert result["status"] == "fail"
    assert any(c["name"] == "region_samples:11110" and not c["passed"] for c in result["checks"])


def test_overall_improvement_does_not_hide_region_regression():
    def region_baseline(target, *args):
        return baseline(target, *args) | {"estimated_manwon": target["price"] * (1.5 if target["lawd_cd"] == "11650" else 1.01)}
    class RegionModel(FeatureOnlyModel):
        def predict(self, rows):
            return [row["area_sqm"] * 600 * (1 if row["lawd_cd"] == "11650" else 1.1) for row in rows]
    result, _ = evaluate(dataset(), {"11650": "서초", "11350": "노원"}, config(), model=RegionModel(), baseline=region_baseline)
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["relative_mape_improvement"]
    assert not checks["region_mape_regression:11350"] and result["status"] == "fail"


def test_baseline_cannot_claim_test_month_history():
    def leaking(*args):
        return baseline(*args) | {"prior_months": ["202607"]}
    with pytest.raises(ValueError, match="최종 평가 기간"):
        evaluate(dataset(), {"11650": "서초"}, config(), model=FeatureOnlyModel(), baseline=leaking)


def test_actual_catboost_roundtrip_unseen_complex_and_artifact_integrity(tmp_path):
    rows = [transaction(i, area_sqm=50 + i, price=30000 + 650 * i) for i in range(35)]
    validation = [r | {"deal_ym": "202605"} for r in rows[::4]]
    model = CatBoostAvm(iterations=30, threads=1).fit(rows, validation)
    target = transaction(month="202606", apt_name="처음 보는 단지", floor=None, year_built=None)
    expected = model.predict([target])[0]
    assert math.isfinite(expected) and expected > 0
    assert model.predict([target | {"price": 1}])[0] == expected
    model.save(tmp_path, {"run_id": "regression"})
    loaded = CatBoostAvm.load(tmp_path)
    assert loaded.predict([target]) == pytest.approx([expected])
    manifest = json.loads((tmp_path / "model.json").read_text())
    assert manifest["prediction_unit"] == "manwon" and manifest["deployment"] == "evaluation_only"
    (tmp_path / "model.cbm").write_bytes(b"changed model")
    with pytest.raises(ValueError, match="일치하지"):
        CatBoostAvm.load(tmp_path)
    with pytest.raises(ValueError, match="겹치지 않는"):
        CatBoostAvm(iterations=2).fit(rows, rows)


def test_readonly_loader_selects_only_apartment_region_and_requested_period():
    from sqlalchemy import event, select, func
    from db.base import get_engine, session_scope
    from db.models import Transaction
    from tests.conftest import truncate_tables
    truncate_tables(Transaction)
    records = [transaction(1), transaction(2, region="11350"), transaction(3, "202609"), transaction(4)]
    with session_scope() as session:
        for row in records:
            session.add(Transaction(**row, category="주거용", endpoint="RTMSDataSvcAptTrade" if row["id"] != 4 else "RTMSDataSvcOffiTrade"))
    engine = get_engine()
    observed = []
    def check_readonly(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            cursor.execute("SHOW transaction_read_only")
            observed.append(cursor.fetchone()[0])
    event.listen(engine, "before_cursor_execute", check_readonly)
    try:
        rows, names = load_transactions(["11650"], config())
    finally:
        event.remove(engine, "before_cursor_execute", check_readonly)
    assert [r["id"] for r in rows] == [1]
    assert names.keys() == {"11650"} and observed and set(observed) == {"on"}
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(Transaction)) == 4


def test_comparison_report_shows_units_and_escapes_region_names(tmp_path):
    from evaluation.report import write_report
    result, _ = evaluate(dataset(), {"11650": "서초"}, config(), model=FeatureOnlyModel(), baseline=baseline)
    result["details"]["by_group"]["lawd_code"]["<script>unsafe()</script>"] = result["details"]["scores"]
    write_report(tmp_path / "report", {"run_id": "test"}, [result])
    document = (tmp_path / "report/report.html").read_text(encoding="utf-8")
    assert "CatBoost" in document and "P90 오차" in document
    assert "48,800,000원" in document  # 평균 오차 4,880만원을 원으로 변환한다.
    assert "&lt;script&gt;unsafe()&lt;/script&gt;" in document and "<script>unsafe()" not in document


def test_real_baseline_records_only_available_months_and_confirmed_match_level():
    from evaluation.production_avm import replay_one
    prior = transaction(month="202606", per_sqm=50000 / 84.9, deal_year=2026, deal_month=6)
    result = replay_one(transaction(month="202608"), {"202606": [prior] * 3}, "11650", "서울특별시 서초구")
    assert result["estimated"]
    assert result["prior_months"] == ["202606"]
    assert result["match_level"] == "same_complex"
