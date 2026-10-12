"""아파트 혼합 AVM(R-APT) 매달 재학습.

롤링 평가에서 매달 직전 2개월로 다시 학습해야 성능이 유지된다는 점을 확인했다(2026-10-12). 이 도구는
① 새 완결월이 생겼는지 확인 → ② 최근 12개월 롤링 평가 → ③ 사전 판정 기준(evaluation.rolling_avm.ACCEPTANCE)으로 판정 →
④ ML 참고 추정 기준을 통과할 때만 새 모델을 임시 폴더에 학습·검증 → ⑤ 한 번에 교체하고 이전 모델은 이력에 보관한다.
A1 혼합 적용(a1_hybrid_approved)은 매번 그 달의 판정을 그대로 따른다. 기준 미달이면 기존 모델을 유지하고 사유를 남긴다.

모델은 저장소가 아닌 라이브 폴더(AVM_APARTMENT_LIVE_DIR, Docker 볼륨)에 둔다. API·작업 실행기는 manifest가 바뀌면 다시 읽는다.
python -m backend.tools.retrain_apartment_avm --live-dir /app/data/models-live/r-apt [--force] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

ENDPOINT = "RTMSDataSvcAptTrade"
TRAIN_HISTORY_MONTHS = 24     # 학습 창 상한(완결월 기준 24개월). 근거용 12개월은 그 앞에서 더 읽는다.


def shift(ym: str, months: int) -> str:
    index = int(ym[:4]) * 12 + int(ym[4:]) - 1 + months
    return f"{index // 12:04d}{index % 12 + 1:02d}"


def last_complete_month(today: date) -> str:
    # 진행 중인 달은 신고가 덜 들어와 평가·보정을 왜곡한다. 직전 달까지를 완결월로 본다.
    return shift(f"{today.year:04d}{today.month:02d}", -1)


def plan_months(earliest: str, last: str) -> dict:
    """롤링 평가 12개월과 최종 학습 창. 학습은 근거용 12개월 이후부터, 최대 24개월."""
    train_start = max(shift(earliest, 12), shift(last, -(TRAIN_HISTORY_MONTHS - 1)))
    first_test = max(shift(last, -11), shift(train_start, 3))
    return {"train_start": train_start, "test_from": first_test, "test_to": last,
            "final_validation_start": shift(last, -1)}


def current_manifest(directory: Path) -> dict | None:
    try:
        return json.loads((directory / "model.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def decide(verdict: dict) -> dict:
    """판정 결과 → 교체 여부와 A1 승인. ML 참고 추정(A2·A3) 기준을 통과하지 못하면 교체하지 않는다."""
    level = verdict["model_estimate"]["level"]
    estimate_ok = (all(v["pass"] for v in level["coverage"].values()) and level["price_band_coverage"]["pass"]
                   and all(v["pass"] for v in level["calibration"].values()))
    return {"deploy": estimate_ok, "a1_hybrid_approved": bool(verdict["a1_hybrid"]["approve"]),
            "a3_keep": bool(verdict["a3"]["keep"]),
            "reason": "기준 통과" if estimate_ok else "ML 참고 추정의 구간 적중·신뢰도 기준 미달 — 기존 모델 유지"}


def swap(staging: Path, live: Path, history: Path) -> Path | None:
    """임시 폴더를 라이브 폴더로 교체한다. 기존 모델은 학습 기준월 이름으로 이력에 옮긴다."""
    previous = None
    old = current_manifest(live)
    if old is not None:
        history.mkdir(parents=True, exist_ok=True)
        previous = history / f"r-apt-{(old.get('trained_through') or 'unknown')[:7]}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
        shutil.move(str(live), str(previous))
    live.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(live))
    return previous


def verify(directory: Path) -> None:
    """교체 전 확인: manifest 해시 검증으로 읽히고, 서비스용 R-APT 산출물인지."""
    from backend.valuation import models as price_models
    model, manifest = price_models.load(directory)
    if manifest.get("segment") != "R-APT" or manifest.get("deployment") != "service" or not manifest.get("calibration"):
        raise ValueError("서비스용 R-APT 산출물이 아닙니다")


def run(live: Path, regions: tuple[str, ...], today: date, force: bool = False, dry_run: bool = False,
        evaluate=None, train=None, load=None, earliest: str | None = None) -> dict:
    """한 번의 재학습 판단·실행. 무거운 단계(evaluate·train·load)는 테스트에서 바꿔 끼울 수 있다."""
    from evaluation import rolling_avm, segment_avm
    evaluate = evaluate or rolling_avm.evaluate
    train = train or segment_avm.train_final
    load = load or segment_avm.load_rows
    last = last_complete_month(today)
    # 라이브 모델이 아직 없으면 이미지에 포함된 모델의 학습 기준월로 판단한다(첫 배포 직후 중복 재학습 방지).
    from backend.valuation.apartment_avm import bundled_dir
    manifest = current_manifest(live) or current_manifest(bundled_dir())
    trained = (manifest or {}).get("trained_through", "")[:7].replace("-", "")
    if manifest and trained >= last and not force:
        return {"status": "up_to_date", "trained_through": trained, "last_complete_month": last}
    months = plan_months(earliest or _earliest_month(regions), last)
    base = segment_avm.SegmentConfig(regions, months["train_start"], months["train_start"], months["train_start"], months["train_start"],
                                     models=("catboost",), segment="apartment", interval=.85)
    rows = load(regions, shift(months["train_start"], -12), last, ENDPOINT)
    report = evaluate(rows, "apartment", rolling_avm.months_between(months["test_from"], months["test_to"]), months["train_start"],
                      ("catboost",), base, progress=lambda message: print(message, flush=True))
    verdict = report["models"]["catboost"]["verdict"]
    decision = decide(verdict)
    summary = {"status": "evaluated", "last_complete_month": last, "months": months, "decision": decision,
               "a1_checks": verdict["a1_hybrid"]["checks"]}
    reports = live.parent / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")  # 같은 초의 재실행도 보고서를 덮어쓰지 않는다
    report_path = reports / f"{stamp}-rolling-{last}.json"
    report_path.write_text(json.dumps({k: v for k, v in report.items() if k != "rows"} | {"decision": decision},
                                      ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if not decision["deploy"] or dry_run:
        return summary | {"status": "kept" if not decision["deploy"] else "dry_run", "report": str(report_path)}
    config = replace(base, validation_start=months["final_validation_start"], test_start="999999", test_end=last, band_by="level")
    model, meta = train(rows, config, "catboost")
    staging = live.parent / f".staging-{stamp}"
    from backend.valuation import models as price_models
    price_models.save(model, staging, meta | {"deployment": "service", "regions": list(regions),
                                              "a1_hybrid_approved": decision["a1_hybrid_approved"], "evaluation_report": str(report_path),
                                              "retrained_at": stamp})
    verify(staging)
    previous = swap(staging, live, live.parent / "history")
    return summary | {"status": "deployed", "trained_through": meta["trained_through"], "previous": str(previous) if previous else None,
                      "report": str(report_path)}


def _earliest_month(regions) -> str:
    from sqlalchemy import func, select
    from db.base import get_engine
    from db.models import Transaction
    with get_engine().connect() as connection:
        value = connection.execute(select(func.min(Transaction.deal_ym)).where(Transaction.endpoint == ENDPOINT,
                                                                               Transaction.lawd_cd.in_(regions))).scalar()
    if not value:
        raise ValueError("아파트 실거래가 없습니다")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="아파트 혼합 AVM 매달 재학습")
    parser.add_argument("--live-dir", required=True)
    parser.add_argument("--sido", default="서울특별시")
    parser.add_argument("--force", action="store_true", help="학습 기준월이 최신이어도 다시 평가·학습")
    parser.add_argument("--dry-run", action="store_true", help="평가·판정만 하고 교체하지 않음")
    args = parser.parse_args()
    from backend.tools.ingest_transactions import _regions_for_sido
    regions = tuple(code for _, code in _regions_for_sido(args.sido))
    if not regions:
        sys.exit("지역이 없습니다. 법정동 마스터를 확인하세요")
    result = run(Path(args.live_dir), regions, date.today(), force=args.force, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    main()
