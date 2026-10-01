"""화면과 대화가 같은 Kotlin 계산·소유자 확인·결과 저장을 사용한다."""
from fastapi import HTTPException
from pydantic import ValidationError
from api.core_bridge import request_core
from schemas.funding_request import SimulationRequest
from schemas.simulation import SimulationResult


def execute_simulation(request: SimulationRequest, user: dict | None):
    response = request_core("/internal/v1/simulation", {"request": request.model_dump(mode="json"),
        "user_id": user["id"] if user else None})
    if response.status_code in (404, 422):
        raise HTTPException(response.status_code, "계산 조건 또는 검토 후보를 확인해주세요")
    if response.status_code != 200:
        raise HTTPException(503, "자금 분석을 완료하지 못했습니다")
    try:
        result = response.json()
    except ValueError:
        raise HTTPException(503, "자금 분석 결과 형식이 올바르지 않습니다") from None
    if not isinstance(result, dict) or result.get("error") or not isinstance(result.get("result"), dict):
        raise HTTPException(503, "자금 분석 결과를 확인하지 못했습니다")
    try:
        calculated = SimulationResult.model_validate(result['result'])
    except ValidationError:
        raise HTTPException(503, "자금 분석 결과 형식이 올바르지 않습니다") from None
    inputs = request.to_simulation_input()
    if (calculated.calculator_engine != 'kotlin-spring' or calculated.calculation_version != 'finance-v1'
            or calculated.purchase_price != inputs.purchase_price or calculated.loan_amount != inputs.loan_amount
            or calculated.owned_homes != inputs.owned_homes):
        raise HTTPException(503, "자금 분석 결과와 입력 조건이 일치하지 않습니다")
    return result
