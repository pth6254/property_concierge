"""선택 실행·예산 제한·보고서 비교를 제공하는 평가 전용 CLI."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from pydantic import ValidationError
from evaluation.schema import Dataset
from evaluation.report import write_report
from evaluation.runner import run_case

ROOT = Path(__file__).resolve().parents[1]
DATASETS = Path(__file__).parent / "datasets"


def load_dataset(path: Path) -> tuple[Dataset, list]:
    dataset = Dataset.model_validate_json(path.read_text(encoding="utf-8-sig"))
    return dataset, dataset.validated_cases()


def positive_int(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수를 지정하세요")
    return result


def metadata(args, paths):
    import platform
    from backend import tax_rules
    from backend.services import chat_service
    hashes = {str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name:
              hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    provider = os.getenv("LLM_PROVIDER", "ollama").lower().strip()
    # 환경변수 전체를 기록하지 않는다. 인증키·접속 문자열은 평가 결과에 불필요하다.
    config_keys = ["LLM_PROVIDER", "EMBED_PROVIDER", "OLLAMA_MODEL", "OLLAMA_EMBED_MODEL",
                   "OPENAI_MODEL", "OPENAI_EMBED_MODEL", "ANTHROPIC_MODEL", "GOOGLE_MODEL", "GOOGLE_EMBED_MODEL"]
    model_config = {key: os.environ[key] for key in config_keys if key in os.environ}
    defaults = {"ollama": ("OLLAMA_MODEL", "qwen3.5:9b"), "openai": ("OPENAI_MODEL", "gpt-4o"),
                "anthropic": ("ANTHROPIC_MODEL", "claude-opus-4-7"), "google": ("GOOGLE_MODEL", "gemini-2.0-flash")}
    model_key, default_model = defaults.get(provider, ("", "unknown"))
    model_config["effective_model"] = os.getenv(model_key, default_model)
    return {"run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8],
            "created_at": datetime.now(timezone.utc).isoformat(), "git_commit": commit,
            "python": platform.python_version(), "datasets": hashes, "live": args.live,
            "repeat": args.repeat, "k": args.k, "timeout_seconds_per_case": args.timeout,
            "model_config": model_config, "provider_default": provider, "rules_as_of": tax_rules.TAX_RULES_AS_OF,
            "prompt_sha256": hashlib.sha256((chat_service.ROUTER_PROMPT + chat_service.ANSWER_PROMPT).encode()).hexdigest(),
            "evaluator_sha256": hashlib.sha256(b"".join(path.read_bytes() for path in sorted(Path(__file__).parent.glob("*.py")))).hexdigest(),
            "implementation_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [ROOT / "backend/services/chat_service.py", ROOT / "backend/chat_corpus.py", ROOT / "backend/tax_rules.py",
                             ROOT / "backend/services/analysis_freshness.py", ROOT / "backend/services/case_comparison_service.py",
                             ROOT / "backend/services/candidate_next_actions.py", ROOT / "backend/services/execution_plan_service.py",
                             ROOT / "backend/tools/backtest_avm.py", ROOT / "backend/price_engine.py",
                             ROOT / "backend/graphs/concierge_graph.py", ROOT / "backend/concierge/tools.py"]}}


def compare_reports(baseline: Path, current: Path):
    before, after = [json.loads(path.read_text(encoding="utf-8")) for path in (baseline, current)]
    old = {(r["suite"], r["id"], r["repeat"]): r for r in before["results"]}
    new = {(r["suite"], r["id"], r["repeat"]): r for r in after["results"]}
    changes = [{"suite": key[0], "id": key[1], "repeat": key[2], "before": old[key]["status"], "after": new[key]["status"],
                "metrics_before": old[key].get("metrics", {}), "metrics_after": new[key].get("metrics", {})}
               for key in sorted(old.keys() & new.keys()) if old[key]["status"] != new[key]["status"] or old[key].get("metrics") != new[key].get("metrics")]
    return {"comparable_configuration": all(before["metadata"].get(key) == after["metadata"].get(key) for key in ("datasets", "live", "k", "evaluator_sha256")),
            "regressions": sum(item["before"] == "pass" and item["after"] != "pass" for item in changes),
            "added": [list(key) for key in sorted(new.keys() - old.keys())],
            "removed": [list(key) for key in sorted(old.keys() - new.keys())], "changes": changes}


def main(argv=None):
    parser = argparse.ArgumentParser(description="부동산 컨시어지 계산·검색·대화 평가")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("listing-check", help="실제 매물 원문과 사람이 확인한 정답 대조")
    listing.add_argument("--dataset", type=Path, required=True)
    listing.add_argument("--live", action="store_true", required=True)
    listing.add_argument("--max-cases", type=positive_int, default=3)
    listing.add_argument("--output", type=Path, default=ROOT / "evaluation-results/listing-live.json")
    run = sub.add_parser("run", help="평가 실행과 JSON·HTML 보고서 생성")
    run.add_argument("--suite", choices=["decision", "avm", "intent", "calculator", "rag", "chat", "all"], default="calculator")
    run.add_argument("--dataset", type=Path)
    run.add_argument("--live", action="store_true", help="실제 모델·설정된 검색 저장소 사용 (외부 호출 가능)")
    run.add_argument("--repeat", type=positive_int, default=1)
    run.add_argument("--max-cases", type=positive_int, default=100)
    run.add_argument("--timeout", type=positive_int, default=120, help="대화 시나리오 전체를 포함한 사례별 제한 시간(초)")
    run.add_argument("--k", type=positive_int, default=4)
    run.add_argument("--output", type=Path, default=ROOT / "evaluation-results")
    validate = sub.add_parser("validate", help="데이터 스키마와 사례 ID 검증")
    validate.add_argument("dataset", type=Path)
    comparison = sub.add_parser("compare", help="두 실행의 회귀와 검색 지표 비교")
    comparison.add_argument("baseline", type=Path)
    comparison.add_argument("current", type=Path)
    legacy = sub.add_parser("import-rag", help="기존 평가 질문의 정적 목록을 공통 데이터셋으로 변환")
    legacy.add_argument("source", type=Path)
    legacy.add_argument("destination", type=Path)
    legacy.add_argument("--question-key", default="question")
    legacy.add_argument("--titles-key", default="relevant_titles")
    legacy.add_argument("--variable", help="Python 파일에서 가져올 목록 상수 이름")
    review = sub.add_parser("review", help="사람 검토 파일의 완결성과 점수 집계")
    review.add_argument("results", type=Path)
    review.add_argument("reviews", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "listing-check":
            import asyncio
            from evaluation.listing_live import evaluate
            if args.max_cases > 10:
                raise ValueError("한 번에 최대 10건까지 검증할 수 있습니다")
            result = asyncio.run(evaluate(args.dataset, args.output, args.max_cases))
            print(f"실제 매물 대조: {result['passed']}/{result['total']} 통과 · {args.output}")
            return 0 if result["passed"] == result["total"] else 1
        if args.command == "import-rag":
            from evaluation.legacy import import_rag
            result = import_rag(args.source, question_key=args.question_key, titles_key=args.titles_key, variable=args.variable)
            args.destination.parent.mkdir(parents=True, exist_ok=True)
            with args.destination.open("x", encoding="utf-8") as output:
                output.write(result.model_dump_json(indent=2))
            print(f"{len(result.cases)}개 사례 변환: {args.destination}")
            return 0
        if args.command == "review":
            from evaluation.review import Reviews, summarize_reviews
            result = summarize_reviews(json.loads(args.results.read_text(encoding="utf-8")),
                                       Reviews.model_validate_json(args.reviews.read_text(encoding="utf-8")))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["pending"] or result["failed"] else 0
        if args.command == "validate":
            dataset, cases = load_dataset(args.dataset)
            print(f"{dataset.suite}: {len(cases)}개 사례 검증 완료")
            return 0
        if args.command == "compare":
            result = compare_reports(args.baseline, args.current)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["regressions"] or result["removed"] or not result["comparable_configuration"] else 0
        if args.suite in {"chat", "intent"} and not args.live:
            parser.error("대화·의도 평가에는 실제 모델을 사용하는 --live를 지정하세요")
        if args.dataset and args.suite == "all":
            parser.error("사용자 데이터셋은 개별 --suite와 함께 지정하세요")
        suites = (["decision", "avm", "calculator", "rag", "intent", "chat"] if args.live else ["decision", "avm", "calculator", "rag"]) if args.suite == "all" else [args.suite]
        paths = [args.dataset or DATASETS / f"{suite}.json" for suite in suites]
        jobs = []
        for suite, path in zip(suites, paths):
            dataset, cases = load_dataset(path)
            if dataset.suite != suite:
                raise ValueError("데이터셋 suite와 실행 suite가 다릅니다")
            jobs.extend((suite, case) for case in cases)
        omitted = max(0, len(jobs) - args.max_cases)
        jobs = jobs[:args.max_cases]
        if args.live:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env", override=False)
        meta = metadata(args, paths)
        meta["selected_suites"] = suites
        meta["omitted_cases"] = omitted
        meta["selected_cases"] = [{"suite": suite, "id": case.id} for suite, case in jobs]
        results = []
        print(f"{len(jobs)}개 사례 × {args.repeat}회. {'설정된 실제 자원 사용 (실행 영역별 범위는 보고서 참조)' if args.live else '고정·가상 입력 평가 (실거래 정확도·실제 대화 미평가)'}", flush=True)
        if omitted:
            print(f"--max-cases 제한으로 {omitted}개 사례는 실행하지 않습니다.", flush=True)
        for repetition in range(1, args.repeat + 1):
            for suite, case in jobs:
                result = run_case(suite, case, live=args.live, k=args.k, timeout=args.timeout)
                result["repeat"] = repetition
                results.append(result)
                print(f"[{suite}] {case.id} #{repetition}: {result['status']}", flush=True)
        directory = args.output / meta["run_id"]
        report = write_report(directory, meta, results)
        print(f"보고서: {directory / 'report.html'}")
        print(json.dumps(report["summary"], ensure_ascii=False))
        return 2 if report["summary"]["errors"] else 1 if report["summary"]["failed"] else 0
    except (ValueError, OSError, ValidationError, SyntaxError) as exc:
        # 사용자 데이터셋 자체의 검증 메시지 외에 환경 자격증명을 포함할 수 있는 예외 원문은 출력하지 않는다.
        print(f"평가 실행 설정 오류: {type(exc).__name__}. 데이터셋 스키마·경로·suite를 확인하세요.", file=sys.stderr)
        return 2
