"""
deps.py — FastAPI 공통 의존성
"""
from __future__ import annotations

from typing import Optional
import os

from fastapi import Cookie, Depends, HTTPException, status

from api import auth_db, auth_utils


def is_operator(user: dict) -> bool:
    # 이메일 재가입으로 권한이 승계되지 않도록 기존 계정의 고유 ID를 지정한다.
    return str(user["id"]) in {value.strip() for value in os.getenv("OPERATOR_USER_IDS", "").split(",") if value.strip()}


def get_current_user(auth_token: Optional[str] = Cookie(default=None)) -> dict:
    if not auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다")
    try:
        payload = auth_utils.decode_jwt_payload(auth_token)
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰")
    user = auth_db.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="사용자를 찾을 수 없음")
    # 비밀번호 변경 이전에 발급된 토큰은 거부한다 (계정 탈취 후 비밀번호를
    # 바꿔도 공격자 세션이 살아있는 문제 방지).
    if not auth_utils.is_session_valid(payload, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비밀번호가 변경되어 다시 로그인해야 합니다",
        )
    return user


def get_optional_user(auth_token: Optional[str] = Cookie(default=None)) -> Optional[dict]:
    if not auth_token:
        return None
    try:
        payload = auth_utils.decode_jwt_payload(auth_token)
        user = auth_db.get_by_id(int(payload["sub"]))
    except Exception:
        return None
    if user and not auth_utils.is_session_valid(payload, user):
        return None
    return user


def require_operator(user: dict = Depends(get_current_user)) -> dict:
    if not is_operator(user):
        raise HTTPException(status_code=403, detail="운영자 권한이 필요합니다")
    return user
