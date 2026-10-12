"""월별 롤링 평가: 기간 분할 누수 없음, 사전 판정 기준 적용, 구간 보정 두 방식 기록."""
import random

from evaluation.rolling_avm import ACCEPTANCE, evaluate, judge, months_between, shift
from evaluation.segment_avm import SegmentConfig, build_frame, split_parts


def _rows(seed=1):
    rng, rows, next_id = random.Random(seed), [], 1
    complexes = [(f"단지{i}", 15.8 + i * .05, ["반포동", "잠원동"][i % 2]) for i in range(16)]
    for month in range(24):
        year, mon = 2024 + month // 12, month % 12 + 1
        for name, level, dong in complexes:
            for _ in range(7):
                area = rng.choice([59.9, 84.9, 114.5])
                floor = rng.randint(1, 30)
                log_price = level + .004 * month + .002 * floor + rng.gauss(0, .03)
                rows.append(dict(id=next_id, lawd_cd="11650", deal_year=year, deal_month=mon, deal_day=rng.randint(1, 28),
                                 price=round(2.718281828 ** log_price * area / 10_000), area_sqm=area, floor=str(floor), year_built=2010,
                                 dong=dong, apt_name=name, transaction_type="중개거래", is_cancelled=False))
                next_id += 1
    return rows


def test_split_parts_keeps_months_ordered_and_blinds_trade_type():
    _, frame = build_frame(_rows(), "apartment", "202501")
    parts = split_parts(frame, SegmentConfig(("11650",), "202501", "202508", "202510", "202510", segment="apartment"))
    assert parts["train"].ym.max() < "202508" <= parts["validation"].ym.min()
    assert parts["validation"].ym.max() < "202510" and set(parts["test"].ym) == {"202510"}
    assert (parts["test"].direct == 0).all()


def test_rolling_evaluation_retrains_per_month_and_reports_both_band_methods():
    base = SegmentConfig(("11650",), "202501", "202501", "202501", "202501", models=("ridge",), segment="apartment", interval=.85)
    report = evaluate(_rows(), "apartment", ["202510", "202511"], "202501", ("ridge",), base, progress=lambda *_: None)
    monthly = report["monthly"]
    assert [m["month"] for m in monthly] == ["202510", "202511"] and monthly[1]["train_rows"] > monthly[0]["train_rows"]
    assert {r["ym"] for r in report["rows"]["ridge"]} == {"202510", "202511"}
    summary = report["models"]["ridge"]["summary"]
    assert set(summary["coverage"]) == {"level", "price"} and "A1" in summary["model"]
    assert report["models"]["ridge"]["verdict"]["a1_hybrid"]["checks"]  # 같은 A1 거래로 기존 규칙과 비교했다


def test_judge_uses_preregistered_thresholds():
    a1 = ACCEPTANCE["a1_hybrid"]
    months = ["202601", "202602"]
    metrics = lambda mape, n=200, bias=0.0: {"n": n, "mape": mape, "bias": bias, "hit10": .8}
    summary = {"model": {"A1": metrics(.050), "A1|month:202601": metrics(.050), "A1|month:202602": metrics(.050), "A1|region:11650": metrics(.05)},
               "rule": {"all": metrics(.060), "month:202601": metrics(.060), "month:202602": metrics(.060), "region:11650": metrics(.06)},
               "coverage": {"level": {}, "price": {}}, "calibration": {"level": {}, "price": {}}}
    assert judge(summary, months, ["A1"])["a1_hybrid"]["approve"]
    summary["model"]["A1"] = metrics(.059)  # 개선 1.7% < 5%
    assert not judge(summary, months, ["A1"])["a1_hybrid"]["approve"]
    summary["model"]["A1"] = metrics(.050, bias=a1["max_abs_bias"] + .01)
    assert not judge(summary, months, ["A1"])["a1_hybrid"]["approve"]


def test_month_helpers():
    assert months_between("202511", "202602") == ["202511", "202512", "202601", "202602"]
    assert shift("202601", -2) == "202511"
