"""
이전 JWT·비밀번호의 Spring 호환 검증 자료. 실행 코드에서 임포트하지 않는다.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

SECRET_KEY = os.environ["JWT_SECRET_KEY"]
ALGORITHM = "HS256"
EXPIRE_DAYS = 7


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_jwt(user_id: int, password_changed_at: str | None = None) -> str:
    """
    세션 토큰 발급.

    password_changed_at 을 pwd_at 클레임으로 함께 넣는다. JWT 는 stateless 라
    서버가 이미 발급한 토큰을 폐기할 수 없으므로, 검증 시점에 DB 값과 대조해
    "비밀번호가 바뀐 뒤 발급된 토큰인가"를 판단한다 (deps.py 참고).
    """
    exp = datetime.now(timezone.utc) + timedelta(days=EXPIRE_DAYS)
    payload: dict = {"sub": str(user_id), "exp": exp}
    if password_changed_at:
        payload["pwd_at"] = password_changed_at
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_jwt(token: str) -> int:
    """토큰 → user_id. 서명·만료가 유효하지 않으면 예외."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return int(payload["sub"])


def decode_jwt_payload(token: str) -> dict:
    """토큰 → 페이로드 전체 (pwd_at 대조가 필요한 경로에서 사용)."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def is_session_valid(payload: dict, user: dict) -> bool:
    """
    비밀번호 변경으로 무효화된 세션인지 판정한다.

    - 사용자가 비밀번호를 한 번도 바꾸지 않았으면(NULL) 통과 —
      컬럼 도입 이전에 발급된 pwd_at 없는 토큰도 계속 쓸 수 있어야 한다.
    - 바꾼 적이 있으면 토큰의 pwd_at 이 현재 값과 정확히 같아야 한다.
      변경 이전에 발급된 토큰은 pwd_at 이 없거나 옛 값이라 여기서 걸러진다.
    """
    changed_at = user.get("password_changed_at")
    if not changed_at:
        return True
    return payload.get("pwd_at") == changed_at
