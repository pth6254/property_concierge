"""운영 상태 외부 알림: 백업 기록 판정, 문구, 연속 확인 후 전송·중복 방지·전달 실패 재시도."""
import json
import time

from api.operational_health import ALERTS, AlertNotifier, alert_message, alert_problems, backup_state


class MemoryRedis:
    def __init__(self, fail=False):
        self.values, self.fail = {}, fail

    def get(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        return self.values.get(key)

    def set(self, key, value):
        if self.fail:
            raise ConnectionError("redis down")
        self.values[key] = value


def notifier(redis, results=None, stable=2):
    sent = []
    outcomes = iter(results or [])

    def sender(message):
        sent.append(message)
        return next(outcomes, True)

    return AlertNotifier("https://hooks.example.invalid/x", redis_factory=lambda: redis, sender=sender, stable=stable), sent


def test_backup_state_matches_operations_screen_rules(tmp_path):
    path = tmp_path / "backup-status.json"
    now = time.time()
    assert backup_state(str(path), now) is None  # 백업 서비스를 쓰지 않는 환경은 알리지 않는다
    path.write_text(json.dumps({"status": "ok", "checked_at": now - 3600, "bytes": 1}), encoding="utf-8")
    assert backup_state(str(path), now) == "ok"
    path.write_text(json.dumps({"status": "ok", "checked_at": now - 27 * 3600, "bytes": 1}), encoding="utf-8")
    assert backup_state(str(path), now) == "stale"
    path.write_text(json.dumps({"status": "failed", "checked_at": now, "bytes": 0}), encoding="utf-8")
    assert backup_state(str(path), now) == "failed"
    path.write_text("{broken", encoding="utf-8")
    assert backup_state(str(path), now) == "unreadable"
    path.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    assert backup_state(str(path), now) == "unreadable"


def test_alert_problems_and_message_name_failed_checks():
    state = {"checks": {"database": "ok", "worker": "down", "queue": "delayed", "redis": "ok"}}
    problems = alert_problems(state, "stale")
    assert problems == ["queue:delayed", "worker:down", "backup:stale"]
    message = alert_message(problems)
    assert "AI 실행기 중단" in message and "작업 대기열 지연" in message and "정기 백업 26시간 넘게 성공 없음" in message
    assert alert_problems({"checks": {"database": "ok"}}, None) == []
    assert "정상" in alert_message([])


def test_notifier_waits_for_stable_state_and_does_not_repeat():
    redis = MemoryRedis()
    alerts, sent = notifier(redis)
    assert alerts.observe(["worker:down"]) is False  # 한 번만 보인 상태는 보내지 않는다
    assert alerts.observe(["worker:down"]) is True
    assert alerts.observe(["worker:down"]) is False  # 같은 장애를 반복해 알리지 않는다
    assert len(sent) == 1 and "AI 실행기 중단" in sent[0]
    assert redis.values[f"{ALERTS}:notified"] == json.dumps(["worker:down"])

    alerts.observe([])
    assert alerts.observe([]) is True
    assert "정상" in sent[-1]

    # 감시를 재시작해도 Redis에 남은 마지막 알림과 같으면 다시 보내지 않는다.
    restarted, resent = notifier(redis)
    restarted.observe([]); restarted.observe([])
    assert resent == []


def test_notifier_ignores_flapping_and_skips_startup_recovery():
    alerts, sent = notifier(MemoryRedis())
    for problems in (["queue:delayed"], [], ["queue:delayed"], []):
        alerts.observe(problems)
    assert sent == []  # 감시 시작이 정상이면 복구 알림도 보내지 않는다
    alerts.observe([]); alerts.observe([])
    assert sent == []


def test_notifier_retries_failed_delivery_and_works_without_redis():
    alerts, sent = notifier(MemoryRedis(fail=True), results=[False, True])
    alerts.observe(["redis:down"])
    assert alerts.observe(["redis:down"]) is False  # 전달 실패는 알린 것으로 기록하지 않는다
    assert alerts.observe(["redis:down"]) is True   # Redis가 없어도 메모리 기준으로 다시 보낸다
    assert alerts.observe(["redis:down"]) is False
    assert len(sent) == 2


def test_notifier_requires_https_webhook(monkeypatch):
    monkeypatch.setenv("OPS_ALERT_WEBHOOK_URL", "")
    assert AlertNotifier.from_env() is None
    monkeypatch.setenv("OPS_ALERT_WEBHOOK_URL", "http://hooks.example.invalid/x")
    assert AlertNotifier.from_env() is None
    monkeypatch.setenv("OPS_ALERT_WEBHOOK_URL", "https://hooks.example.invalid/x")
    assert AlertNotifier.from_env() is not None
