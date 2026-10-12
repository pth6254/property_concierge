"""스카이키 과제 규격 실행기: python predict.py --input input.csv --output output.csv

입력: id, sigungu, dong, jibun, floor, ho, area_m2(비어 있을 수 있음)
출력: id, price_est, price_low, price_high, confidence, basis, status (산출 불가 시 status=fail: 사유)

처리 순서
1. 권역(강서구 화곡동·강남구·관악구) 확인 → 밖이면 fail
2. 전용면적: 입력값 → 건축물대장 전유부(지번+호) → 같은 건물 실거래 면적 중앙값(추정, 신뢰도·구간 보정) → 없으면 fail
3. 건물 정보: 같은 건물 실거래의 준공연도·대지권비율·연립/다세대 → 없으면 건축물대장 표제부
4. 비교사례 근거(L1 같은 건물 / L2 같은 동 유사 / L3 없음)와 CatBoost 보정으로 ㎡당 가격 추정
5. 근거 버킷별로 검증 구간에서 보정한 하한·상한·신뢰도를 붙인다
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

from rh_avm.core import ComparableIndex, MarketIndex, Trade, load_trades, month_of, normalize_jibun, to_float, to_int
from rh_avm.model import COLUMNS, bucket, features, interval, load
from rh_avm import register

ROOT = Path(__file__).resolve().parent
SIGUNGU = {"강서구": "11500", "관악구": "11620", "강남구": "11680"}
# 강서구는 화곡동만 과제 권역이다. 강남구·관악구는 구 전체.
DONG_LIMIT = {"11500": {"화곡동"}}
OUTPUT = ["id", "price_est", "price_low", "price_high", "confidence", "basis", "status"]


def lawd_of(sigungu: str) -> str | None:
    text = re.sub(r"\s+", "", sigungu or "")
    for name, code in SIGUNGU.items():
        if text.endswith(name) and (text in (name, "서울" + name, "서울시" + name, "서울특별시" + name)):
            return code
    return None


def floor_of(floor: str, ho: str) -> int | None:
    value = to_int(floor)
    if value is not None:
        return value
    text = re.sub(r"\s", "", str(ho or "")).upper()
    if re.fullmatch(r"B\d+", text):  # B01 → 지하1층, B201 → 지하2층
        digits = text[1:]
        return -1 if len(digits) <= 2 else -int(digits[:-2])
    if re.fullmatch(r"\d{3,4}", text):
        return int(text[:-2])
    return None


def fail(row_id: str, reason: str) -> dict:
    return {"id": row_id, "price_est": "", "price_low": "", "price_high": "", "confidence": 0, "basis": reason, "status": f"fail: {reason}"}


def estimate_one(row: dict, comps: ComparableIndex, index: MarketIndex, model, meta: dict, as_of: date) -> dict:
    row_id = str(row.get("id", "")).strip()
    lawd = lawd_of(row.get("sigungu", ""))
    dong = re.sub(r"\s+", "", row.get("dong", ""))
    if not lawd:
        return fail(row_id, "과제 권역(서울 강서구·관악구·강남구) 밖의 시군구")
    if lawd in DONG_LIMIT and dong not in DONG_LIMIT[lawd]:
        return fail(row_id, "강서구는 화곡동만 과제 권역")
    if not register.legal_dong_code(lawd, dong):
        return fail(row_id, f"법정동을 확인할 수 없음: {dong}")
    jibun = normalize_jibun(row.get("jibun", ""))
    if not re.fullmatch(r"산?\d+(-\d+)?", jibun):
        return fail(row_id, "지번 형식을 확인할 수 없음")
    notes, widen, confidence_factor = [], 0.0, 1.0
    same = comps.building_trades(lawd, dong, jibun)
    area = to_float(row.get("area_m2"))
    if area:
        notes.append(f"전용 {area:g}㎡(입력)")
    else:
        found = register.unit_area(lawd, dong, jibun, row.get("ho", ""))
        if found:
            area = found; notes.append(f"전용 {area:g}㎡(건축물대장 전유부)")
        elif same:
            area = round(median(t.area for t in same), 2)
            # 같은 건물이라도 호마다 면적이 다를 수 있어 구간을 넓히고 신뢰도를 낮춘다.
            widen, confidence_factor = .10, .7
            notes.append(f"전용면적 미입력·건축물대장 조회 실패 → 같은 건물 실거래 면적 중앙값 {area:g}㎡로 추정")
        else:
            return fail(row_id, "전용면적 미입력, 건축물대장 조회 실패, 같은 건물 실거래 없음")
    floor = floor_of(row.get("floor", ""), row.get("ho", ""))
    if same:
        years = [t.year_built for t in same if t.year_built]
        year_built = Counter(years).most_common(1)[0][0] if years else None
        ratios = [t.land_area / t.area for t in same if t.land_area]
        land_area = median(ratios) * area if ratios else None
        house_type = Counter(t.house_type for t in same).most_common(1)[0][0]
        name = Counter(t.name for t in same if t.name).most_common(1)
        notes.append(f"{name[0][0] if name else '같은 건물'} 준공 {year_built or '미상'}")
    else:
        title = register.building_title(lawd, dong, jibun)
        year_built = title["year_built"] if title else None
        land_area, house_type = None, "미상"
        if title:
            notes.append(f"건축물대장 표제부: 사용승인 {year_built or '미상'} · 주용도 {title['main_use'] or '미상'}")
            if title["main_use"] and "공동주택" not in title["main_use"] and "다세대" not in title["main_use"] and "연립" not in title["main_use"]:
                # 근생빌라 등 공부상 용도가 다르면 가격·대출 조건이 달라 신뢰도를 낮춘다.
                confidence_factor *= .6; widen += .05
                notes.append("공부상 주용도가 공동주택이 아님(근생 등) → 신뢰도 하향")
        else:
            notes.append("같은 건물 실거래 없음·건축물대장 표제부 조회 실패 → 준공연도 미상")
    target = Trade(id=-1, lawd=lawd, dong=dong, jibun=jibun, day=as_of, floor=floor, area=area, price=1,
                   year_built=year_built, land_area=land_area, house_type=house_type, direct=False)
    evidence = comps.evidence(target, as_of + timedelta(days=1))
    record = features(target, evidence, index, meta["origin_month"], month_of(as_of), direct=False)
    import pandas as pd
    log_estimate = float(model.predict(pd.DataFrame([record])[COLUMNS])[0])
    estimate = math.exp(log_estimate) * area
    name = bucket(evidence)
    low, high, confidence = interval(log_estimate, area, meta["calibration"], name, widen)
    confidence = round(confidence * confidence_factor, 2)
    method = {"L1": "같은 건물 거래 기반", "L2": "같은 동 유사 물건 기반", "L3": "근거 거래 없음 → 통계 보정만"}[evidence.level]
    comp_text = "" if evidence.estimate is None else f"(비교사례 ㎡당 {math.exp(evidence.estimate) / 10_000:,.0f}만원)"
    basis = (f"[{name}] {evidence.basis}{comp_text}, {method}; {meta['model']} 보정(층 {floor if floor is not None else '미상'}·준공·대지권비율·시점, "
             f"기준일 {as_of.isoformat()}, 중개거래 가정); " + "; ".join(notes))
    # 10만원 단위로 반올림한 정수 원.
    return {"id": row_id, "price_est": int(round(estimate, -5)), "price_low": int(round(low, -5)), "price_high": int(round(high, -5)),
            "confidence": confidence, "basis": basis, "status": "ok"}


def main() -> int:
    parser = argparse.ArgumentParser(description="연립·다세대 AI 시세 산출")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--as-of", help="산출 기준일 YYYY-MM-DD (기본: 오늘, 한국 시간)")
    parser.add_argument("--data", default=str(ROOT / "data" / "rh_trades.csv"))
    args = parser.parse_args()
    started = time.perf_counter()
    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(ZoneInfo("Asia/Seoul")).date()
    if not (ROOT / "model" / "model.json").exists():
        sys.exit("model/model.json이 없습니다. 먼저 python train.py를 실행하세요.")
    model, meta = load(ROOT / "model")
    trades = load_trades(Path(args.data))
    index = MarketIndex(trades)
    comps = ComparableIndex(trades, index)
    with open(args.input, encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    results = []
    for row in rows:
        try:
            results.append(estimate_one(row, comps, index, model, meta, as_of))
        except Exception as error:  # 한 건의 오류로 전체를 멈추지 않는다
            results.append(fail(str(row.get("id", "")), f"처리 오류: {type(error).__name__}"))
    with open(args.output, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT)
        writer.writeheader(); writer.writerows(results)
    failed = sum(r["status"] != "ok" for r in results)
    print(f"{len(results)}건 처리 (실패 {failed}건) · 모델 {meta['model']} · 기준일 {as_of} · {time.perf_counter() - started:.1f}초 · 저장 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
