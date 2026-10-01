"""Python 오케스트레이션에서 Kotlin의 업무 저장 계약을 호출한다."""
from __future__ import annotations

import functools
import inspect
import os
from urllib.parse import urlsplit

import requests
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder


def require_core_configuration() -> tuple[str, str]:
    root = os.getenv("CORE_STORAGE_URL", "").strip().rstrip("/")
    parsed = urlsplit(root)
    key = os.getenv("INTERNAL_SERVICE_SECRET", "")
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
            or parsed.query or parsed.fragment or len(key) < 32):
        raise HTTPException(503, "Kotlin 서비스 주소와 내부 인증 설정이 필요합니다")
    return root, key


def request_core(path: str, inputs: dict) -> requests.Response:
    root, key = require_core_configuration()
    try:
        return requests.post(root + path, json=jsonable_encoder(inputs),
                             headers={"X-Internal-Service-Key": key}, timeout=30)
    except requests.RequestException:
        raise HTTPException(503, "Kotlin 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해주세요") from None


def core_store(domain: str):
    def decorate(contract):
        signature = inspect.signature(contract)
        @functools.wraps(contract)
        def invoke(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            response = request_core(f"/internal/v1/store/{domain}/{contract.__name__}", dict(bound.arguments))
            if response.status_code == 404:
                if domain in ("listings", "observations"):
                    raise HTTPException(404, "매물 또는 수집 기록을 찾을 수 없습니다")
                raise LookupError("record_not_found")
            if response.status_code in (409, 422):
                if domain in ("listings", "observations"):
                    raise HTTPException(response.status_code, response.json().get("detail", "저장 조건을 확인해주세요"))
                raise ValueError(response.json().get("detail", "저장 조건을 확인해주세요"))
            if response.status_code != 200:
                raise HTTPException(503, "저장 요청을 처리하지 못했습니다")
            try:
                return response.json() if response.content else None
            except ValueError:
                raise HTTPException(503, "저장 응답의 형식을 확인하지 못했습니다") from None
        return invoke
    return decorate
