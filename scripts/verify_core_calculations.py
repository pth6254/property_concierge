"""격리 Spring 계산을 수기 정답·기존 수식·화면/대화/시나리오 경로로 대조한다."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))


def verify(root: str):
    from sqlalchemy.engine import make_url
    if make_url(os.environ["TEST_DATABASE_URL"]).database != "real_estate_test" or not os.environ["TEST_REDIS_URL"].endswith("/15"):
        raise RuntimeError("격리 DB·Redis에서만 계산 검증을 실행할 수 있습니다")
    from schemas.simulation import SimulationInput
    from backend.tools.simulation_tool import run_simulation
    from backend.concierge.decision_tools import simulate_investment
    from backend.services.chat_service import _run_tool
    headers = {"X-Internal-Service-Key": os.environ["INTERNAL_SERVICE_SECRET"]}
    report = {"status": "running", "checks": [], "differential_cases": 0,
              "boundary": "간이 정책 이관·수기 사례·경로 연결 검증. 최신 세법·대출 승인·실제 LLM 정확도 검증 제외."}
    previous = os.environ.get("CORE_STORAGE_URL", "")
    owner = requests.Session()
    def check(name):
        report["checks"].append({"name": name, "status": "passed"}); print("PASS " + name)
    def require(response, status=200):
        assert response.status_code == status, (response.status_code, response.text[:500])
        return response.json()
    def calculation(operation, inputs):
        return requests.post(root + "/internal/v1/calculations/" + operation, headers=headers, json=inputs, timeout=30)
    try:
        require(requests.post(root + "/internal/v1/calculations/simulation", json={"purchase_price": 600000000}), 401)
        for inputs in ({"purchase_price": None}, {"purchase_price": 1.5}, {"purchase_price": 600000000, "owned_homes": 0},
                       {"purchase_price": 600000000, "loan_amount": 600000000},
                       {"purchase_price": 600000000, "loan_amount": 1, "annual_interest_rate": "1e-1000"},
                       {"purchase_price": 1000000000000000, "holding_years": 50, "expected_annual_growth_rate": 50}):
            require(calculation("simulation", inputs), 422)
        check("내부 인증·필수 null·소수 금액·잘못된 조건·초저금리와 복리 오버플로 거부")
        golden = require(calculation("simulation", {"purchase_price": 600000000, "loan_amount": 300000000}))
        assert golden["required_cash"] == 309600000 and golden["loan"]["monthly_payment"] == 1432246
        assert golden["calculator_engine"] == "kotlin-spring" and golden["calculation_version"] == "finance-v1"
        assert require(calculation("calc_gift_tax", {"gift_value": 500000000}))["tax"] == 77600000
        assert require(calculation("calc_inheritance_tax", {"estate_value": 2000000000}))["tax"] == 232800000
        assert require(calculation("calc_annual_holding_tax", {"official_price": 600000000}))["total"] == 787200
        check("수기 정답: 취득비용·필요 현금·월 상환·증여·상속·보유세")
        # 기존 부동소수 수식과 원 단위 차이를 기록한다. 금액은 ±1원, 반올림 비율은 동일해야 한다.
        maximum_difference = 0
        samples = json.loads((ROOT / "tests/fixtures/finance_migration.json").read_text(encoding="utf-8"))["cases"]
        metadata = {"calculator_engine", "calculation_version", "rounding_policy"}
        def compare(before, after, path=""):
            nonlocal maximum_difference
            if isinstance(before, dict):
                assert before.keys() == after.keys(), path
                for key in before:
                    if key not in metadata: compare(before[key], after[key], path + "/" + key)
            elif isinstance(before, list):
                assert len(before) == len(after), path
                for index, (left, right) in enumerate(zip(before, after)): compare(left, right, path + f"/{index}")
            elif type(before) is int and type(after) is int:
                difference = abs(before - after)
                maximum_difference = max(maximum_difference, difference)
                assert difference <= 1, (path, before, after)
            else:
                assert before == after, (path, before, after)
        for sample in samples:
            old = sample["expected"]
            new = require(calculation("simulation", sample["input"]))
            compare(old, new)
            report["differential_cases"] += 1
        report["maximum_money_difference_won"] = maximum_difference
        check(f"기존 수식 {len(samples)}개 조건 전체 결과 대조 (원 단위 최대 차이 {maximum_difference})")
        os.environ["CORE_STORAGE_URL"] = root
        require(owner.post(root + "/api/auth/register", json={"email": f"calculation-{uuid.uuid4().hex}@example.com",
            "password": "Calculator-Check-2026!", "name": "격리 계산 검증"}), 201)
        user = require(owner.get(root + "/api/auth/me"))
        for homes in (1, 2, 3):
            profile = dict(cash_available=400000000, emergency_reserve=50000000, monthly_payment_limit=2000000,
                annual_income=100000000, existing_loan_annual_payment=1200000, loan_ratio=0.5,
                annual_interest_rate=4.25, loan_years=27, owned_homes=homes, adjusted_area=False)
            case = require(owner.post(root + "/api/cases", json={"title": "Kotlin 계산 대조", "buyer_profile": profile}), 201)
            candidate = require(owner.post(root + f"/api/cases/{case['id']}/properties", json={
                "name": "자금 대조", "asking_price": 600000000, "category": "apartment"}), 201)
            payload = {key: value for key, value in profile.items() if key != "emergency_reserve"}
            payload["cash_available"] -= profile["emergency_reserve"]
            direct = require(owner.post(root + "/api/simulation", json={"case_id": case["id"],
                "candidate_id": candidate["id"], "purchase_price": 600000000, **payload}))
            expected = direct["candidate_funding"]
            assert expected["calculator_engine"] == "kotlin-spring" and expected["cash_available"] == 350000000
            chat = simulate_investment({}, user["id"], {"case_id": case["id"], "candidate_id": candidate["id"]})
            assert chat.status == "completed" and chat.data["candidate_funding"] == expected, chat
            scenario = require(owner.post(root + f"/api/cases/{case['id']}/funding-scenarios", json={}))["rows"][0]
            assert scenario["baseline"]["summary"] == scenario["scenario"]["summary"] == expected
            detail = require(owner.get(root + f"/api/cases/{case['id']}"))
            saved = next(item for item in detail["properties"][0]["analyses"] if item["analysis_type"] == "simulation")
            assert saved["summary"] == expected
        check("1·2·3주택: 네이티브 API·실제 챗봇 도구·비교 시나리오·저장 결과 일치와 비상자금 1회 차감")
        args = {"user_id": user["id"], "case_id": case["id"], "property_id": candidate["id"]}
        before = require(requests.post(root + "/internal/v1/store/cases/candidate_inputs", headers=headers, json=args))
        before["asking_price"] -= 1
        require(requests.post(root + "/internal/v1/store/cases/link_candidate_analysis", headers=headers, json=args | {
            "analysis_type": "simulation", "summary": expected, "checklist_status": "done",
            "evidence": "오래된 결과 연결 금지", "expected_inputs": before}), 422)
        require(owner.post(root + "/api/simulation", json={"case_id": case["id"], "candidate_id": 2000000000,
            "purchase_price": 600000000}), 404)
        zero = require(owner.post(root + "/api/simulation", json={"purchase_price": 600000000, "annual_income": 0}))
        assert zero["result"]["finance_check"]["dsr"] is None
        check("계산 중 변경된 후보 결과 연결·없는 후보 거부 및 0원 소득의 DSR 미검증")
        for tool, params in (("gift_tax", {"gift_value": 500000000}), ("inheritance_tax", {"estate_value": 2000000000}),
                             ("capital_gains_tax", {"purchase_price": 800000000, "sale_price": 1100000000, "holding_years": 2}),
                             ("holding_tax", {"official_price": 600000000})):
            output = _run_tool(tool, params)
            assert output and output["outputs"], (tool, output)
        check("법률·세금 챗봇의 4종 실제 계산 도구가 Kotlin 계약 사용 (LLM 라우팅 제외)")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        os.environ["CORE_STORAGE_URL"] = previous
        if owner.cookies.get("auth_token"): owner.delete(root + "/api/auth/me")
        (ROOT / "evaluation-results").mkdir(exist_ok=True)
        (ROOT / "evaluation-results/core-calculations-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    verify(sys.argv[1])
