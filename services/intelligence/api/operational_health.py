"""기동 여부와 서비스 준비 상태를 분리한다. 외부 호출·사용자 데이터는 조회하지 않는다."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from sqlalchemy import text

from api import jobs
from db.base import get_engine
from db.redis_client import get_redis

logger = logging.getLogger(__name__)
WORKERS = f"{jobs.STREAM}:workers"
ALERTS = f"{jobs.STREAM}:ops-alerts"


def worker_heartbeat(consumer: str) -> None:
    client = get_redis()
    now = time.time()
    with client.pipeline() as pipe:
        pipe.zadd(WORKERS, {consumer: now})
        pipe.zremrangebyscore(WORKERS, "-inf", now - 300)
        pipe.expire(WORKERS, 300)
        pipe.execute()


def snapshot() -> dict:
    checks = {"database": "down", "legal_regions": "missing", "redis": "down", "worker": "down", "queue": "unknown"}
    queue = {"waiting": None, "in_progress": None, "oldest_wait_seconds": None}
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            connection.execute(text("SELECT 1"))
            # DB 연결만으로는 매물 주소 연결이 가능한지 알 수 없다. 동 기준정보가
            # 비어 있으면 등록·후보 저장이 실패하므로 준비 상태에서 드러낸다.
            if connection.scalar(text("SELECT EXISTS (SELECT 1 FROM legal_regions WHERE is_active AND level = 'eup_myeon_dong' AND sido_code = '11')")):
                checks["legal_regions"] = "ok"
        checks["database"] = "ok"
    except Exception:
        pass
    try:
        client = get_redis()
        client.ping()
        checks["redis"] = "ok"
        if client.zcount(WORKERS, time.time() - 30, "+inf"):
            checks["worker"] = "ok"
        if client.exists(jobs.STREAM):
            groups = client.xinfo_groups(jobs.STREAM)
            group = next((g for g in groups if g["name"] == jobs.GROUP), None)
            if group:
                waiting = group.get("lag")
                first = client.xrange(jobs.STREAM, min=f"({group['last-delivered-id']}", max="+", count=1)
                age = max(0, time.time() - int(first[0][0].split("-")[0]) / 1000) if first else 0
                queue = {"waiting": waiting, "in_progress": group["pending"], "oldest_wait_seconds": round(age)}
                checks["queue"] = "delayed" if age > 120 or (waiting or 0) > 100 else "ok"
    except Exception:
        pass
    core_url = os.getenv("CORE_HEALTH_URL", "").strip()
    if core_url:
        # /ready는 Python을 다시 점검하므로 순환 호출을 피하고 Spring 생존만 따로 확인한다.
        import requests
        checks["core"] = "down"
        try:
            response = requests.get(core_url, timeout=2, allow_redirects=False)
            if response.status_code == 200 and response.json().get("status") == "ok":
                checks["core"] = "ok"
        except (requests.RequestException, ValueError, AttributeError):
            pass
    return {"status": "ready" if all(v == "ok" for v in checks.values()) else "degraded",
            "checks": checks, "queue": queue, "checked_at": time.time()}


def record_transition(state: dict) -> None:
    """같은 장애를 반복 알리지 않고 장애·복구 전환을 운영 알림함에 남긴다."""
    import json
    client = get_redis()
    value = json.dumps(state["checks"], sort_keys=True)
    previous = client.getset(f"{ALERTS}:state", value)
    if previous != value:
        client.xadd(ALERTS, {"status": state["status"], "checks": value, "at": str(state["checked_at"])},
                    maxlen=200, approximate=False)
        logger.warning("운영 상태 변경: %s", value)


CHECK_LABELS = {"database": "DB", "legal_regions": "법정동 기준정보", "redis": "Redis", "worker": "AI 실행기",
                "queue": "작업 대기열", "core": "Spring API", "backup": "정기 백업"}
VALUE_LABELS = {"down": "중단", "missing": "누락", "delayed": "지연", "unknown": "확인 불가",
                "failed": "실패", "stale": "26시간 넘게 성공 없음", "unreadable": "기록 읽기 실패"}


def backup_state(path: str | None = None, now: float | None = None) -> str | None:
    """정기 백업 기록 상태. 백업 서비스를 쓰지 않아 기록 파일이 없으면 None(알리지 않음)."""
    target = Path(path or os.getenv("BACKUP_STATUS_PATH", "/app/backups/backup-status.json"))
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return "unreadable"
    status, checked = data.get("status"), data.get("checked_at")
    if status not in {"ok", "failed"} or not isinstance(checked, (int, float)):
        return "unreadable"
    # 운영 화면(OperationsController.backup)과 같은 26시간 기준이다.
    if status == "ok" and (now if now is not None else time.time()) - checked > 26 * 3600:
        return "stale"
    return status


def alert_problems(state: dict, backup: str | None) -> list[str]:
    problems = sorted(f"{name}:{value}" for name, value in state["checks"].items() if value != "ok")
    if backup not in (None, "ok"):
        problems.append(f"backup:{backup}")
    return problems


def alert_message(problems: list[str]) -> str:
    if not problems:
        return "[부동산 컨시어지] 운영 상태가 정상으로 돌아왔습니다."
    parts = []
    for problem in problems:
        name, _, value = problem.partition(":")
        parts.append(f"{CHECK_LABELS.get(name, name)} {VALUE_LABELS.get(value, value)}")
    return "[부동산 컨시어지] 운영 점검 실패: " + ", ".join(parts)


class AlertNotifier:
    """운영 상태 전환을 외부 웹훅(Slack 호환 {"text": ...})으로 보낸다.

    - 같은 문제 조합이 연속 `stable`회(기본 2회, 약 30초) 확인돼야 보낸다. 대기열 지연처럼 잠깐 넘나드는 상태로 알림이 쏟아지지 않게 한다.
    - 마지막으로 알린 조합을 Redis에 둬서 감시 컨테이너를 재시작해도 같은 장애를 다시 알리지 않는다.
      Redis 자체가 장애일 때도 알려야 하므로 Redis를 못 쓰면 프로세스 메모리 값으로 계속 판단한다.
    - 전달에 실패하면 알린 것으로 기록하지 않아 다음 주기에 다시 보낸다.
    """

    _UNSET = object()

    def __init__(self, webhook: str, redis_factory=None, sender=None, stable: int = 2):
        self.webhook = webhook
        self.redis_factory = redis_factory or get_redis
        self.sender = sender or self._post
        self.stable = stable
        self.candidate: str | None = None
        self.seen = 0
        self.notified: object = self._UNSET

    @classmethod
    def from_env(cls) -> "AlertNotifier | None":
        from urllib.parse import urlsplit
        webhook = os.getenv("OPS_ALERT_WEBHOOK_URL", "").strip()
        if not webhook:
            return None
        if urlsplit(webhook).scheme != "https":
            logger.error("OPS_ALERT_WEBHOOK_URL은 HTTPS 주소여야 합니다. 외부 알림을 보내지 않습니다")
            return None
        return cls(webhook)

    def _post(self, message: str) -> bool:
        import requests
        try:
            response = requests.post(self.webhook, json={"text": message}, timeout=5, allow_redirects=False)
            return 200 <= response.status_code < 300
        except requests.RequestException:
            return False

    def _last_notified(self) -> str | None:
        if self.notified is self._UNSET:
            try:
                self.notified = self.redis_factory().get(f"{ALERTS}:notified")
            except Exception:
                self.notified = None
        return self.notified  # type: ignore[return-value]

    def observe(self, problems: list[str]) -> bool:
        key = json.dumps(problems)
        if key == self.candidate:
            self.seen += 1
        else:
            self.candidate, self.seen = key, 1
        if self.seen < self.stable:
            return False
        previous = self._last_notified()
        if previous == key:
            return False
        # 감시 시작 직후가 정상이면 "복구" 알림을 보낼 이유가 없다.
        if previous is None and not problems:
            self._remember(key)
            return False
        if not self.sender(alert_message(problems)):
            # 웹훅 주소에는 토큰이 들어 있으므로 로그에 남기지 않는다.
            logger.warning("외부 운영 알림 전달 실패. 다음 점검에서 다시 보냅니다")
            return False
        self._remember(key)
        return True

    def _remember(self, key: str) -> None:
        self.notified = key
        try:
            self.redis_factory().set(f"{ALERTS}:notified", key)
        except Exception:
            pass


def monitor(stop) -> None:
    # 실행기와 독립된 프로세스에서 관찰해야 실행기 자체의 종료도 감지한다.
    notifier = AlertNotifier.from_env()
    while not stop.is_set():
        state = None
        try:
            state = snapshot()
            record_transition(state)
        except Exception:
            logger.error("운영 상태 저장 실패: Redis 연결을 확인하세요")
        if notifier and state is not None:
            try:
                notifier.observe(alert_problems(state, backup_state()))
            except Exception:
                logger.error("외부 운영 알림 처리 실패")
        stop.wait(15)


if __name__ == "__main__":
    import threading
    monitor(threading.Event())
