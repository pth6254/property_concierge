"""실행 중인 로컬 서비스의 연결만 검증한다. 생성한 검증 계정만 삭제한다."""
from __future__ import annotations

import json
import secrets
import subprocess
import time
import uuid
from pathlib import Path

import requests


def main():
    root = Path(__file__).resolve().parents[1]
    names = ["property_concierge_backend", "property_concierge_core", "property_concierge-job-worker-1"]
    containers = json.loads(subprocess.check_output(["docker", "inspect", *names], text=True))
    environments = [{value.split("=", 1)[0]: value.split("=", 1)[1] for value in container["Config"]["Env"]}
                    for container in containers]
    session = requests.Session()
    web, core = "http://127.0.0.1:3002", "http://127.0.0.1:8002"
    report = {"status": "running", "checks": [], "boundaries": [
        "로컬 실행 서비스 연결 검증", "검증 전용 임시 계정만 생성·삭제", "실제 AVM·LLM·외부 매물 정확도 제외",
    ]}
    registered = False
    def check(label):
        report["checks"].append(label)
        print("PASS", label, flush=True)
    def require(reply, status=200):
        assert reply.status_code == status, f"서비스 응답 코드: {reply.status_code} (예상 {status})"
        return reply.json()
    try:
        api_env, core_env, worker_env = environments
        assert not containers[0]["HostConfig"]["PortBindings"], "Python이 외부에 노출되어 있습니다"
        assert api_env["CORE_STORAGE_URL"] == worker_env["CORE_STORAGE_URL"] == "http://core:8080"
        assert api_env["REQUIRE_INTERNAL_SERVICE_AUTH"] == "1"
        assert len(core_env["INTERNAL_SERVICE_SECRET"]) >= 32
        assert len({env["INTERNAL_SERVICE_SECRET"] for env in environments}) == 1
        assert len({env["JWT_SECRET_KEY"] for env in environments}) == 1
        for endpoint in (web, core):
            assert require(requests.get(endpoint + "/ready", timeout=8))["status"] == "ready"
        check("실제 공개 포트·내부 인증·API/실행기 저장 책임·준비 상태 일치")
        user = require(session.post(web + "/api/auth/register", timeout=10, json={
            "email": f"spring-deployment-{uuid.uuid4().hex}@example.com",
            "password": secrets.token_urlsafe(24), "name": "배포 연결 검증",
        }), 201)
        registered = True
        assert require(session.get(core + "/api/auth/me", timeout=8))["id"] == user["id"]
        check("실제 Caddy 웹 가입 쿠키와 Spring 직접 조회 호환")
        # 토큰을 명령 인자·환경·로그에 남기지 않고 컨테이너 표준입력으로 전달한다.
        probe = "import sys,json,requests; d=json.load(sys.stdin); print(requests.get('http://127.0.0.1:8000/api/auth/me',headers={'Cookie':'auth_token='+d['token']},timeout=5).status_code)"
        reply = subprocess.check_output(["docker", "exec", "-i", names[0], "python", "-c", probe],
            input=json.dumps({"token": session.cookies.get("auth_token")}), text=True)
        assert reply.strip() == "401"
        check("실제 Python이 유효한 사용자 쿠키만 가진 직접 요청을 차단")
        job_id = require(requests.post(core + "/internal/v1/store/jobs/create_task", timeout=8,
            headers={"X-Internal-Service-Key": core_env["INTERNAL_SERVICE_SECRET"]},
            json={"task_type": "probe", "payload": {}, "owner_id": user["id"]}))
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            state = require(session.get(core + f"/api/appraisal/jobs/{job_id}", timeout=8))
            if state["status"] in ("done", "error"):
                break
            time.sleep(.2)
        assert state["status"] == "done" and state["result"] == {"worker": "ready"}
        stream = session.get(web + f"/api/jobs/{job_id}/events", timeout=8)
        assert stream.status_code == 200 and "text/event-stream" in stream.headers["content-type"]
        assert '"status":"done"' in stream.text
        check("실제 Spring 접수→Redis→Python 실행기→Spring 결과 저장·Caddy SSE")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=type(error).__name__)
        raise
    finally:
        if registered:
            reply = session.delete(web + "/api/auth/me", timeout=10)
            if reply.status_code != 200:
                report.update(status="failed", cleanup="검증 계정 제거 실패")
                raise RuntimeError("검증 계정 제거 실패")
        output = root / "evaluation-results/spring-deployment-result.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
