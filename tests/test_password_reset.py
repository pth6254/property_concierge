"""
test_password_reset.py — 비밀번호 재설정 + 세션 무효화 회귀 테스트

고정하려는 동작:
  1. 계정 열거 방지 — 가입 여부·소셜 계정 여부와 무관하게 응답이 동일해야 한다.
  2. 토큰 1회성 — 한 번 쓴 토큰으로 다시 바꿀 수 없어야 한다.
  3. 만료·위조 토큰 거부.
  4. 비밀번호 변경 시 기존 JWT 세션이 전부 끊겨야 한다 (계정 탈취 대응).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("DISABLE_RATE_LIMIT", "1")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-password-reset")

EMAIL    = "reset-target@example.com"
PASSWORD = "original-pass-1234"
NEW_PASS = "brand-new-pass-5678"


@pytest.fixture()
def client():
    """users/history 를 비우고 시작하는 TestClient."""
    from tests.service_client import ServiceTestClient as TestClient

    from db.models import HistoryRecord, User
    from tests.conftest import truncate_tables

    truncate_tables(HistoryRecord, User)

    from api.main import app

    with TestClient(app) as c:
        yield c


def _register(client, email: str = EMAIL, password: str = PASSWORD) -> None:
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "재설정테스트"},
    )
    assert res.status_code == 201, res.text


def _issue_reset_token(client, email: str = EMAIL) -> str:
    """재설정을 요청하고 Redis 에 저장된 토큰을 직접 꺼낸다 (메일 대신)."""
    from db.redis_client import get_redis

    res = client.post("/api/auth/password-reset/request", json={"email": email})
    assert res.status_code == 200

    keys = list(get_redis().scan_iter(match="pwreset:*"))
    assert keys, "재설정 토큰이 Redis 에 생성되지 않았다"
    return keys[-1].split("pwreset:", 1)[1]


@pytest.fixture(autouse=True)
def _clear_reset_tokens():
    """테스트 간 토큰이 새지 않도록 정리."""
    from db.redis_client import get_redis

    r = get_redis()
    for k in list(r.scan_iter(match="pwreset:*")):
        r.delete(k)
    yield
    for k in list(r.scan_iter(match="pwreset:*")):
        r.delete(k)


class TestAccountEnumeration:
    """계정 존재 여부가 응답으로 새어나가면 안 된다."""

    def test_same_response_for_unknown_email(self, client):
        _register(client)
        known   = client.post("/api/auth/password-reset/request", json={"email": EMAIL})
        unknown = client.post("/api/auth/password-reset/request",
                              json={"email": "nobody-here@example.com"})

        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json(), "가입 여부에 따라 응답이 달라 계정 열거가 가능하다"

    def test_no_token_issued_for_unknown_email(self, client):
        """응답은 같아도 실제 토큰은 발급되지 않아야 한다."""
        from db.redis_client import get_redis

        client.post("/api/auth/password-reset/request",
                    json={"email": "nobody-here@example.com"})
        assert not list(get_redis().scan_iter(match="pwreset:*"))

    def test_social_account_gets_same_response_but_no_token(self, client):
        """Google 계정은 비밀번호가 없다 — 응답은 동일하되 토큰은 만들지 않는다."""
        from db.redis_client import get_redis

        from tests import core_accounts as auth_db

        auth_db.get_or_create_oauth_user(
            email="social@example.com", name="소셜", avatar_url="",
            provider="google", provider_id="g-1",
        )
        res = client.post("/api/auth/password-reset/request",
                          json={"email": "social@example.com"})

        assert res.status_code == 200
        assert not list(get_redis().scan_iter(match="pwreset:*"))


class TestResetFlow:
    def test_reset_changes_password(self, client):
        _register(client)
        token = _issue_reset_token(client)

        res = client.post("/api/auth/password-reset/confirm",
                          json={"token": token, "new_password": NEW_PASS})
        assert res.status_code == 200, res.text

        client.cookies.clear()
        assert client.post("/api/auth/login",
                           json={"email": EMAIL, "password": NEW_PASS}).status_code == 200
        client.cookies.clear()
        assert client.post("/api/auth/login",
                           json={"email": EMAIL, "password": PASSWORD}).status_code == 401

    def test_token_is_single_use(self, client):
        _register(client)
        token = _issue_reset_token(client)

        first = client.post("/api/auth/password-reset/confirm",
                            json={"token": token, "new_password": NEW_PASS})
        assert first.status_code == 200

        second = client.post("/api/auth/password-reset/confirm",
                             json={"token": token, "new_password": "yet-another-pass-9"})
        assert second.status_code == 400, "이미 사용한 토큰이 재사용됐다"

    def test_unknown_token_rejected(self, client):
        res = client.post("/api/auth/password-reset/confirm",
                          json={"token": "not-a-real-token", "new_password": NEW_PASS})
        assert res.status_code == 400

    def test_expired_token_rejected(self, client):
        """TTL 이 지난 토큰은 거부된다 (Redis 키를 직접 지워 만료를 재현)."""
        from db.redis_client import get_redis

        _register(client)
        token = _issue_reset_token(client)
        get_redis().delete(f"pwreset:{token}")

        res = client.post("/api/auth/password-reset/confirm",
                          json={"token": token, "new_password": NEW_PASS})
        assert res.status_code == 400

    def test_short_password_rejected(self, client):
        _register(client)
        token = _issue_reset_token(client)

        res = client.post("/api/auth/password-reset/confirm",
                          json={"token": token, "new_password": "short"})
        assert res.status_code == 422


class TestSessionInvalidation:
    """비밀번호가 바뀌면 그 이전에 발급된 세션은 전부 끊겨야 한다."""

    def test_existing_session_dies_after_reset(self, client):
        _register(client)                      # 가입 시 받은 쿠키가 client 에 남아 있다
        assert client.get("/api/auth/me").status_code == 200

        token = _issue_reset_token(client)
        client.post("/api/auth/password-reset/confirm",
                    json={"token": token, "new_password": NEW_PASS})

        # confirm 응답이 쿠키를 지우므로, 탈취당한 세션 상황을 재현하기 위해
        # 이전 쿠키를 그대로 되살려 접근을 시도한다.
        from tests import core_accounts as auth_db, legacy_auth as auth_utils

        user = auth_db.get_by_email(EMAIL)
        stale = auth_utils.create_jwt(user["id"], password_changed_at=None)
        client.cookies.set("auth_token", stale)

        res = client.get("/api/auth/me")
        assert res.status_code == 401, "비밀번호 변경 전에 발급된 토큰이 아직 살아있다"

    def test_new_session_works_after_reset(self, client):
        _register(client)
        token = _issue_reset_token(client)
        client.post("/api/auth/password-reset/confirm",
                    json={"token": token, "new_password": NEW_PASS})

        client.cookies.clear()
        assert client.post("/api/auth/login",
                           json={"email": EMAIL, "password": NEW_PASS}).status_code == 200
        assert client.get("/api/auth/me").status_code == 200

    def test_token_without_pwd_at_still_valid_when_never_changed(self, client):
        """
        컬럼 도입 이전에 발급된 토큰 호환성 —
        비밀번호를 한 번도 바꾼 적 없는 계정은 pwd_at 없는 토큰도 통과해야 한다.
        """
        from tests import core_accounts as auth_db, legacy_auth as auth_utils

        _register(client)
        user = auth_db.get_by_email(EMAIL)
        assert user["password_changed_at"] is None

        legacy = auth_utils.create_jwt(user["id"])   # pwd_at 클레임 없음
        client.cookies.set("auth_token", legacy)
        assert client.get("/api/auth/me").status_code == 200
