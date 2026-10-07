"""같은 과거 거래로 기존 실서비스 AVM과 CatBoost를 비교한다. 저장소는 읽기 전용이다."""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from statistics import mean, median
from time import perf_counter

from backend.valuation.catboost_avm import CatBoostAvm, complex_key, month_index, month_shift, numeric
from evaluation.production_avm import replay_one
from evaluation.schema import Check
from evaluation.suites import finish


@dataclass(frozen=True)
class ComparisonConfig:
    test_start: str
    test_end: str
    train_months: int = 8
    validation_months: int = 1
    max_cases: int = 300
    min_train: int = 200
    min_validation: int = 30
    min_paired: int = 100
    min_region_cases: int = 20
    min_improvement: float = .05
    max_region_regression: float = .02
    seed: int = 42

    def __post_init__(self):
        if not 0 <= month_index(self.test_end) - month_index(self.test_start) <= 11:
            raise ValueError("최종 평가 기간은 순서대로 1~12개월을 지정해주세요")
        if not 1 <= self.train_months <= 60 or not 1 <= self.validation_months <= 6 or not 1 <= self.max_cases <= 5000:
            raise ValueError("학습·검증 기간과 표본 수의 허용 범위를 확인해주세요")
        if min(self.min_train, self.min_validation, self.min_paired, self.min_region_cases) < 1:
            raise ValueError("최소 표본 수는 양수여야 합니다")
        if not 0 <= self.min_improvement <= 1 or not 0 <= self.max_region_regression <= 1:
            raise ValueError("개선 및 회귀 기준은 0~1 비율이어야 합니다")

    @property
    def validation_start(self):
        return month_shift(self.test_start, -self.validation_months)

    @property
    def train_start(self):
        return month_shift(self.validation_start, -self.train_months)


def load_transactions(regions: list[str], config: ComparisonConfig) -> tuple[list[dict], dict]:
    from sqlalchemy import select, text
    from db.base import get_engine
    from db.models import Transaction, LegalRegion
    if not regions or len(regions) != len(set(regions)) or len(regions) > 25 or not all(re.fullmatch(r"\d{5}", code) for code in regions):
        raise ValueError("서로 다른 시군구 코드 1~25개를 지정해주세요")
    columns = [Transaction.id, Transaction.lawd_cd, Transaction.deal_ym, Transaction.price,
               Transaction.area_sqm, Transaction.floor, Transaction.year_built, Transaction.apt_name,
               Transaction.dong, Transaction.jibun, Transaction.bjdong_code, Transaction.is_cancelled]
    # create_all·마이그레이션·수집·캐시 쓰기를 호출하지 않는다. 한 시점의 자료를 같은 두 모델에 제공한다.
    with get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = connection.execute(select(*columns).where(Transaction.endpoint == "RTMSDataSvcAptTrade",
                Transaction.lawd_cd.in_(regions), Transaction.deal_ym >= config.train_start,
                Transaction.deal_ym <= config.test_end).order_by(Transaction.deal_ym, Transaction.id).limit(500001)).mappings().all()
            names = dict(connection.execute(select(LegalRegion.lawd_code, LegalRegion.full_name).where(
                LegalRegion.lawd_code.in_(regions), LegalRegion.level == "sigungu")).all())
    if len(rows) > 500000:
        raise ValueError("한 번에 50만 건 이하가 되도록 기간·지역을 줄여주세요")
    return [dict(row) for row in rows], {code: names.get(code, code) for code in regions}


def split_rows(rows, config):
    groups = {"train": [], "validation": [], "test": []}
    excluded = Counter()
    for source in rows:
        row = dict(source)
        row["deal_ym"] = str(row.get("deal_ym", ""))
        try:
            month_index(str(row.get("deal_ym", "")))
        except ValueError:
            excluded["invalid_month"] += 1
            continue
        if not config.train_start <= row["deal_ym"] <= config.test_end:
            excluded["outside_period"] += 1
            continue
        if row.get("is_cancelled"):
            excluded["cancelled"] += 1
            continue
        price, area = numeric(row.get("price")), numeric(row.get("area_sqm"))
        if not math.isfinite(price) or price <= 0 or not math.isfinite(area) or area <= 0:
            excluded["invalid_price_or_area"] += 1
            continue
        row.update(price=price, area_sqm=area, per_sqm=price/area,
                   deal_year=int(row["deal_ym"][:4]), deal_month=int(row["deal_ym"][4:]))
        # 모델에 단가를 전달하는 것은 feature_values의 고정 허용 목록으로 차단한다.
        row = {key: row.get(key) for key in ("id", "lawd_cd", "deal_ym", "price", "area_sqm", "per_sqm",
               "deal_year", "deal_month", "floor", "year_built", "apt_name", "dong", "jibun", "bjdong_code")}
        group = "train" if row["deal_ym"] < config.validation_start else "validation" if row["deal_ym"] < config.test_start else "test"
        groups[group].append(row)
    for values in groups.values():
        values.sort(key=lambda row: (row["deal_ym"], str(row["lawd_cd"]), str(row["id"])))
    if len(groups["train"]) < config.min_train or len(groups["validation"]) < config.min_validation or not groups["test"]:
        raise ValueError("학습·검증·최종 평가 거래가 최소 표본 조건을 충족하지 못했습니다")
    return groups, dict(excluded)


def area_band(row):
    return "under60" if row["area_sqm"] < 60 else "60to85" if row["area_sqm"] <= 85 else "over85"


def select_targets(rows, config):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["lawd_cd"], row["deal_ym"], area_band(row))].append(row)
    pools = []
    for key in sorted(groups):
        pools.append(deque(sorted(groups[key], key=lambda row: hashlib.sha256(
            f"{config.seed}:{row['lawd_cd']}:{row['id']}".encode()).digest())))
    result = []
    while pools and len(result) < config.max_cases:
        for pool in pools:
            if pool and len(result) < config.max_cases:
                result.append(pool.popleft())
        pools = [pool for pool in pools if pool]
    return result


def price_metrics(records, field):
    predicted = [row for row in records if row[field] is not None and math.isfinite(row[field]) and row[field] > 0]
    errors = [abs(row[field] - row["actual_manwon"]) for row in predicted]
    apes = [error / row["actual_manwon"] for error, row in zip(errors, predicted)]
    return {"targets": len(records), "estimated": len(predicted), "coverage": len(predicted)/len(records) if records else 0,
        "mape": mean(apes) if apes else None, "median_ape": median(apes) if apes else None,
        "p90_ape": sorted(apes)[math.ceil(len(apes)*.9)-1] if apes else None,
        "mae_won": mean(errors)*10000 if errors else None,
        "hit10": mean(value <= .1 for value in apes) if apes else None}


def comparison_metrics(records):
    paired = [row for row in records if all(row[key] is not None and math.isfinite(row[key]) and row[key] > 0
              for key in ("baseline_manwon", "catboost_manwon"))]
    before = price_metrics(paired, "baseline_manwon")
    after = price_metrics(paired, "catboost_manwon")
    improvement = 1-after["mape"]/before["mape"] if before["mape"] and after["mape"] is not None else None
    return {"baseline": price_metrics(records, "baseline_manwon"), "catboost": price_metrics(records, "catboost_manwon"),
            "paired": {"count": len(paired), "baseline": before, "catboost": after, "relative_mape_improvement": improvement}}


def evaluate(rows, regions, config, *, model=None, baseline=replay_one):
    started = perf_counter()
    groups, excluded = split_rows(rows, config)
    targets = select_targets(groups["test"], config)
    model = model or CatBoostAvm(seed=config.seed)
    model.fit(groups["train"], groups["validation"])
    predictions = model.predict(targets)
    if len(predictions) != len(targets):
        raise ValueError("모델 예측 수와 평가 대상 수가 다릅니다")
    history = defaultdict(lambda: defaultdict(list))
    known_complexes = set()
    for row in groups["train"] + groups["validation"]:
        history[row["lawd_cd"]][row["deal_ym"]].append(row)
        known_complexes.add(complex_key(row))
    records = []
    for index, (target, predicted) in enumerate(zip(targets, predictions)):
        code = target["lawd_cd"]
        reference = baseline(target, dict(history[code]), code, regions.get(code, code))
        if any(month >= config.test_start for month in reference["prior_months"]):
            raise ValueError("기준선에 최종 평가 기간의 거래가 유입됐습니다")
        if not math.isfinite(predicted) or predicted <= 0:
            raise ValueError("CatBoost가 유효한 가격을 반환하지 않았습니다")
        records.append({"transaction_id": target["id"], "lawd_code": code, "target_month": target["deal_ym"],
            "actual_manwon": target["price"], "baseline_manwon": reference["estimated_manwon"] if reference["estimated"] else None,
            "catboost_manwon": predicted, "match_level": reference["match_level"], "area_band": area_band(target),
            "build_year_band": reference["build_year_band"], "seen_complex": complex_key(target) in known_complexes,
            "comparable_count": reference["comparable_count"], "baseline_prior_months": reference["prior_months"]})
        if (index + 1) % 50 == 0:
            print(f"동일 거래 비교 {index + 1}/{len(targets)}건", flush=True)
    scores = comparison_metrics(records)
    by_group = {axis: {str(value): comparison_metrics([row for row in records if row[axis] == value])
                      for value in sorted({row[axis] for row in records})}
                for axis in ("lawd_code", "target_month", "area_band", "build_year_band", "match_level", "seen_complex")}
    paired = scores["paired"]
    improvement = paired["relative_mape_improvement"]
    checks = [Check(name="paired_sample_count", passed=paired["count"] >= config.min_paired, expected=config.min_paired, actual=paired["count"]),
        Check(name="relative_mape_improvement", passed=improvement is not None and improvement >= config.min_improvement,
              expected=config.min_improvement, actual=improvement),
        Check(name="hit10_not_worse", passed=paired["catboost"]["hit10"] is not None and paired["catboost"]["hit10"] >= paired["baseline"]["hit10"]),
        Check(name="coverage_not_worse", passed=scores["catboost"]["coverage"] >= scores["baseline"]["coverage"])]
    for code in regions:
        region = by_group["lawd_code"].get(code, {}).get("paired", {})
        adequate = region.get("count", 0) >= config.min_region_cases
        checks.append(Check(name=f"region_samples:{code}", passed=adequate, expected=config.min_region_cases, actual=region.get("count", 0)))
        regression = region["catboost"]["mape"] - region["baseline"]["mape"] if adequate else None
        checks.append(Check(name=f"region_mape_regression:{code}", passed=regression is not None and regression <= config.max_region_regression,
                            expected=config.max_region_regression, actual=regression))
    data_hash = hashlib.sha256(json.dumps(groups, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
    details = {"scope": "아파트 매매·고정 시간 분할의 후보 모델 비교. 기준선은 실제 residential_agent 재생이며 현재 시설·LLM·외부 지수는 제외한다. 당시 신고/공표 지연·정정 이력은 복원하지 못한 회고 평가다. 가격은 내부 만원, MAE는 원이다. 통과해도 서비스 모델을 자동 변경하지 않는다.",
        "configuration": asdict(config), "split": {key: {"count": len(values), "first_month": min(r["deal_ym"] for r in values),
            "last_month": max(r["deal_ym"] for r in values)} for key, values in groups.items()},
        "excluded": excluded, "sampling": "지역·월·면적별 순환 및 ID/seed 해시 순서. 전체 시장의 거래량 가중 성능과 구분한다.",
        "unevaluated_targets": len(groups["test"])-len(targets), "data_sha256": data_hash,
        "scores": scores, "by_group": by_group, "records": records, "deployment": "evaluation_only"}
    metrics = {"paired_cases": paired["count"], "baseline_mape": paired["baseline"]["mape"],
               "catboost_mape": paired["catboost"]["mape"], "relative_mape_improvement": improvement,
               "baseline_hit10": paired["baseline"]["hit10"], "catboost_hit10": paired["catboost"]["hit10"]}
    result = finish("apartment-catboost-v1", "avm_compare", started, [check.model_dump() for check in checks], details, metrics)
    result["repeat"] = 1
    return result, model


def run(args):
    from pathlib import Path
    import importlib.metadata
    import uuid
    from dotenv import load_dotenv
    from concierge_workspace import REPO_ROOT
    from evaluation.report import write_report
    load_dotenv(REPO_ROOT / ".env", override=False)
    config = ComparisonConfig(args.test_start, args.test_end, args.train_months, args.validation_months,
        args.max_cases, min_improvement=args.min_improvement, seed=args.seed)
    if config.test_end >= datetime.now(timezone.utc).strftime("%Y%m"):
        raise ValueError("진행 중이거나 미래인 월을 최종 평가에 넣을 수 없습니다")
    try:
        version = importlib.metadata.version("catboost")
    except importlib.metadata.PackageNotFoundError as error:
        raise ValueError("requirements-ml.txt를 설치해야 합니다") from error
    rows, names = load_transactions(args.regions, config)
    print(f"저장 아파트 거래 {len(rows)}건 · 학습 {config.train_start}~{month_shift(config.validation_start,-1)} · 검증 {config.validation_start}~{month_shift(config.test_start,-1)} · 평가 {config.test_start}~{config.test_end}", flush=True)
    result, model = evaluate(rows, names, config, model=CatBoostAvm(iterations=args.iterations, seed=args.seed, threads=args.threads))
    directory = args.output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-avm-compare-" + uuid.uuid4().hex[:8])
    metadata = {"run_id": directory.name, "live": True, "created_at": datetime.now(timezone.utc).isoformat(),
        "catboost_version": version, "regions": names, "configuration": asdict(config),
        "data_sha256": result["details"]["data_sha256"], "split": result["details"]["split"],
        "implementation_sha256": {str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [Path(__file__), REPO_ROOT / "services/intelligence/backend/valuation/catboost_avm.py",
                         REPO_ROOT / "services/intelligence/evaluation/production_avm.py",
                         REPO_ROOT / "services/intelligence/backend/agents.py", REPO_ROOT / "services/intelligence/backend/price_engine.py"]}}
    write_report(directory, metadata, [result])
    model.save(directory, metadata | {"comparison_status": result["status"]})
    print(json.dumps({"status": result["status"], "metrics": result["metrics"], "report": str(directory / "report.html"),
                      "deployment": "evaluation_only"}, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "pass" else 1
