"""
test_cookie_config.py — 세션 쿠키 속성 회귀 테스트

배포 형태(같은 출처 / 크로스 사이트)에 따라 쿠키 속성이 달라져야 한다.
잘못 나가면 증상이 "로그인이 그냥 안 됨"이라 원인을 찾기 어렵고,
브라우저가 조용히 무시하는 조합(SameSite=None + Secure 없음)도 있어
설정값 → 실제 Set-Cookie 헤더 매핑을 테스트로 고정한다.

auth.py 는 모듈 임포트 시점에 환경변수를 읽으므로, 각 테스트는
환경변수를 바꾼 뒤 모듈을 리로드해서 확인한다.
"""
from __future__ import annotations

import importlib
import os

import pytest

os.environ.setdefault("DISABLE_RATE_LIMIT", "1")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-cookie-config")


def _reload_auth(monkeypatch, **env):
    """환경변수를 적용한 상태로 auth 라우터 모듈을 다시 읽는다."""
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    from api.routes import auth as auth_module
    return importlib.reload(auth_module)


@pytest.fixture(autouse=True)
def _restore_auth_module():
    """다른 테스트가 오염된 모듈을 쓰지 않도록 원래 설정으로 되돌린다."""
    yield
    from api.routes import auth as auth_module
    importlib.reload(auth_module)


class TestCookieAttributes:
    def test_default_is_lax_and_insecure_in_dev(self, monkeypatch):
        """개발 기본값 — 같은 출처 배포 전제, HTTP 로도 동작해야 한다."""
        auth = _reload_auth(monkeypatch, COOKIE_SAMESITE=None, APP_ENV="development")
        assert auth._COOKIE_SAMESITE == "lax"
        assert auth._COOKIE_SECURE is False

    def test_production_forces_secure(self, monkeypatch):
        auth = _reload_auth(monkeypatch, COOKIE_SAMESITE="lax", APP_ENV="production")
        assert auth._COOKIE_SECURE is True

    def test_samesite_none_forces_secure_even_in_dev(self, monkeypatch):
        """
        SameSite=None 은 Secure 없이는 브라우저가 조용히 거부한다.
        APP_ENV 와 무관하게 secure 가 켜져야 설정 실수로 로그인이 통째로 깨지지 않는다.
        """
        auth = _reload_auth(monkeypatch, COOKIE_SAMESITE="none", APP_ENV="development")
        assert auth._COOKIE_SAMESITE == "none"
        assert auth._COOKIE_SECURE is True

    def test_invalid_value_fails_fast(self, monkeypatch):
        """오타는 기동 시점에 잡는다 — 런타임에 조용히 잘못 동작하면 원인 추적이 어렵다."""
        with pytest.raises(RuntimeError, match="COOKIE_SAMESITE"):
            _reload_auth(monkeypatch, COOKIE_SAMESITE="lax; strict")

    def test_value_is_normalized(self, monkeypatch):
        auth = _reload_auth(monkeypatch, COOKIE_SAMESITE="  NONE  ")
        assert auth._COOKIE_SAMESITE == "none"


class TestSetCookieHeader:
    """설정값이 실제 응답 헤더까지 반영되는지 확인한다."""

    def _client(self):
        from fastapi.testclient import TestClient

        from db.models import HistoryRecord, User
        from tests.conftest import truncate_tables

        truncate_tables(HistoryRecord, User)

        from api.main import app
        return TestClient(app)

    def _register_and_get_cookie_header(self, client, email: str) -> str:
        res = client.post(
            "/api/auth/register",
            json={"email": email, "password": "cookie-test-1234", "name": "쿠키"},
        )
        assert res.status_code == 201, res.text
        return res.headers.get("set-cookie", "")

    def test_lax_dev_header(self, monkeypatch):
        _reload_auth(monkeypatch, COOKIE_SAMESITE="lax", APP_ENV="development")
        header = self._register_and_get_cookie_header(self._client(), "cookie-lax@example.com")

        assert "samesite=lax" in header.lower()
        assert "httponly" in header.lower()
        assert "secure" not in header.lower()

    def test_none_header_includes_secure(self, monkeypatch):
        _reload_auth(monkeypatch, COOKIE_SAMESITE="none", APP_ENV="development")
        header = self._register_and_get_cookie_header(self._client(), "cookie-none@example.com")

        assert "samesite=none" in header.lower()
        assert "secure" in header.lower(), "SameSite=None 인데 Secure 가 없으면 브라우저가 쿠키를 버린다"

    def test_logout_clears_with_matching_attributes(self, monkeypatch):
        """
        삭제 쿠키도 설정과 같은 속성이어야 브라우저가 같은 쿠키로 인식해 지운다.
        """
        _reload_auth(monkeypatch, COOKIE_SAMESITE="none", APP_ENV="development")
        client = self._client()
        self._register_and_get_cookie_header(client, "cookie-logout@example.com")

        res = client.post("/api/auth/logout")
        header = res.headers.get("set-cookie", "").lower()

        assert "samesite=none" in header
        assert "secure" in header
