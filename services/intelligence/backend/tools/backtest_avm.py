"""
backtest_avm.py — AVM 추정 정확도 백테스트 + 신뢰도 보정테이블 생성

방법 (홀드아웃):
  대상 월 T의 실거래 각각에 대해, T 이전 window개월 데이터만으로
  실서비스와 같은 단계적 매칭(동일단지 → 동일동 → 동일구)으로 시세를 추정하고
  실제 거래가와 비교한다.

  APE = |추정가 − 실거래가| / 실거래가
  hit10 = APE ≤ 10% 비율  →  "신뢰도"의 실측 정의

출력:
  - 콘솔: 전체/버킷별 MAPE·중앙값·적중률
  - data/avm_calibration.json: confidence.py 가 블렌딩에 사용하는 보정테이블
    버킷 키 = "{매칭수준}|{표본수밴드}" (예: "same_complex|n5-9")

사용 예:
  # 사전에 실거래 수집 필요 (백테스트는 로컬 스토어만 사용, API 호출 없음)
  python backend/tools/ingest_transactions.py --regions 서초구 --months 12 --yes
  python backend/tools/backtest_avm.py --regions 서초구 --target-months 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from statistics import mean, median

_TOOLS_DIR    = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_TOOLS_DIR)
from concierge_workspace import REPO_ROOT
_PROJECT_ROOT = str(REPO_ROOT)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import transaction_store
from cache_db import get_lawd_code
from confidence import count_band
from price_engine import _TIME_ADJ_MONTHLY_RATE, _time_adj_factor

ENDPOINT = "RTMSDataSvcAptTrade"   # 단지명 매칭이 유의미한 아파트 계열로 백테스트
CATEGORY = "주거용"

DEFAULT_OUT = os.path.join(_PROJECT_ROOT, "data", "avm_calibration.json")


# ─────────────────────────────────────────
#  시점수정 (실서비스와 동일: 지수 우선 → 근사율)
# ─────────────────────────────────────────

def _months_diff(from_ym: str, to_ym: str) -> int:
    a = datetime.strptime(from_ym, "%Y%m")
    b = datetime.strptime(to_ym, "%Y%m")
    return (b.year - a.year) * 12 + (b.month - a.month)


def _make_time_factor(region_name: str):
    """(from_ym, to_ym) → 시점수정 계수. reb_index 사용 가능 시 지수 우선."""
    try:
        import reb_index
        use_reb = reb_index.is_enabled()
    except Exception:
        use_reb = False
    rate = _TIME_ADJ_MONTHLY_RATE.get(CATEGORY, 0.002)

    def factor(from_ym: str, to_ym: str) -> float:
        if from_ym == to_ym:
            return 1.0
        if use_reb:
            r = reb_index.get_adj_factor(CATEGORY, region_name, from_ym, to_ym)
            if r:
                f, desc = r
                reached = reb_index.reached_ym(desc)
                remain = _months_diff(reached, to_ym) if reached else 0
                if remain > 0:
                    f = f * _time_adj_factor(remain, rate)
                return f
        return _time_adj_factor(_months_diff(from_ym, to_ym), rate)

    return factor


# ─────────────────────────────────────────
#  매칭 (실서비스 단계 축소판)
# ─────────────────────────────────────────

def _match_comps(deal: dict, pool: list[tuple[str, dict]]) -> tuple[list[tuple[str, dict]], str]:
    """
    반환: (매칭 표본 [(ym, sample)], match_level)
    1) 동일 단지 + 면적 ±15%
    2) 동일 동   + 면적 ±10%
    3) 구 전체   + 면적 ±10%
    """
    area = deal.get("area_sqm") or 0

    def _area_ok(c, tol):
        ca = c.get("area_sqm") or 0
        return ca > 0 and abs(ca - area) / area <= tol

    same_complex = [(ym, c) for ym, c in pool
                    if c.get("apt_name") == deal.get("apt_name") and _area_ok(c, 0.15)]
    if same_complex:
        return same_complex, "same_complex"

    same_dong = [(ym, c) for ym, c in pool
                 if c.get("dong") and c.get("dong") == deal.get("dong") and _area_ok(c, 0.10)]
    if same_dong:
        return same_dong, "same_dong"

    same_gu = [(ym, c) for ym, c in pool if _area_ok(c, 0.10)]
    return same_gu, "same_gu"


# ─────────────────────────────────────────
#  백테스트 본체
# ─────────────────────────────────────────

def run_backtest(region_name: str, lawd_cd: str,
                 target_months: int, window: int) -> list[dict]:
    """지역 1곳 백테스트 → 케이스 목록 [{level, n, ape}, ...]"""
    # 로컬 스토어에서 적재된 전체 월 로드 (TTL 무시)
    months_data: dict[str, list[dict]] = {}
    yms = transaction_store.list_ingested_months(ENDPOINT, CATEGORY, lawd_cd)
    for ym in yms:
        rows = transaction_store.get_month(ENDPOINT, CATEGORY, lawd_cd, ym, ignore_ttl=True)
        if rows:
            months_data[ym] = rows

    if len(months_data) < 3:
        print(f"⚠️  {region_name}: 적재 월 {len(months_data)}개 — 백테스트에 최소 3개월 필요."
              f" 먼저 ingest_transactions.py 로 수집하세요.")
        return []

    return evaluate_months(months_data, region_name=region_name, target_months=target_months,
                           window=window, time_factor=_make_time_factor(region_name))["cases"]


def evaluate_months(months_data: dict[str, list[dict]], *, region_name: str,
                    target_months: int, window: int, time_factor) -> dict:
    """읽어온 거래를 시간순으로 분리한다. 저장·외부 조회 없이 기존 백테스트를 재사용한다."""
    all_yms = sorted(months_data)
    targets = all_yms[-target_months:]
    cases: list[dict] = []
    eligible = 0
    invalid = 0
    cancelled = 0
    for T in targets:
        prior_yms = [ym for ym in all_yms if ym < T][-window:]
        # 해제 거래가 비교사례나 정답에 섞이면 실제 거래 성능을 왜곡한다.
        pool = [(ym, s) for ym in prior_yms for s in months_data[ym]
                if not s.get("is_cancelled") and (s.get("price") or 0) > 0 and (s.get("area_sqm") or 0) > 0]

        for deal in months_data[T]:
            if deal.get("is_cancelled"):
                cancelled += 1
                continue
            price = deal.get("price") or 0
            area  = deal.get("area_sqm") or 0
            if price <= 0 or area <= 0:
                invalid += 1
                continue

            eligible += 1

            comps, level = _match_comps(deal, pool)
            if not comps:
                continue

            adj_per_sqm = []
            for ym, c in comps:
                per = c.get("per_sqm") or 0
                if per <= 0:
                    continue
                adj_per_sqm.append(per * time_factor(ym, T))
            if not adj_per_sqm:
                continue

            pred = mean(adj_per_sqm) * area
            ape  = abs(pred - price) / price
            cases.append({"region": region_name, "target_ym": T,
                          "level": level, "n": len(adj_per_sqm), "ape": ape,
                          "predicted_manwon": pred, "observed_manwon": price,
                          "prior_months": prior_yms})
    return {"cases": cases, "eligible": eligible, "invalid": invalid, "cancelled": cancelled,
            "unestimated": eligible - len(cases), "coverage": len(cases) / eligible if eligible else 0}


def summarize(cases: list[dict]) -> dict:
    """케이스 → 전체/버킷 통계 + 보정테이블."""
    def _stats(apes: list[float]) -> dict:
        return {
            "n":      len(apes),
            "mape":   round(mean(apes), 4),
            "median": round(median(apes), 4),
            "hit5":   round(sum(a <= 0.05 for a in apes) / len(apes), 3),
            "hit10":  round(sum(a <= 0.10 for a in apes) / len(apes), 3),
            "hit15":  round(sum(a <= 0.15 for a in apes) / len(apes), 3),
        }

    buckets: dict[str, list[float]] = {}
    for c in cases:
        key = f"{c['level']}|{count_band(c['n'])}"
        buckets.setdefault(key, []).append(c["ape"])

    return {
        "generated_at":  datetime.now().isoformat(timespec="seconds"),
        "method":        "holdout: 대상월 거래를 이전 window개월 비교사례로 추정",
        "n_cases":       len(cases),
        "overall":       _stats([c["ape"] for c in cases]),
        "buckets":       {k: _stats(v) for k, v in sorted(buckets.items())},
    }


def main():
    parser = argparse.ArgumentParser(description="AVM 백테스트 + 신뢰도 보정테이블 생성")
    parser.add_argument("--regions", required=True, help="쉼표 구분 지역명 (예: 서초구,강남구)")
    parser.add_argument("--target-months", type=int, default=3, help="검증 대상 최근 월 수 (기본 3)")
    parser.add_argument("--window", type=int, default=6, help="비교사례 조회 이전 개월 수 (기본 6)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="보정테이블 출력 경로")
    args = parser.parse_args()

    all_cases: list[dict] = []
    for name in args.regions.split(","):
        name = name.strip()
        if not name:
            continue
        lawd = get_lawd_code(name)
        if not lawd:
            print(f"⚠️  '{name}' 지역코드 없음 — 건너뜀")
            continue
        cases = run_backtest(name, lawd, args.target_months, args.window)
        print(f"[backtest] {name}: {len(cases)}건 검증")
        all_cases.extend(cases)

    if not all_cases:
        sys.exit("❌ 검증 케이스 없음 — 데이터 수집 상태를 확인하세요")

    result = summarize(all_cases)

    o = result["overall"]
    print(f"\n═══ 백테스트 결과 (전체 {o['n']}건) ═══")
    print(f"  MAPE {o['mape']:.1%} / 중앙값 {o['median']:.1%}"
          f" / ±5% {o['hit5']:.0%} / ±10% {o['hit10']:.0%} / ±15% {o['hit15']:.0%}")
    print(f"\n  {'버킷':<22}{'건수':>5}{'MAPE':>8}{'±10%':>7}")
    for k, s in result["buckets"].items():
        print(f"  {k:<22}{s['n']:>5}{s['mape']:>8.1%}{s['hit10']:>7.0%}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 보정테이블 저장: {args.out}")
    print("   → confidence.py 가 자동으로 로드해 신뢰도에 반영합니다")


if __name__ == "__main__":
    main()
