"""스냅샷 전체로 최종 모델을 학습해 model/에 저장한다. 가격 모델은 --model로 바꿀 수 있다.

python train.py                       # 마지막 3개월을 검증(조기 종료·구간·신뢰도 보정)으로 쓴다
python train.py --validation-months 3 --history-months 12
python train.py --model ridge          # 다른 등록 모델로 교체 (model/의 manifest가 바뀌고 predict가 그 모델을 읽는다)
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from rh_avm.core import load_trades
from rh_avm.model import save, train

ROOT = Path(__file__).resolve().parent


def shift(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="R-RH 연립·다세대 AVM 학습")
    parser.add_argument("--data", default=str(ROOT / "data" / "rh_trades.csv"))
    parser.add_argument("--validation-months", type=int, default=3)
    parser.add_argument("--history-months", type=int, default=12, help="학습 시작 전 비교사례용으로만 쓰는 기간")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", default="catboost", help="가격 모델 이름 (등록표: catboost, ridge, comparables)")
    args = parser.parse_args()
    data = Path(args.data)
    trades = load_trades(data)
    last = trades[-1].day
    # 진행 중인 마지막 달은 신고가 덜 들어와 검증을 왜곡하므로 검증 끝을 그 전달 말일로 둔다.
    end = shift(date(last.year, last.month, 1), 0)
    end = date.fromordinal(end.toordinal() - 1)
    validation_start = shift(date(end.year, end.month, 1), -(args.validation_months - 1))
    train_start = shift(date(trades[0].day.year, trades[0].day.month, 1), args.history_months)
    model, meta, validation, _ = train(trades, train_start, validation_start, end, seed=args.seed, model_name=args.model)
    save(model, meta, ROOT / "model", data)
    print(f"학습 {meta['train_start']}~{validation_start} 전날 {meta['train_rows']}건 (학습 이상치 제외 {meta['train_outliers_removed']}건)")
    print(f"모델 {model.name} {model.training} · 검증 {validation_start}~{end} {meta['validation_rows']}건 · 검증 MAPE {meta['validation_mape']:.1%} · 저장 {ROOT / 'model'}")
    for name, band in meta["calibration"].items():
        print(f"  {name}: 검증 {band['n']}건 · 구간 로그 {band['low']:+.3f}~{band['high']:+.3f} · 신뢰도 {band['confidence']} (출처 {band['source']})")


if __name__ == "__main__":
    main()
