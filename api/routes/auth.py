"""
auth.py — 인증 라우터

POST   /api/auth/register        : 이메일/비밀번호 회원가입
POST   /api/auth/login           : 이메일/비밀번호 로그인 (계정별 잠금: 10분 내 5회 실패 시 차단)
POST   /api/auth/password-reset/request : 재설정 링크 발송 (응답은 계정 존재 여부와 무관하게 동일)
POST   /api/auth/password-reset/confirm : 토큰 검증 후 비밀번호 변경 (기존 세션 전부 무효화)
GET    /api/auth/google          : Google OAuth 시작
GET    /api/auth/google/callback : Google OAuth 콜백
GET    /api/auth/me              : 현재 사용자 정보
DELETE /api/auth/me              : 회원 탈퇴 (이력·활동 포함 전체 삭제)
POST   /api/auth/logout          : 로그아웃
"""
from __future__ import annotations

import logging
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api import activity_db, auth_db, auth_utils, email_service, history_db
from api.deps import get_current_user, is_operator
from api.rate_limit import limiter
from db.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:3000/api/auth/google/callback")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "http://localhost:3000")

_COOKIE      = "auth_token"
_COOKIE_AGE  = 7 * 24 * 3600
_IS_PROD     = os.getenv("APP_ENV", "development") == "production"

# ── 세션 쿠키의 SameSite / Secure ────────────────────────
#
# 기본값 lax 는 "프론트와 백엔드가 브라우저에게 같은 출처로 보이는" 배포를 전제한다.
# 지금 구조가 그렇다 — frontend/next.config.ts 의 rewrites 가 /api/* 를 백엔드로
# 중계하므로 브라우저 입장에서는 동일 출처다.
#
# 프론트와 API 를 서로 다른 사이트(예: app.vercel.app ↔ api.fly.dev)에 배포하면
# 브라우저가 크로스 사이트로 판단해 lax 쿠키를 아예 붙이지 않는다(= 항상 401).
# 그 경우에만 COOKIE_SAMESITE=none 으로 바꾼다.
#
# SameSite=None 은 브라우저 규격상 Secure 가 없으면 조용히 거부되므로,
# APP_ENV 와 무관하게 secure 를 강제한다 — 설정 실수로 로그인이 통째로
# 깨지는 것을 막기 위해서다(HTTPS 가 아니면 none 은 애초에 쓸 수 없다).
_COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").strip().lower()
if _COOKIE_SAMESITE not in ("lax", "none", "strict"):
    raise RuntimeError(
        f"COOKIE_SAMESITE 값이 올바르지 않습니다: {_COOKIE_SAMESITE!r} "
        "(lax | none | strict 중 하나여야 합니다)"
    )
_COOKIE_SECURE = _IS_PROD or _COOKIE_SAMESITE == "none"

# 로그인 브루트포스 방지 — 계정별 10분 내 5회 실패 시 잠금.
# 이전에는 실패 타임스탬프 리스트를 프로세스 메모리 dict에 쌓는 슬라이딩 윈도우였다
# (워커마다 따로 놀아 실질 한도가 워커 수만큼 늘어나는 문제가 있었다). Redis
# INCR+EXPIRE 기반 고정 윈도우로 바꿔 워커 간 카운터를 공유한다 — 정확도는
# 슬라이딩보다 약간 떨어지지만(윈도우 경계에서 최대 2배까지 허용 가능) 계정 잠금
# 목적에는 충분하고 구현이 훨씬 단순하다.
_LOCK_WINDOW_SEC = 600
_LOCK_MAX_FAILS  = 5


def _fail_key(email: str) -> str:
    return f"loginfail:{email}"


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE, value=token,
        httponly=True, secure=_COOKIE_SECURE, samesite=_COOKIE_SAMESITE,
        max_age=_COOKIE_AGE, path="/",
    )


def _clear_cookie(response: Response) -> None:
    """
    세션 쿠키 삭제.

    삭제도 설정과 **같은 속성**(path·samesite·secure)으로 보내야 한다 —
    속성이 다르면 브라우저가 다른 쿠키로 보고 기존 것을 남겨둔다.
    """
    response.delete_cookie(
        key=_COOKIE, path="/",
        samesite=_COOKIE_SAMESITE, secure=_COOKIE_SECURE, httponly=True,
    )


def _check_login_lock(email: str) -> None:
    count = get_redis().get(_fail_key(email))
    if count is not None and int(count) >= _LOCK_MAX_FAILS:
        raise HTTPException(
            status_code=429,
            detail="로그인 시도가 너무 많습니다. 10분 후 다시 시도해주세요.",
        )


def _record_login_fail(email: str) -> None:
    r   = get_redis()
    key = _fail_key(email)
    count = r.incr(key)
    if count == 1:
        r.expire(key, _LOCK_WINDOW_SEC)


def _clear_login_fails(email: str) -> None:
    get_redis().delete(_fail_key(email))


# ── 비밀번호 재설정 ──────────────────────────────────────
#
# 토큰은 DB가 아니라 Redis에 둔다 — TTL 이 곧 만료 정책이라 별도 테이블·정리
# 배치가 필요 없고, 로그인 잠금 카운터와 동일한 저장소를 쓰므로 멀티 워커에서도
# 그대로 공유된다.
_RESET_TTL_SEC     = 30 * 60   # 30분
_RESET_TOKEN_BYTES = 32        # secrets.token_urlsafe 입력 바이트 수


def _reset_key(token: str) -> str:
    return f"pwreset:{token}"


# ── 이메일/비밀번호 ──────────────────────────────────────

class RegisterBody(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/auth/register", status_code=201)
@limiter.limit("5/minute")
def register(request: Request, body: RegisterBody, response: Response):
    if auth_db.get_by_email(body.email):
        raise HTTPException(status_code=409, detail="이미 사용 중인 이메일입니다")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="비밀번호는 8자 이상이어야 합니다")
    hashed = auth_utils.hash_password(body.password)
    user   = auth_db.create_local_user(body.email, hashed, body.name)
    _set_cookie(response, auth_utils.create_jwt(user["id"], user.get("password_changed_at")))
    return {"id": user["id"], "email": user["email"], "name": user["name"], "is_operator": is_operator(user)}


@router.post("/auth/login")
@limiter.limit("10/minute")
def login(request: Request, body: LoginBody, response: Response):
    _check_login_lock(body.email)
    user = auth_db.get_by_email(body.email)
    if not user or not user.get("password_hash"):
        _record_login_fail(body.email)
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")
    if not auth_utils.verify_password(body.password, user["password_hash"]):
        _record_login_fail(body.email)
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")
    _clear_login_fails(body.email)
    _set_cookie(response, auth_utils.create_jwt(user["id"], user.get("password_changed_at")))
    return {"id": user["id"], "email": user["email"], "name": user["name"], "is_operator": is_operator(user)}


# ── 비밀번호 재설정 ──────────────────────────────────────

class PasswordResetRequestBody(BaseModel):
    email: str


class PasswordResetConfirmBody(BaseModel):
    token: str
    new_password: str


# 계정 존재 여부를 노출하지 않기 위해 어떤 경우에도 동일하게 반환하는 응답.
_RESET_GENERIC_RESPONSE = {
    "ok": True,
    "message": "입력하신 이메일로 재설정 링크를 보냈습니다. 메일함을 확인해주세요.",
}


@router.post("/auth/password-reset/request")
@limiter.limit("3/hour")
def password_reset_request(request: Request, body: PasswordResetRequestBody):
    """
    재설정 링크 발송.

    응답은 **항상 동일하다** — "가입되지 않은 이메일입니다" 같은 구분을 주면
    공격자가 어떤 이메일이 가입돼 있는지 훑을 수 있다(계정 열거).
    다음 경우 모두 겉으로는 성공처럼 보이되 실제로는 메일을 보내지 않는다:
      - 가입되지 않은 이메일
      - Google 계정(provider != "local") — 비밀번호 자체가 없다
      - 메일 발송 실패
    """
    email = body.email.strip().lower()
    user  = auth_db.get_by_email(email)

    if user and user.get("provider") == "local" and user.get("password_hash"):
        token = secrets.token_urlsafe(_RESET_TOKEN_BYTES)
        get_redis().set(_reset_key(token), str(user["id"]), ex=_RESET_TTL_SEC)
        link = f"{FRONTEND_URL}/reset-password?token={token}"
        email_service.send_password_reset(email, link, _RESET_TTL_SEC // 60)
    else:
        logger.info("[password-reset] 발송 생략 (미가입 또는 소셜 계정) — %s", email)

    return _RESET_GENERIC_RESPONSE


@router.post("/auth/password-reset/confirm")
@limiter.limit("10/hour")
def password_reset_confirm(request: Request, body: PasswordResetConfirmBody, response: Response):
    """
    토큰 검증 후 비밀번호 변경.

    토큰은 1회성이다 — 성공 시 즉시 삭제해 재사용을 막는다.
    비밀번호가 바뀌면 password_changed_at 이 갱신되어 **기존 세션이 전부 무효화**된다
    (auth_utils.is_session_valid). 재설정 직후 쿠키도 지워 로그인 화면으로 보낸다.
    """
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="비밀번호는 8자 이상이어야 합니다")

    r       = get_redis()
    key     = _reset_key(body.token)
    user_id = r.get(key)
    if user_id is None:
        raise HTTPException(
            status_code=400,
            detail="링크가 만료되었거나 이미 사용되었습니다. 재설정을 다시 요청해주세요.",
        )

    updated = auth_db.update_password(int(user_id), auth_utils.hash_password(body.new_password))
    if updated is None:
        r.delete(key)
        raise HTTPException(status_code=400, detail="사용자를 찾을 수 없습니다")

    r.delete(key)                       # 1회성 — 재사용 차단
    _clear_login_fails(updated["email"])  # 잠긴 상태였다면 함께 해제
    _clear_cookie(response)
    logger.info("[password-reset] 완료 — user_id=%s (기존 세션 전부 무효화)", updated["id"])

    return {"ok": True, "message": "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해주세요."}


# ── Google OAuth ─────────────────────────────────────────

@router.get("/auth/google")
def google_login():
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth가 설정되지 않았습니다")
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "offline",
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@router.get("/auth/google/callback")
async def google_callback(code: str, response: Response):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth가 설정되지 않았습니다")
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  GOOGLE_REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
        )
        token_res.raise_for_status()
        access_token = token_res.json()["access_token"]

        user_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_res.raise_for_status()
        info = user_res.json()

    user = auth_db.get_or_create_oauth_user(
        email=info["email"], name=info.get("name", ""),
        avatar_url=info.get("picture", ""), provider="google", provider_id=info["id"],
    )
    redirect = RedirectResponse(url=FRONTEND_URL, status_code=302)
    _set_cookie(redirect, auth_utils.create_jwt(user["id"], user.get("password_changed_at")))
    return redirect


# ── 공통 ─────────────────────────────────────────────────

@router.get("/auth/me")
def me(user: dict = Depends(get_current_user)):
    return {
        "id":         user["id"],
        "email":      user["email"],
        "name":       user["name"],
        "avatar_url": user.get("avatar_url", ""),
        "provider":   user.get("provider", "local"),
        "is_operator": is_operator(user),
    }


@router.delete("/auth/me")
def withdraw(response: Response, user: dict = Depends(get_current_user)):
    """회원 탈퇴 — 시세추정 이력·활동 기록·계정을 즉시 삭제한다 (복구 불가)"""
    from backend.services.chat_conversations import delete_user_conversations
    delete_user_conversations(user["id"])
    history_db.delete_all(user_id=user["id"])
    activity_db.delete_all(user_id=user["id"])
    auth_db.delete_user(user["id"])
    _clear_cookie(response)
    return {"ok": True}


@router.post("/auth/logout")
def logout(response: Response):
    _clear_cookie(response)
    return {"ok": True}
