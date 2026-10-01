"""시크릿이 포함된 Compose 설정을 출력하지 않고 공개 포트·저장 책임만 점검한다."""
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


def main():
    root = Path(__file__).resolve().parents[1]
    for production in (False, True):
        args = ["docker", "compose", "--project-directory", str(root), "-p", "property_concierge", "-f", "infrastructure/compose/compose.yml"]
        if production:
            args += ["-f", "infrastructure/compose/compose.production.yml"]
        result = subprocess.run(args + ["config", "--format", "json"], cwd=root,
            env=os.environ | {"SERVICE_DOMAIN": "deployment-check.invalid"}, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("Compose 검증 실패: 필수 환경변수와 Docker Compose 버전을 확인하세요")
        services = json.loads(result.stdout)["services"]
        for name in ("api", "frontend"):
            assert not services[name].get("ports"), f"{name}가 직접 공개되어 있습니다"
        for name in ("api", "job-worker"):
            assert services[name]["environment"]["CORE_STORAGE_URL"] == "http://core:8080", "API와 실행기 저장 책임 불일치"
        assert services["api"]["environment"]["REQUIRE_INTERNAL_SERVICE_AUTH"] == "1"
        assert services["api"]["environment"]["FORWARDED_ALLOW_IPS"] == "172.31.244.2"
        assert services["frontend"]["build"]["args"]["NEXT_PUBLIC_API_URL"] == "http://core:8080"
        if production:
            assert not services["core"].get("ports"), "운영 Spring이 HTTPS 프록시를 우회합니다"
            assert {p["target"] for p in services["gateway"]["ports"]} == {80, 443}
            assert services["core"]["environment"]["APP_ENV"] == "production"
        else:
            assert services["core"]["ports"][0]["target"] == 8080
            assert services["gateway"]["ports"][0]["target"] == 3000
        ports = {name: [p["published"] for p in services[name].get("ports", [])]
                 for name in ("api", "core", "frontend", "gateway")}
        print(json.dumps({"mode": "production" if production else "local", "status": "passed", "ports": ports}))


if __name__ == "__main__":
    main()
