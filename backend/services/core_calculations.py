"""계산 수식은 Kotlin에만 둔다. Python은 입력·결과 계약을 변환한다."""
from __future__ import annotations

import functools
import inspect
from fastapi import HTTPException
from pydantic import ValidationError
from api.core_bridge import request_core


def calculate(operation: str, inputs: dict):
    response = request_core(f"/internal/v1/calculations/{operation}", inputs)
    if response.status_code == 422:
        raise HTTPException(422, "계산 입력의 범위와 조건을 확인해주세요")
    if response.status_code != 200:
        raise HTTPException(503, "계산 요청을 처리하지 못했습니다")
    try:
        value = response.json()
    except ValueError:
        raise HTTPException(503, "계산 결과의 형식을 확인하지 못했습니다") from None
    if value is None:
        raise HTTPException(503, "계산 결과가 비어 있습니다")
    return value


def core_calculation(result_model=None):
    def decorate(contract):
        signature = inspect.signature(contract)
        @functools.wraps(contract)
        def invoke(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            try:
                result = calculate(contract.__name__, dict(bound.arguments))
            except HTTPException as error:
                if error.status_code == 422:
                    raise ValueError(error.detail) from None
                raise
            if result_model is None:
                return result
            try:
                return result_model.model_validate(result)
            except ValidationError:
                raise HTTPException(503, "계산 결과의 형식을 확인하지 못했습니다") from None
        return invoke
    return decorate
