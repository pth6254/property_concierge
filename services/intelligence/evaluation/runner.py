"""실제 모델 평가를 별도 프로세스로 실행해 시간 초과 후 로컬 실행을 종료한다."""
from __future__ import annotations

import contextlib
import io
import multiprocessing
from time import perf_counter

from evaluation.schema import CalculatorCase, ChatCase, RagCase
from evaluation import suites


def _execute(suite, payload, live, k, on_progress=None):
    from evaluation.decision_schema import DecisionCase, AvmCase, IntentCase
    from evaluation import decision_suites
    if suite == "decision":
        return decision_suites.decision(DecisionCase.model_validate(payload))
    if suite == "avm":
        return decision_suites.avm(AvmCase.model_validate(payload), live=live)
    if suite == "intent" and live:
        return decision_suites.intent(IntentCase.model_validate(payload), on_progress=on_progress)
    if suite == "calculator":
        return suites.calculator(CalculatorCase.model_validate(payload))
    if suite == "rag":
        return suites.rag(RagCase.model_validate(payload), live=live, k=k)
    if suite == "chat" and live:
        return suites.chat(ChatCase.model_validate(payload), on_progress=on_progress)
    raise ValueError("대화·의도 평가는 --live가 필요합니다")


def _worker(connection, suite, payload, live, k):
    try:
        # 서비스의 예외 로그에는 접속 정보가 포함될 수 있어 원문 로그를 보고서에 복제하지 않는다.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = _execute(suite, payload, live, k, on_progress=lambda value: connection.send(("progress", value)))
        connection.send(("result", result))
    except Exception as exc:
        connection.send(("error", type(exc).__name__))
    finally:
        connection.close()


def run_case(suite: str, case, *, live: bool, k: int, timeout: float) -> dict:
    started = perf_counter()
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, suite, case.model_dump(), live, k))
    process.start()
    sender.close()
    progress = {}
    try:
        while True:
            remaining = timeout - (perf_counter() - started)
            if remaining <= 0 or not receiver.poll(remaining):
                error = "Timeout"
                break
            try:
                kind, value = receiver.recv()
            except EOFError:
                kind, value = "error", "WorkerExited"
            if kind == "progress":
                progress = value
                continue
            if kind == "result":
                return value
            error = value
            break
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join()
        receiver.close()
    return {"id": case.id, "suite": suite, "status": "error", "elapsed_seconds": round(perf_counter() - started, 4),
            "checks": [], "details": {**progress, "error_type": error}, "metrics": {}, "review_required": suite == "chat"}
