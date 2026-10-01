"""격리 DB에서 Kotlin 저장·권한 처리와 Python 입력 검증의 연결을 대조한다."""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    database = make_url(os.environ["TEST_DATABASE_URL"])
    if database.database != "real_estate_test":
        raise SystemExit("격리 테스트 DB가 필요합니다")
    engine = create_engine(database)
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO legal_regions(code,parent_code,sido_code,sigungu_code,eup_myeon_dong_code,ri_code,
            name,full_name,level,depth,lawd_code,resident_code,cadastral_code,sort_order,remarks,is_active,synced_at)
            VALUES ('1168010100','1168000000','11','680','101','00','역삼동','서울특별시 강남구 역삼동','eup_myeon_dong',3,
              '11680','','',1,'',true,0) ON CONFLICT(code) DO NOTHING"""))
    root, python = sys.argv[1:3]
    owner, other = requests.Session(), requests.Session()
    private_headers = {"X-Internal-Service-Key": os.environ["INTERNAL_SERVICE_SECRET"]}
    checks = []
    report = {"status": "running", "checks": checks,
              "boundaries": ["실제 PostgreSQL real_estate_test·Redis 15", "Kotlin 인증·매물 조회·저장", "Python CSV 검증", "실제 모델 정확도 제외"]}
    def check(name):
        checks.append(name)
        print("PASS", name, flush=True)
    def require(response, status=200):
        assert response.status_code == status, (response.status_code, response.text[:500])
        return response.json()
    try:
        credentials = {"email": f"core-{uuid.uuid4().hex}@example.com", "password": "spring-check-12345", "name": "Spring 검증"}
        user = require(owner.post(root + "/api/auth/register", json=credentials), 201)
        require(other.post(root + "/api/auth/register", json={**credentials, "email": "other-" + credentials["email"]}), 201)
        assert require(owner.get(root + "/api/auth/me"))["id"] == user["id"]
        require(owner.get(python + "/api/activity", headers=private_headers),404)
        require(owner.get(python + "/internal/v1/data/market/regions", headers=private_headers))
        check("Kotlin 가입·인증과 Python 일반 API 제거")
        require(owner.get(python + "/api/activity"), 401)
        check("유효한 사용자 쿠키가 있어도 내부 인증 없는 Python 직접 요청 차단")
        # Python 발급 토큰도 Kotlin에서 검증하며 기존 bcrypt 계정을 재해시 없이 유지한다.
        from tests import legacy_auth as auth_utils
        with engine.begin() as connection:
            connection.execute(text("UPDATE users SET password_hash=:hash WHERE id=:id"),
                {"hash": auth_utils.hash_password(credentials["password"]), "id": user["id"]})
        require(owner.post(root + "/api/auth/login", json={k: credentials[k] for k in ("email", "password")}))
        owner.cookies.clear()
        owner.cookies.set("auth_token", auth_utils.create_jwt(user["id"]))
        assert require(owner.get(root + "/api/auth/me"))["id"] == user["id"]
        check("기존 Python 로그인 토큰·bcrypt와 Kotlin 세션의 양방향 호환")
        row = {"external_id": "core-check", "name": "검증 단지", "alias": '첫 임장, "출퇴근"', "property_type": "apartment",
            "transaction_type": "purchase", "address": "서울특별시 강남구 역삼동 123", "legal_region_code": "1168010100",
            "area_sqm": "84", "asking_price": "700000000", "confirmed_at": (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(), "status": "active",
            "source_url": "https://fin.land.naver.com/articles/123456789"}
        def upload(rows, commit=True):
            data = io.StringIO(); writer = csv.DictWriter(data, fieldnames=list(row))
            writer.writeheader(); writer.writerows(rows)
            return owner.post(root + "/api/listings/import", json={"source_name": "Spring 검증 출처", "csv_text": data.getvalue(), "commit": commit})
        assert require(upload([row], False))["valid"]
        assert require(owner.get(root + "/api/listings"))["total"] == 0
        assert require(upload([row]))["created"] == 1
        assert require(upload([row]))["unchanged"] == 1
        listing = require(owner.get(root + "/api/listings"))["items"][0]
        assert listing["alias"] == row["alias"] and listing["asking_price"] == 700000000
        require(owner.get(python + "/api/listings", headers=private_headers), 404)
        stored = require(requests.post(root + "/internal/v1/store/listings/get_listing", headers=private_headers,
            json={"user_id": user["id"], "listing_id": listing["id"]}))
        assert stored == listing
        assert require(owner.get(root + "/api/listings?fresh_only=true"))["total"] == 1
        check("미리보기·Kotlin 저장·별칭·동일 업로드·중복 Python 경로 제거")
        id = listing["id"]
        require(other.get(root + f"/api/listings/{id}"), 404)
        require(other.get(root + f"/api/listings/{id}/history"), 404)
        assert require(other.get(root + "/api/listings"))["total"] == 0
        check("다른 사용자 매물·변경 이력 404 및 목록 격리")
        assert not require(upload([row, row | {"external_id": "bad", "asking_price": "7억"}]))["valid"]
        assert not require(upload([row | {"external_id": "overflow", "asking_price": "18446744073709551617"}]))["valid"]
        require(upload([row | {"external_id": "new"}, row | {"asking_price": "750000000"}]), 409)
        assert require(owner.get(root + "/api/listings"))["total"] == 1
        assert len(require(owner.get(root + f"/api/listings/{id}/history"))["items"]) == 1
        check("잘못된 행·동시각 상충 시 전체 롤백")
        updated = row | {"asking_price": "750000000", "confirmed_at": datetime.now(timezone.utc).isoformat()}
        assert require(upload([updated]))["updated"] == 1
        assert require(upload([row]))["skipped_older"] == 1
        assert [r["asking_price"] for r in require(owner.get(root + f"/api/listings/{id}/history"))["items"]] == [750000000, 700000000]
        check("가격 변경 이력·오래된 자료로 덮어쓰기 방지")
        case = require(owner.post(root + "/api/cases", json={"title": "Spring 연결 검증"}), 201)
        require(owner.patch(root + f"/api/cases/{case['id']}", json={"budget_min": 500000000, "budget_max": 900000000}))
        require(owner.patch(root + f"/api/cases/{case['id']}", json={"budget_max": 400000000}), 422)
        assert require(owner.get(root + f"/api/cases/{case['id']}"))["budget_max"] == 900000000
        check("예산 부분 수정의 전체 조건 검증과 실패 시 기존 값 보존")
        candidate = require(owner.post(root + f"/api/listings/{id}/candidate", json={"case_id": case["id"]}), 201)
        assert candidate["asking_price"] == 750000000 and candidate["alias"] == row["alias"]
        assert require(owner.get(root + f"/api/cases/{case['id']}/summary"))["case"]["properties"][0]["id"] == candidate["id"]
        check("Kotlin 케이스 저장·별칭·Python 스냅샷 분석 연결")
        case_id, candidate_id = case["id"], candidate["id"]
        require(other.get(root + f"/api/cases/{case_id}"), 404)
        require(other.patch(root + f"/api/cases/{case_id}", json={"notes": "변경 시도"}), 404)
        require(other.get(root + f"/api/cases/{case_id}/execution"), 404)
        require(owner.post(root + f"/api/cases/{case_id}/decision", json={"property_id": candidate_id, "reason": "   "}), 422)
        check("케이스 조회·변경·실행계획 소유자 격리와 빈 선택 근거 차단")
        consistent_case = require(owner.post(root + "/api/cases", json={"title": "동시 조회 검증", "budget_max": 900000000}), 201)
        consistent_property = require(owner.post(root + f"/api/cases/{consistent_case['id']}/properties", json={
            "name": "동시 조회 검증 후보", "asking_price": 900000000}), 201)
        import threading
        stop = threading.Event()
        errors = []
        def edit_together():
            try:
                turn = 0
                while not stop.is_set():
                    amount = 900000000 if turn % 2 else 800000000
                    with engine.begin() as connection:
                        connection.execute(text("UPDATE purchase_cases SET budget_max=:amount WHERE id=:id"),
                            {"amount": amount, "id": consistent_case["id"]})
                        connection.execute(text("UPDATE case_properties SET asking_price=:amount WHERE id=:id"),
                            {"amount": amount, "id": consistent_property["id"]})
                    turn += 1
                    stop.wait(.003)
            except Exception as error:
                errors.append(type(error).__name__)
        writer = threading.Thread(target=edit_together)
        writer.start()
        try:
            for _ in range(15):
                snapshot = require(owner.get(root + f"/api/cases/{consistent_case['id']}"))
                assert snapshot["budget_max"] == snapshot["properties"][0]["asking_price"], "다른 시점의 예산·후보 혼합"
            assert not errors, errors
        finally:
            stop.set(); writer.join(timeout=5)
        check("동시 변경 중 케이스·후보 읽기 스냅샷 일관성")
        def link_appraisal():
            # AVM 추정 정확도와 저장 계약 검증을 분리한다. 고정 결과임을 평가 산출물에 표시한다.
            result = {"analysis_result": {"estimated_value": 78000, "value_unit": "만원", "comparable_count": 0}}
            with engine.begin() as connection:
                history_id = connection.execute(text("""INSERT INTO history(user_id,query,category,result,created)
                    VALUES (:user,'고정 AVM 연결 검증','',cast(:result as json),:created) RETURNING id"""),
                    {"user": user["id"], "result": json.dumps(result), "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}).scalar_one()
            args = {"case_id": case_id, "property_id": candidate_id, "user_id": user["id"],
                    "history_id": history_id, "result": result, "expected_inputs": None}
            assert require(requests.post(root + "/internal/v1/store/cases/link_appraisal", json=args, headers=private_headers)) is True
            return history_id
        def fund(price):
            response = require(owner.post(root + "/api/simulation", json={"case_id": case_id,
                "candidate_id": candidate_id, "purchase_price": price, "loan_ratio": 0.5,
                "annual_interest_rate": 4, "annual_income": 100000000, "cash_available": 700000000,
                "monthly_payment_limit": 10000000}))
            assert not response.get("error"), response
            assert response["candidate_funding"]["purchase_price"] == price
        first_history = link_appraisal()
        fund(750000000)
        detail = require(owner.get(root + f"/api/cases/{case_id}"))
        assert detail["properties"][0]["appraisal"]["estimated_value"] == 780000000
        assert {a["analysis_type"] for a in detail["properties"][0]["analyses"]} == {"simulation", "appraisal"}
        require(owner.post(root + f"/api/cases/{case_id}/decision", json={"property_id": candidate_id, "reason": "7.5억 자금 검토"}))
        plan = require(owner.get(root + f"/api/cases/{case_id}/execution"))
        assert len(plan["tasks"]) == 18 and not plan["requires_selection"]
        assert next(task for task in plan["tasks"] if task["template_key"] == "appraisal_review")["status"] == "done"
        funded_task = next(task for task in plan["tasks"] if task["template_key"] == "funding_check")
        assert funded_task["status"] != "done" and "은행 승인과는 다름" in funded_task["evidence_note"]
        require(owner.patch(root + f"/api/cases/{case_id}/execution", json={"contract_planned_date": "2026-11-01", "closing_planned_date": "2026-12-01"}))
        custom = require(owner.post(root + f"/api/cases/{case_id}/execution/tasks", json={"title": "현장 소음 재확인", "phase": "before_contract"}), 201)
        require(owner.patch(root + f"/api/cases/{case_id}/execution/tasks/{custom['id']}", json={"status": "done"}), 422)
        require(owner.patch(root + f"/api/cases/{case_id}/execution/tasks/{custom['id']}", json={"status": "done", "checked_by": "본인", "outcome": "현장 확인"}))
        check("고정 AVM 결과 원 단위 저장·실제 자금 계산·선택·18개 거래 작업 연결")
        changed = row | {"asking_price": "800000000", "confirmed_at": (datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()}
        assert require(upload([changed]))["updated"] == 1
        source = require(owner.get(root + f"/api/cases/{case_id}"))["properties"][0]["source_status"]
        require(owner.post(root + f"/api/cases/{case_id}/decision", json={"property_id": candidate_id, "reason": "검토하지 않은 변경"}), 422)
        applied = require(owner.post(root + f"/api/cases/{case_id}/properties/{candidate_id}/source-update", json={
            "expected_revision_id": source["current"]["revision_id"], "expected_confirmed_at": source["current"]["confirmed_at"]}))
        assert applied["decision_reopened"] and set(applied["invalidated_analyses"]) == {"appraisal", "simulation", "rights"}
        detail = require(owner.get(root + f"/api/cases/{case_id}"))
        assert detail["selected_property_id"] is None
        assert all(a["status"] == "stale" for a in detail["properties"][0]["analyses"])
        assert detail["properties"][0]["source_reviews"][0]["previous_decision"]["reason"] == "7.5억 자금 검토"
        assert require(owner.get(root + f"/api/cases/{case_id}/execution"))["requires_selection"]
        require(owner.post(root + f"/api/cases/{case_id}/decision", json={"property_id": candidate_id, "reason": "만료된 분석으로 선택"}), 422)
        assert link_appraisal() != first_history
        fund(800000000)
        require(owner.post(root + f"/api/cases/{case_id}/decision", json={"property_id": candidate_id, "reason": "8억 자금을 다시 확인"}))
        assert require(owner.get(root + f"/api/cases/{case_id}"))["selected_property_id"] == candidate_id
        restored = requests.Session(); restored.cookies.update(owner.cookies)
        assert require(restored.get(root + f"/api/cases/{case_id}/summary"))["case"]["selected_property_id"] == candidate_id
        assert all(task["status"] == "scheduled" for task in require(owner.get(root + f"/api/cases/{case_id}/execution"))["tasks"] if task["template_key"] != "appraisal_review")
        check("가격 변경→분석 무효화·선택 해제→이전 근거 보존→재분석·재선택·새 세션 복원")
        def internal(domain, operation, args):
            return require(requests.post(root + f"/internal/v1/store/{domain}/{operation}", json=args, headers=private_headers))
        fixed = {"analysis_result": {"estimated_value": 78000, "value_unit": "만원"}}
        saved_id = internal("history", "save", {"user_id": user["id"], "query": "작업 중복 저장 검증", "result": fixed, "job_id": "a"*16})
        same_id = internal("history", "save", {"user_id": user["id"], "query": "다른 결과로 덮어쓰기 시도", "result": {"estimated_value": 1}, "job_id": "a"*16})
        assert saved_id == same_id and require(owner.get(root + f"/api/history/{saved_id}"))["analysis_result"] == fixed["analysis_result"]
        require(other.get(root + f"/api/history/{saved_id}"), 404)
        assert require(owner.get(root + "/api/history"))["total"] >= 3
        check("분석 이력 Kotlin 저장·job_id 중복 보존·타인 이력 404")
        job_id = internal("jobs", "create_task", {"task_type": "probe", "payload": {}, "owner_id": user["id"]})
        require(other.get(root + f"/api/appraisal/jobs/{job_id}"), 404)
        until = time.monotonic() + 20
        while time.monotonic() < until:
            state = require(owner.get(root + f"/api/appraisal/jobs/{job_id}"))
            if state["status"] in ("done", "error"):
                break
            time.sleep(.1)
        assert state["status"] == "done" and state["result"] == {"worker": "ready"}, state
        streamed = owner.get(root + f"/api/jobs/{job_id}/events", timeout=5)
        assert streamed.status_code == 200 and "text/event-stream" in streamed.headers["content-type"]
        assert '"status":"done"' in streamed.text and "event:job" in streamed.text
        check("Kotlin 작업 접수→Redis Stream→별도 Python 실행기→결과 저장·권한 조회·SSE")
        assert requests.get(root + "/ready").status_code == 200
        observed = {"external_id": "123456789", "requested_at": time.time()+2, "fetched_at": time.time()+3,
                    "outcome": "blocked", "fields": {}, "source_url": row["source_url"]}
        record = internal("observations", "record_observation", {"user_id": user["id"], "result": observed, "job_id": "b"*16})
        repeated = internal("observations", "record_observation", {"user_id": user["id"], "result": observed | {"outcome": "unavailable"}, "job_id": "b"*16})
        assert record == repeated and repeated["outcome"] == "blocked"
        assert len(require(owner.get(root + "/api/listings/collection/history", params={"source_url": row["source_url"]}))["items"]) == 1
        listing_after = require(owner.get(root + f"/api/listings/{id}"))
        assert listing_after["asking_price"] == 800000000 and listing_after["needs_confirmation"]
        assert require(owner.get(root + "/api/listings?fresh_only=true"))["total"] == 0
        check("수집 실패 시 가격 보존·관측 시점 저장·중복 기록 방지·최신 후보 제외")
        from redis import Redis
        metrics = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        feature = "http:GET:/api/cases/{caseId:[0-9]+}"
        deadline = time.monotonic()+3
        while not metrics.sismember(f"metrics:features:{day}", feature) and time.monotonic() < deadline:
            time.sleep(.05)
        duration = metrics.hgetall(f"metrics:duration:{day}:{feature}")
        assert int(duration["requests"]) > 0 and float(duration["total_seconds"]) > 0
        assert any(name.startswith("bucket:") for name in duration)
        assert not any(f"/api/cases/{case_id}" in key for key in metrics.smembers(f"metrics:features:{day}") if key.startswith("http:GET:/api/cases/"))
        check("Kotlin HTTP 운영 지표·기존 화면 집계 호환·실제 케이스 ID 제외")
        old_token = owner.cookies.get("auth_token")
        internal("accounts", "update_password", {"user_id": user["id"], "password_hash": "$2b$12$not-used-login-during-reset-check"})
        require(owner.get(root + "/api/auth/me"), 401)
        owner.cookies.set("auth_token", old_token)
        require(owner.post(root + "/api/chat", json={"message":"만료 세션 검증"}), 401)
        require(owner.get(python + "/api/activity", headers=private_headers), 404)
        # 제거용 유효 토큰은 새로운 버전으로 직접 발급한다. 공개 서비스 자격증명을 사용하지 않는다.
        import jwt
        with engine.connect() as connection:
            version = connection.execute(text("SELECT password_changed_at FROM users WHERE id=:id"), {"id": user["id"]}).scalar_one()
        replacement = jwt.encode({"sub": str(user["id"]), "pwd_at": version, "exp": int(time.time())+600}, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
        owner.cookies.clear(); owner.cookies.set("auth_token", replacement)
        check("Kotlin 비밀번호 변경 후 일반·AI 공개 경로의 기존 JWT 무효화")
        report["status"] = "passed"
    except Exception as exc:
        report["status"], report["error"] = "failed", str(exc)
        raise
    finally:
        for session in (owner, other):
            if session.cookies.get("auth_token"):
                session.delete(root + "/api/auth/me")
        Path("evaluation-results").mkdir(exist_ok=True)
        Path("evaluation-results/spring-core-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        engine.dispose()


if __name__ == "__main__":
    main()
