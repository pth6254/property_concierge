"""격리 Spring·Caddy에서 직접/프록시 요청의 위조 IP 제한 우회를 검증한다."""
from __future__ import annotations

from pathlib import Path as _WorkspacePath
import sys as _workspace_sys
_workspace_sys.path.insert(0, str(_WorkspacePath(__file__).resolve().parents[1] / "services/intelligence"))
from concierge_workspace import ensure_import_paths as _ensure_import_paths
_ensure_import_paths()


import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import requests
from redis import Redis


def verify(network: str, environment_file: str, redis_url: str):
    if urlsplit(redis_url).path != "/15":
        raise RuntimeError("프록시 검증은 Redis 15에서만 실행할 수 있습니다")
    client = Redis.from_url(redis_url, decode_responses=True)
    gateway, core = "property_concierge_spring_test_gateway", "property_concierge_spring_test_limits"
    report = {"status": "running", "checks": []}
    def docker(*args):
        return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.PIPE).strip()
    try:
        for name in (gateway, core):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        with tempfile.TemporaryDirectory(prefix="property-core-gateway-") as directory:
            config = Path(directory) / "Caddyfile"
            config.write_text(":3000 {\n reverse_proxy property-core-test-limits:8080\n}\n", encoding="utf-8")
            docker("run", "-d", "--name", gateway, "--network", network, "-p", "127.0.0.1:8015:3000",
                   "-v", f"{config}:/etc/caddy/Caddyfile:ro", "caddy:2-alpine")
            address = json.loads(docker("inspect", gateway))[0]["NetworkSettings"]["Networks"][network]["IPAddress"]
            docker("run", "-d", "--name", core, "--network", network, "--network-alias", "property-core-test-limits",
                   "--env-file", environment_file, "-e", "DISABLE_RATE_LIMIT=0", "-e", f"TRUSTED_PROXY_IPS={address.replace('.', chr(92)+'.')}",
                   "-p", "127.0.0.1:8014:8080", "property_concierge_core:latest")
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    if requests.get("http://127.0.0.1:8015/health", timeout=2).status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("프록시 검증 서비스 기동 실패")
            for url, label in [("http://127.0.0.1:8014", "Spring 직접 접속의 위조 IP 무시"),
                               ("http://127.0.0.1:8015", "Caddy 경유 실제 IP 보존·위조 헤더 제거")]:
                keys = list(client.scan_iter("core-limit:login:*"))
                if keys:
                    client.delete(*keys)
                for attempt in range(11):
                    reply = requests.post(url + "/api/auth/login", timeout=5,
                        json={"email": f"spoof-{uuid.uuid4().hex}@example.com", "password": "invalid-login-123"},
                        headers={"X-Forwarded-For": f"203.0.113.{attempt+1}", "Forwarded": f"for=203.0.113.{attempt+1}"})
                    expected = 401 if attempt < 10 else 429
                    assert reply.status_code == expected, (label, attempt, reply.status_code)
                keys = list(client.scan_iter("core-limit:login:*"))
                assert len(keys) == 1 and "203.0.113." not in keys[0], keys
                assert client.ttl(keys[0]) > 0
                if url.endswith("8015"):
                    assert keys[0] != "core-limit:login:" + address, "프록시 IP로 모든 사용자를 합치면 안 됩니다"
                report["checks"].append(label)
                print("PASS", label, flush=True)
            report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        for name in (gateway, core):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        Path("evaluation-results").mkdir(exist_ok=True)
        Path("evaluation-results/spring-gateway-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
