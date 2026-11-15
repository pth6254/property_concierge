"""시크릿이 포함된 Compose 설정을 출력하지 않고 공개 포트·저장 책임·운영 추적 차단만 점검한다."""
from __future__ import annotations

from pathlib import Path as _WorkspacePath
import sys as _workspace_sys
_workspace_sys.path.insert(0, str(_WorkspacePath(__file__).resolve().parents[1] / "services/intelligence"))
from concierge_workspace import ensure_import_paths as _ensure_import_paths
_ensure_import_paths()


import json
import os
import subprocess
from pathlib import Path


# 배포 형태별 겹쳐 쓰는 파일과 필수 변수(검사용 값). scripts/compose.sh의 모드와 같다.
MODES = {
    "local": ([], {}),
    "production": (["infrastructure/compose/compose.production.yml"], {"SERVICE_DOMAIN": "deployment-check.invalid"}),
    "vercel": (["infrastructure/compose/compose.vercel.yml"], {
        "WEB_DOMAIN": "web.deployment-check.invalid", "API_DOMAIN": "api.deployment-check.invalid",
        "EDGE_PROXY_SECRET": "deployment-check-edge-secret-0000000000"}),
}
# LangSmith가 추적 여부를 읽는 순서대로 모두 고정해야 .env에 남은 다른 이름으로 켜지지 않는다(compose.production.yml 참고).
TRACING_VARS = ("LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_TRACING")
PYTHON_IMAGE = "property_concierge_backend:latest"


def render(root: Path, overlays: list[str], env: dict[str, str]) -> dict:
    args = ["docker", "compose", "--project-directory", str(root), "-p", "property_concierge",
            "-f", "infrastructure/compose/compose.yml"]
    for overlay in overlays:
        args += ["-f", overlay]
    # 유지보수 프로필의 수집·재학습 컨테이너도 같은 Python 이미지와 .env를 쓰므로 함께 렌더링한다.
    result = subprocess.run(args + ["--profile", "maintenance", "config", "--format", "json"], cwd=root,
        env=os.environ | env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Compose 검증 실패: 필수 환경변수와 Docker Compose 버전을 확인하세요")
    return json.loads(result.stdout)["services"]


def tracing_values(services: dict) -> dict[str, set]:
    python_services = {name: service for name, service in services.items() if service.get("image") == PYTHON_IMAGE}
    assert {"api", "job-worker"} <= set(python_services), "Python 서비스 목록을 확인할 수 없습니다"
    return {name: {(service.get("environment") or {}).get(var) for var in TRACING_VARS}
            for name, service in python_services.items()}


def main():
    root = Path(__file__).resolve().parents[1]
    for mode, (overlays, required) in MODES.items():
        deployed = mode != "local"
        # 셸이나 .env의 선택 값과 무관하게 기본값을 검사한다(빈 값이면 Compose가 :- 기본값을 쓴다).
        services = render(root, overlays, required | {"LANGSMITH_PRODUCTION_TRACING": ""})
        assert not services["api"].get("ports"), "api가 직접 공개되어 있습니다"
        for name in ("api", "job-worker"):
            assert services[name]["environment"]["CORE_STORAGE_URL"] == "http://core:8080", "API와 실행기 저장 책임 불일치"
        assert services["api"]["environment"]["REQUIRE_INTERNAL_SERVICE_AUTH"] == "1"
        assert services["api"]["environment"]["FORWARDED_ALLOW_IPS"] == "172.31.244.2"
        # Vercel 배포는 웹 컨테이너를 띄우지 않는다(docker-web 프로필).
        if mode == "vercel":
            assert "frontend" not in services, "Vercel 배포에서 웹 컨테이너가 실행됩니다"
        else:
            assert not services["frontend"].get("ports"), "frontend가 직접 공개되어 있습니다"
            assert services["frontend"]["build"]["args"]["NEXT_PUBLIC_API_URL"] == "http://core:8080"
        if deployed:
            assert not services["core"].get("ports"), "운영 Spring이 HTTPS 프록시를 우회합니다"
            assert {p["target"] for p in services["gateway"]["ports"]} == {80, 443}
            assert services["core"]["environment"]["APP_ENV"] == "production"
            # 운영은 LangSmith 추적을 기본으로 끄고(개인정보처리방침 미고지), 명시적으로 켤 때만 켠다.
            off = tracing_values(services)
            assert all(values == {"false"} for values in off.values()), f"운영 LangSmith 추적이 꺼져 있지 않습니다: {sorted(off)}"
            on = tracing_values(render(root, overlays, required | {"LANGSMITH_PRODUCTION_TRACING": "true"}))
            assert all(values == {"true"} for values in on.values()), "LANGSMITH_PRODUCTION_TRACING=true가 적용되지 않습니다"
        else:
            assert services["core"]["ports"][0]["target"] == 8080
            assert services["gateway"]["ports"][0]["target"] == 3000
        ports = {name: [p["published"] for p in services[name].get("ports", [])]
                 for name in ("api", "core", "frontend", "gateway") if name in services}
        report = {"mode": mode, "status": "passed", "ports": ports}
        if deployed:
            report["tracing_off"] = sorted(off)
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
