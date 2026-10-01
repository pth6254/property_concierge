"""서비스 데이터에 접근하지 않는 Spring·Python 연결 검증 실행기."""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / ".env", override=False)
    raw = os.getenv("TEST_DATABASE_URL") or URL.create("postgresql", username=os.getenv("POSTGRES_USER", "postgres"),
        password=os.environ["POSTGRES_PASSWORD"], host="localhost", port=5432, database="real_estate_test").render_as_string(hide_password=False)
    database = make_url(raw)
    if database.database != "real_estate_test" or database.drivername not in ("postgresql", "postgresql+psycopg2"):
        raise SystemExit("real_estate_test PostgreSQL만 검증할 수 있습니다")
    admin = create_engine(database.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        if not connection.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname='real_estate_test'").scalar():
            connection.exec_driver_sql("CREATE DATABASE real_estate_test")
    admin.dispose()
    settings = {"DATABASE_URL": raw, "TEST_DATABASE_URL": raw, "REDIS_URL": "redis://localhost:6379/15",
        "TEST_REDIS_URL": "redis://localhost:6379/15", "APP_ENV": "development", "DISABLE_RATE_LIMIT": "1",
        "JWT_SECRET_KEY": "spring-isolated-test-secret-not-used-in-production",
        "INTERNAL_SERVICE_SECRET": secrets.token_urlsafe(48), "LANGCHAIN_TRACING_V2": "false", "CORE_STORAGE_URL": "",
        "REQUIRE_INTERNAL_SERVICE_AUTH": "0"}
    env = os.environ | settings
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, "scripts/seed_browser_regions.py", "--transactions"], cwd=ROOT,
                   env=env | {"BROWSER_TEST_DB": "1"}, check=True)
    from redis import Redis
    Redis.from_url(settings["REDIS_URL"]).flushdb()
    containers = ["property_concierge_spring_test_core", "property_concierge_spring_test_api", "property_concierge_spring_test_worker"]
    for name in containers:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    handle, filename = tempfile.mkstemp(prefix="property-core-test-", suffix=".env")
    try:
        container_settings = settings | {"DATABASE_URL": database.set(host="pgvector", port=5432).render_as_string(hide_password=False),
            "TEST_DATABASE_URL": database.set(host="pgvector", port=5432).render_as_string(hide_password=False),
            "REDIS_URL": "redis://redis:6379/15", "TEST_REDIS_URL": "redis://redis:6379/15",
            "PYTHON_AI_URL": "http://property-core-test-ai:8000", "CORE_STORAGE_URL": "http://property-core-test-core:8080",
            "REQUIRE_INTERNAL_SERVICE_AUTH": "1"}
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            output.write("\n".join(f"{key}={value}" for key, value in container_settings.items()))
        for name, image, port, command in [
            (containers[1], "property_concierge_backend:latest", "127.0.0.1:8012:8000", ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]),
            (containers[0], "property_concierge_core:latest", "127.0.0.1:8013:8080", []),
            (containers[2], "property_concierge_backend:latest", None, ["python", "-m", "api.job_worker"])]:
            if "--pytest" in sys.argv and name == containers[2]:
                continue
            args = ["docker", "run", "-d", "--name", name, "--network", os.getenv("SPRING_TEST_NETWORK", "property_concierge_default"), "--env-file", filename]
            if port:
                args.extend(["-p", port])
            if name != containers[0]:
                if name == containers[1]:
                    args.extend(["--network-alias", "property-core-test-ai"])
                for directory in ("api", "backend", "schemas"):
                    args.extend(["-v", f"{ROOT / directory}:/app/{directory}:ro"])
            else:
                args.extend(["--network-alias", "property-core-test-core"])
            subprocess.run(args + [image] + command, capture_output=True, check=True)
        for port in (8012, 8013):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("격리 검증 서비스가 기동하지 못했습니다")
        env.update(CORE_STORAGE_URL="http://127.0.0.1:8013", TEST_CORE_URL="http://127.0.0.1:8013")
        if "--pytest" in sys.argv:
            return subprocess.call([sys.executable, "-m", "pytest", *sys.argv[sys.argv.index("--pytest") + 1:]], cwd=ROOT, env=env)
        if "--evaluation" in sys.argv:
            return subprocess.call([sys.executable, "-m", "evaluation", "run", "--suite", "all", "--timeout", "30"], cwd=ROOT, env=env)
        result = subprocess.call([sys.executable, "scripts/verify_spring_core.py", "http://127.0.0.1:8013", "http://127.0.0.1:8012"], cwd=ROOT, env=env)
        if result:
            return result
        result = subprocess.call([sys.executable, "scripts/verify_core_calculations.py", "http://127.0.0.1:8013"], cwd=ROOT, env=env)
        if result:
            return result
        from verify_spring_gateway import verify
        verify(os.getenv("SPRING_TEST_NETWORK", "property_concierge_default"), filename, settings["REDIS_URL"])
        if "--browser" not in sys.argv:
            return 0
        node = shutil.which("node") or shutil.which("node.exe")
        if not node:
            raise RuntimeError("브라우저 검증에 Node.js가 필요합니다")
        def node_path(path):
            return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip() if node.endswith(".exe") else str(path)
        browser_env = env | {"PLAYWRIGHT_MODULE_PATH": node_path(ROOT / "frontend/node_modules/playwright"), "NEXT_TELEMETRY_DISABLED": "1"}
        if node.endswith(".exe"):
            # WSL 프로세스의 환경변수는 WSLENV에 지정한 항목만 Windows Node로 전달된다.
            # 주소 브라우저의 WSL 서명 도우미에도 같은 격리 JWT 키가 전달되어야 한다.
            names = "PLAYWRIGHT_MODULE_PATH/w:NEXT_TELEMETRY_DISABLED/w:E2E_BROWSER/w:JWT_SECRET_KEY"
            browser_env["WSLENV"] = ":".join(filter(None, (browser_env.get("WSLENV"), names)))
        for script in ("verify_listing_import_browser.cjs", "verify_navigation_browser.cjs", "verify_service_quality_browser.cjs",
                       "verify_candidate_funding_browser.cjs", "verify_decision_assessment_browser.cjs", "verify_listing_address_browser.cjs"):
            subprocess.run([node, node_path(ROOT / "scripts" / script), "http://127.0.0.1:8013"], cwd=ROOT, env=browser_env, check=True)
        return 0
    finally:
        for name in containers:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        Path(filename).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
