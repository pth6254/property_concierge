"""
test_access_control.py — 이력·작업 소유자 격리 회귀 테스트

id가 순차 정수인 history 레코드를 소유자 검증 없이 조회하면
로그인한 아무나 /api/history/{id} 를 훑어 타인의 리포트를 읽을 수 있다.
같은 문제가 job 폴링 엔드포인트에도 적용된다.

두 경로 모두 "타인 → 404"가 유지되는지 고정한다.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("DISABLE_RATE_LIMIT", "1")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-access-control")


@pytest.fixture()
def client():
    """
    users/history 테이블을 비운 상태로 시작하는 TestClient.

    이전에는 auth_db.DB/history_db.DB(SQLite 파일 경로)를 tmp_path로
    monkeypatch해 테스트마다 완전히 별개의 DB 파일을 썼다. 지금은 모든
    워커가 같은 Postgres 인스턴스를 보므로, 관련 테이블만 비워 격리한다.
    """
    from fastapi.testclient import TestClient

    from db.models import HistoryRecord, User
    from tests.conftest import truncate_tables

    truncate_tables(HistoryRecord, User)

    from api.main import app

    with TestClient(app) as c:
        yield c


def _register(client, email: str) -> None:
    """회원가입 후 쿠키가 client에 저장된다."""
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": "test-password-1234", "name": email.split("@")[0]},
    )
    assert res.status_code == 201, res.text


class TestHistoryOwnerIsolation:
    def test_other_user_cannot_read_report(self, client):
        from api import history_db

        _register(client, "owner@example.com")
        owner_id = client.get("/api/auth/me").json()["id"]

        record_id = history_db.save(
            "서초구 아파트 84㎡",
            {"final_report": "소유자 전용 리포트", "analysis_result": {}},
            user_id=owner_id,
        )

        # 소유자는 열람 가능
        res = client.get(f"/api/history/{record_id}")
        assert res.status_code == 200
        assert res.json()["final_report"] == "소유자 전용 리포트"

        # 다른 사용자로 전환 → 동일 id 조회 시 404 (존재 여부도 노출 금지)
        client.cookies.clear()
        _register(client, "attacker@example.com")

        res = client.get(f"/api/history/{record_id}")
        assert res.status_code == 404, "타인의 이력이 조회됨 — 소유자 검증 누락"

    def test_anonymous_record_not_readable(self, client):
        """비로그인 상태로 저장된 레코드(user_id=NULL)도 임의 조회 불가."""
        from api import history_db

        record_id = history_db.save(
            "비로그인 요청", {"final_report": "익명 리포트"}, user_id=None
        )

        _register(client, "someone@example.com")
        assert client.get(f"/api/history/{record_id}").status_code == 404

    def test_requires_login(self, client):
        assert client.get("/api/history/1").status_code == 401


class TestJobOwnerIsolation:
    def test_other_user_cannot_poll_job(self, client):
        from api import jobs

        _register(client, "jobowner@example.com")
        owner_id = client.get("/api/auth/me").json()["id"]

        job_id = jobs.create(lambda set_step: {"final_report": "ok"}, owner_id=owner_id)

        assert client.get(f"/api/appraisal/jobs/{job_id}").status_code == 200

        client.cookies.clear()
        _register(client, "jobattacker@example.com")
        res = client.get(f"/api/appraisal/jobs/{job_id}")
        assert res.status_code == 404, "타인의 작업이 조회됨 — 소유자 검증 누락"

    def test_anonymous_job_still_pollable(self, client):
        """비로그인 작업은 추측 불가한 job_id 자체가 접근 토큰 — 폴링이 계속 동작해야 한다."""
        from api import jobs

        job_id = jobs.create(lambda set_step: {"final_report": "ok"}, owner_id=None)
        assert client.get(f"/api/appraisal/jobs/{job_id}").status_code == 200
