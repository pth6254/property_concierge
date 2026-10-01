"""실행 서비스의 익명 계산과 API·실행기 내부 호출을 점검한다. DB에 레코드를 쓰지 않는다."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import requests


def main():
    checks = []
    report = {"status": "running", "checks": checks,
              "boundary": "배포된 계산 연결 점검. 익명 계산과 컨테이너 내 직접 도구 실행이며 작업 큐·LLM·법령 정확도 평가는 제외."}
    def checked(name, value):
        assert value["engine"] == "kotlin-spring" and value["version"] == "finance-v1", value
        assert value["required_cash"] == 309600000 and value["monthly_payment"] == 1432246, value
        checks.append({"name": name, "status": "passed"}); print("PASS " + name)
    try:
        for root, label in (("http://127.0.0.1:8002", "실행 Spring 공개 API 계산"), ("http://127.0.0.1:3002", "실행 Caddy 웹 API 계산")):
            response = requests.post(root + "/api/simulation", json={"purchase_price": 600000000}, timeout=30)
            assert response.status_code == 200, (response.status_code, response.text[:300])
            result = response.json()["result"]
            checked(label, {"engine": result["calculator_engine"], "version": result["calculation_version"],
                "required_cash": result["required_cash"], "monthly_payment": result["loan"]["monthly_payment"]})
        code = """import json
from schemas.simulation import SimulationInput
from backend.tools.simulation_tool import run_simulation
from backend import tax_rules
result = run_simulation(SimulationInput(purchase_price=600000000, loan_amount=300000000))
assert tax_rules.calc_gift_tax(500000000)["tax"] == 77600000
print(json.dumps({"engine":result.calculator_engine,"version":result.calculation_version,
"required_cash":result.required_cash,"monthly_payment":result.loan.monthly_payment}))
"""
        for container, label in (("property_concierge_backend", "실행 Python API의 Kotlin 계산·세금 계약"),
                                  ("property_concierge-job-worker-1", "실행 Python 작업 컨테이너의 Kotlin 계산·세금 계약")):
            output = subprocess.run(["docker", "exec", container, "python", "-c", code], capture_output=True, text=True, check=True)
            checked(label, json.loads(output.stdout.strip().splitlines()[-1]))
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=type(error).__name__)
        raise
    finally:
        target = Path(__file__).resolve().parents[1] / "evaluation-results/calculation-deployment-result.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
