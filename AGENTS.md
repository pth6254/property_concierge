# 에이전트 작업 지침 — 부동산 컨시어지

> 이 파일은 Claude Code · Codex 등 **모든 코딩 에이전트가 공유하는 단일 원본**이다.
> `CLAUDE.md` 는 이 파일을 `@AGENTS.md` 로 임포트만 한다 — 내용을 양쪽에 복제하지 말 것.
> 사람이 읽는 셋업·기능 설명은 `README.md` 에 있다. 여기에는 **코드를 고칠 때 알아야 할
> 제약과 함정**만 적는다.

---

## 1. 프로젝트 한눈에

서비스 책임 중심 경로는 `services/platform/`, `services/intelligence/`, `web/`다.
내부 명세는 `contracts/v1/`, 실행 인프라는 `infrastructure/`에 있다.
폴더를 되돌리거나 루트에 구현 복제본을 두지 않는다. [구조 안내](docs/architecture.md#repository)를 따른다.
Compose 실행은 `scripts/compose.sh` 또는 `compose.ps1`로 프로젝트 경로·이름을 고정한다.

기능 설명은 `docs/features/`의 매물·의사결정·챗봇·탐색 문서에 통합한다.
작은 변경마다 문서를 새로 만들지 말고 해당 문서의 계약·제약·검증 절을 갱신한다.
구조·운영·과거 실측의 위치는 [문서 안내](docs/README.md)를 따른다.

사용자가 가져온 매물을 매수 케이스에 저장하고 **적합성·가격성·자금성·위험성·실행성**을
검토해 후보 비교·선택·다음 행동으로 이어가는 부동산 의사결정 플랫폼이다.
국토부 실거래 기반 AVM·자금 계산·권리 점검·챗봇·동네 탐색은 이 흐름을 지원한다.

현재 개발 순서는 **아파트 매수 의사결정 기반 완성부터**다. 독립 모바일 앱은 나중에 진행한다.
포털 링크와 비공식 매물 추출 성공을 핵심 흐름의 필수 조건으로 만들지 않는다.
제품 단계는 [제품 전략](docs/product-strategy.md), 구현 상태와 다음 작업은
[인수인계 문서](docs/project-handoff.md)를 따른다.

```
웹 호스트 :3002 → Caddy → Next.js 16 (App Router) 내부 :3000
   │ /api · JWT 쿠키 (Caddy가 Spring으로 전달)
Kotlin Spring 내부 :8080 / 기본 API 호스트 :8002
   ├── services/platform/ 회원·매물·케이스·거래 상태·분석 이력·작업 저장·자금/세금 계산
   │ 내부 REST (서비스 인증)
FastAPI 내부 :8000 (공개 포트 없음, uvicorn --workers 4)
   ├── services/intelligence/api/          내부 AI·데이터 계약 · AI 작업 실행기
   ├── services/intelligence/backend/      LangGraph 파이프라인 + 도메인 로직
   ├── services/intelligence/db/           SQLAlchemy 모델 + Alembic + Redis 클라이언트
   └── services/intelligence/schemas/      Pydantic 스키마 (단위: 원 · ㎡)
        │
PostgreSQL(+pgvector) · Redis
```

시세추정은 `주거 / 상업 / 업무 / 산업 / 토지` **5개 유형별 에이전트**로 조건부 분기한다
(`services/intelligence/backend/graphs/appraisal_graph.py` 의 `CATEGORY_TO_AGENT`). 신규 유형은 이 매핑에
에이전트를 추가하면 된다. 이 분기가 존재한다는 사실을 전국·모든 자산 유형의 같은 수준의
데이터 및 제품 검증이 완료됐다는 뜻으로 설명하지 않는다.

기획안의 `Property` 유형별 모델·Buyer Decision Graph·Listing Time Machine·Marketplace는
후속 설계다. 현재의 `ImportedListing`·관측/변경 이력·`PurchaseCase`·후보·거래 준비 모델을
우선 연결하고, 새 저장소나 테이블은 기존 데이터와 권한을 유지하는 이관 계획과 함께 추가한다.

---

## 2. 절대 되돌리면 안 되는 결정

**백엔드 전환:** 언어는 사용자 결정에 따라 Kotlin이다. `services/platform/`의 Spring은 저장·소유자 확인·트랜잭션을,
고정 수식의 금융·세금 계산도 담당한다. Python은 모델 추정·입력 해석·AI 분석을 담당한다.
기본 API 8002는 Spring이며 Python은 내부 전용이다.
`CORE_STORAGE_URL`은 필수이며 전환된 영역은 `services/intelligence/api/core_bridge.py`를 통해 Spring에 저장한다. 중복 Python SQL 구현은 제거했다. 실패 시 Python SQL로
폴백하거나 양쪽 저장소에 이중 저장하지 않는다. AI 원격 호출을 DB 트랜잭션 안에 추가하지 않는다.
Kotlin에서 `!!`로 필수 값을 강제하지 말고, 외부 JSON의 null·목록 원소·소수 금액을 검증한다.
Alembic은 전환 중에도 스키마의 단일 관리 도구다. Hibernate 자동 DDL을 켜지 않는다.
Compose는 API·실행기 모두 Spring 저장 계약으로 고정한다. 한쪽만 이전 저장소로 바꾸지 않는다.
Caddy가 웹 3002의 `/api/*`를 Spring에 직접 전달한다. Spring은 Caddy 172.30.92.2,
Python은 Spring 172.31.244.2만 IP 헤더를 신뢰한다. Next나 사설망 전체를 신뢰 목록에 추가하지 않는다.
계약·실행·검증 경계는 [백엔드 전환 안내](docs/architecture.md#backend)를 확인한다.
일반 공개 API·OAuth·재설정·메일·탈퇴·주소·운영·작업 접수는 Spring이다.
대체된 Python 일반 API·인증·주소·레이트 리밋 파일 16개를 삭제했다.
Python은 `/internal/v1/ai/*`·`/internal/v1/data/*`와 순수 분석 계약만 제공하며 항상 서비스 키를 검증한다.
`X-AI-User-Id`는 Spring이 세션 검증 후 설정한다. 브라우저 쿠키·JWT를 Python에서 처리하지 않는다.
`scripts/audit_python_routes.py`는 중복 경로가 생기면 실패한다. 기존 HTTP 회귀 테스트는
`tests/service_client.py`를 통해 이전된 경로를 실제 격리 Spring에 보낸다. Python 핸들러를 테스트용으로 복구하지 않는다.
챗봇 자금 분석은 `funding_execution_client.py` → `/internal/v1/simulation`으로 계산·소유자 확인·저장을 함께 실행한다.
자금 입력 계약은 `services/intelligence/schemas/funding_request.py`다. 제거된 `api.routes.simulation.SimulationRequest`를 다시 추가하지 않는다.
Spring 검증도 `real_estate_test`·Redis 15만 사용한다. Python 테스트와 Spring 검증을 동시에 실행하면
같은 테스트 DB를 비우는 작업이 충돌하므로 두 실행기는 순서대로 실행한다.

**계산 책임:** `services/platform/.../calculations/`의 `FinanceCalculator`·`TaxRules`가 자금·세금 수치의 실행 원본이다.
Python 시뮬레이션·챗봇 세금 도구는 `core_calculations.py`로 같은 계산기를 호출한다.
연결 실패 시 Python 수식·LLM 계산으로 대체하지 않는다. 중복 수식은 제거했고 기존 54개 결과는 고정 회귀 자료로 보존한다.
Python 테스트도 격리 Spring에 연결한다. `TEST_CORE_URL` 일치와 실제 DB 이름·Redis 15 확인을 우회하지 않는다.
금액은 BigDecimal로 중간 계산하고 원 단위 HALF_EVEN, 대출 비율의 원 단위 변환만 버림을 적용한다.
금액 범위 초과는 422로 거부하며 결과에 엔진·계산 버전·세율 기준일을 보존한다.
`2026-01-01` 간이 정책을 이관한 것이며 최신 법령·대출 심사를 검증했다는 뜻으로 설명하지 않는다.
AVM 통계 보정·추천 점수·다섯 판단 축 등의 기존 Python 규칙까지 전부 이전했다고 말하지 않는다.
계산 경계·검증은 [계산 책임 문서](docs/architecture.md#calculations)를 따른다.

아래는 모두 **문제를 겪고 내린 결정**이다. "단순화"하려다 되돌리기 쉬우니 주의할 것.

### 2-1. SQLite · 인프로세스 메모리 폴백을 두지 않는다

`DATABASE_URL` / `REDIS_URL` 이 없으면 **기동을 막는다**(`services/intelligence/db/base.py`, `services/intelligence/db/redis_client.py`).
"로컬은 SQLite, 운영은 Postgres"로 갈라지면 로컬에서 검증되지 않은 쿼리가 운영에서만
깨진다. 로컬 개발도 `sh scripts/compose.sh dev up -d pgvector redis` 를 전제로 한다.

작업 큐 · 레이트 리밋 · 로그인 잠금 상태도 **전부 Redis**다. 프로세스 메모리로 되돌리면
멀티 워커에서 상태가 갈려 다음이 조용히 깨진다:
- 워커 A가 만든 job을 워커 B가 못 찾음 → 폴링 404
- 레이트 리밋 · 로그인 잠금 한도가 워커 수만큼 실질 증가 → 브루트포스 방어 무력화

### 2-2. Alembic 은 워커 기동 "전에" 단일 프로세스로 실행한다

`infrastructure/docker/Dockerfile.intelligence` 의 `CMD` 가 `alembic -c services/intelligence/alembic.ini upgrade head && uvicorn ... --workers N` 인 것은
의도된 순서다. 스키마를 먼저 확정해야 여러 워커가 동시에 DDL을 치는 경합이 아예 생기지 않는다.

`services/intelligence/db/base.py` 의 `init_db()`(create_all)는 alembic 없이 `uvicorn` 을 직접 띄우는
로컬·테스트 경로용 **안전망**이다. 지우지 말 것. 단, create_all 은 컬럼 삭제·타입 변경을
반영하지 못하므로 그런 변경은 반드시 마이그레이션을 만들어야 한다.

```bash
alembic -c services/intelligence/alembic.ini revision --autogenerate -m "설명"   # 생성 후 파일을 반드시 검토
alembic -c services/intelligence/alembic.ini upgrade head
```

**autogenerate 결과에서 아래 세 테이블의 `drop_table` 은 반드시 지울 것:**
`real_estate_docs` · `langchain_pg_collection` · `langchain_pg_embedding`

이 셋은 `infrastructure/database/init.sql` 이 만드는 RAG 벡터스토어 테이블로 `services/intelligence/db/models.py` 에 없다.
autogenerate 는 모델에 없으면 "삭제된 것"으로 간주해 **매번 drop 구문을 끼워 넣는다.**
그대로 적용하면 RAG 데이터가 전부 사라진다 (실제로 겪어서 `b7e42562ca36` 에서 제거함).

### 2-3. 소유자 검증 없이 레코드를 조회하지 않는다

`history` · `activity` 의 id는 순차 정수다. 사용자 요청 경로에서 소유자 필터 없이 조회하면
id를 훑어 타인 데이터를 전량 읽을 수 있다(실제로 있었던 취약점).

- 조회 함수에 `user_id` 를 넘긴다 (`history_db.load_one(record_id, user_id=...)`)
- 타인 레코드는 403이 아니라 **404** — 403은 "그 id에 무언가 있다"를 노출한다
- 회귀 테스트: `tests/test_access_control.py` (이 파일을 지우거나 약화시키지 말 것)

### 2-4. 시크릿을 저장소에 넣지 않는다

`infrastructure/compose/compose.yml` 은 `${POSTGRES_PASSWORD:?...}` 로 **미설정 시 기동 실패**하게 되어 있다.
편의를 위해 기본값을 넣으면 그 값이 그대로 운영에 올라간다.

`.github/workflows/ci.yml` 의 postgres 비밀번호는 예외다 — 워크플로 실행 중에만 존재하는
휘발성 컨테이너라 유출 리스크가 없다(주석에 명시되어 있음).

### 2-5. 리버스 프록시 뒤에 배포하면 FORWARDED_ALLOW_IPS 를 반드시 지정한다

현재 레이트 리밋(`RedisLimits`)과 로그인 잠금이 **클라이언트 IP 기준**인데, 프록시를 거치면
FastAPI 에는 모든 요청이 프록시 IP 하나로 들어온다. 실제 IP 는 `X-Forwarded-For` 에 있다.

uvicorn 은 `proxy_headers=True` 가 기본이지만 `forwarded_allow_ips` 기본값이
`"127.0.0.1"` 이라 **같은 기계의 프록시만** 신뢰한다. sh scripts/compose.sh dev 처럼 프록시가
별도 컨테이너면 기본값으로는 동작하지 않는다 — `FORWARDED_ALLOW_IPS` 환경변수에
프록시 IP/대역을 넣으면 uvicorn 이 자동으로 읽는다(코드 변경 불필요).

**실측 결과** (register 분당 5회 제한, 7회 연속 요청):

| 조건 | 6번째 요청 |
|---|---|
| 기본값 + `X-Forwarded-For` 위조 | **201** ← 위조가 통해 레이트 리밋 무력화 |
| 기본값 + 헤더 없음 | 429 (정상) |
| `FORWARDED_ALLOW_IPS=<프록시IP>` + 위조 | 429 (정상) |

⚠️ `"*"` 로 열어두고 앱이 외부에 직접 노출되면 누구나 헤더를 위조해 우회할 수 있다.
프록시 주소를 정확히 지정할 것.

### 2-6. LLM 수치 가드레일을 우회하지 않는다

`services/intelligence/backend/opinion_guard.py` 는 LLM 출력에서 **컨텍스트로 주입한 수치 외의 숫자가 든 문장을
자동 삭제**한다. 부동산 가격에서 환각은 치명적이라 프롬프트 부탁이 아니라 출력 검증으로
막는다. 위반 시 1회 재생성 → 결정론적 폴백.

### 2-7. 비밀번호가 바뀌면 기존 JWT 를 전부 무효화한다

JWT 는 stateless 라 발급 후에는 서버가 취소할 방법이 원래 없다. 그래서 "비밀번호를 바꿨는데
탈취당한 세션이 만료(7일)까지 살아 있는" 상태가 된다 — 재설정 기능의 목적 자체가 무너진다.

세션 테이블을 만드는 대신 **버전 클레임**으로 해결했다:

- `users.password_changed_at` (ISO8601 문자열) 을 비밀번호 변경 시 갱신
- 토큰 발급 시 그 값을 `pwd_at` 클레임으로 심는다 (`SessionService.issue`)
- 요청마다 `SessionService.validate`로 대조 → 불일치면 401
  (`SessionService.required`·`optional` **양쪽 모두**)

`optional` 검증을 빼먹으면 비로그인도 되는 경로에서 옛 토큰이 계속 통한다. 둘 다 고칠 것.
`password_changed_at` 이 `None` 인 계정(재설정 이력 없음)은 무조건 유효 — 기존 사용자가
마이그레이션 직후 전원 로그아웃되지 않게 한 의도적 처리다.

회귀 테스트: `tests/test_password_reset.py`.

### 2-8. 쿠키 SameSite 는 배포 형태에 맞춰 환경변수로 고른다

증상이 항상 **"로그인이 그냥 안 됨"** 이라 원인 추적이 특히 어려운 영역이다.
브라우저는 잘못된 조합을 오류 없이 **조용히 버린다**.

| 배포 형태 | `COOKIE_SAMESITE` |
|---|---|
| 프론트·API 가 같은 출처 (**현재 구조** — `next.config.ts` 의 rewrites 가 `/api/*` 중계) | `lax` (기본) |
| 서로 다른 사이트 (예: `app.vercel.app` ↔ `api.fly.dev`) | `none` — HTTPS 필수 |

- `none` 이면 `APP_ENV` 와 무관하게 `secure` 가 자동으로 켜진다. Secure 없는 `SameSite=None`
  은 브라우저가 무시하기 때문 (`SessionService.secure`).
- 오타는 **기동 시점에 RuntimeError** 로 죽인다. 런타임에 잘못된 값이 조용히 나가면
  증상만 보고는 절대 못 찾는다.
- **로그아웃 시 삭제 쿠키도 같은 속성으로 내려야 한다.** 속성이 다르면 브라우저가 다른
  쿠키로 보고 지우지 않는다 (`AuthController.logout`·`AccountLifecycleController` 삭제 쿠키).

회귀 테스트: Kotlin `CookieContractTest`(환경 조합·잘못된 설정·삭제 헤더)와
`tests/test_cookie_config.py`(실제 Spring 발급·삭제 HTTP 헤더). OAuth state 쿠키는 외부 콜백을 위해 Lax를 사용한다.

### 2-9. 오래 걸리는 작업은 별도 실행기에서 처리한다

공개 AVM·수집·채팅 접수는 Spring `AiWorkController` → `AiJobStore`가 JSON 입력을 Redis Stream에
기록한다. AI 도구의 하위 작업은 `services/intelligence/api/jobs.py`의 내부 Spring 계약을 호출한다.
`services/intelligence/api/job_worker.py`가 별도 컨테이너에서 실행한다. API 내부 스레드 실행으로
되돌리면 서버 재시작 때 진행 중 작업이 사라진다. 운영 Redis의 AOF 설정과
`job-worker` 서비스도 함께 유지할 것. AVM 이력·수집 기록은 `job_id`로 중복 저장을 막는다.

실행 도중 죽은 채팅·종합 컨시어지 작업은 대화 중복을 피하려고 자동 재실행하지 않고
사용자 재질문을 안내한다. 정확한 경계는 `docs/operations.md#job-recovery`를 따른다.

### 2-10. pytest는 서비스 DB·Redis에 절대 연결하지 않는다

일부 통합 테스트는 `users`·`transactions`·`legal_regions` 등을 비운다. 2026-09-27에
테스트 기본 접속 주소가 실행 중인 서비스 DB를 가리켜 실데이터가 지워졌고 백업으로
복구했다. `tests/conftest.py`는 명시적인 `TEST_DATABASE_URL`의 DB 이름이
`real_estate_test`, `TEST_REDIS_URL`의 DB 번호가 `15`인지 확인하고, 아니면 테스트를
시작하지 않는다. 로컬에서는 `scripts/run_isolated_tests.py`를 사용한다. 이 보호를
우회하거나 테스트 파일에 서비스 DB 주소를 기본값으로 넣지 말 것.

### 2-11. 다섯 판단 축과 후보 비교는 같은 검토 기준을 쓴다

`services/intelligence/schemas/decision_assessment.py`와 `services/intelligence/backend/services/case_decision_assessment.py`가
후보별 상태·근거·기준일·누락 정보·다음 행동의 공통 계약이다.
`GET /api/cases/{id}/summary`의 `decision`과 `comparison`은 같은 평가 결과를 사용한다.
화면이나 비교 서비스에 별도의 완료 기준·점수·매수 결론을 만들지 않는다.

- 미입력·판독 실패·낮은 신뢰도·유효하지 않은 기준일은 확인된 값이나 안전으로 바꾸지 않는다.
- 만료·원본 변경으로 사용할 수 없는 분석은 현재 비교 금액에서 제외한다. 과거 근거는 구분해 표시한다.
- 권리 PDF의 **업로드 여부와 판독 성공 여부를 구분**한다. 기존 결과에 판독 기록이 없으면 미확인이다.
- 판독 실패·부분 판독을 안전 또는 0점으로 만들지 않는다. 최소 근거는 페이지·명시 발급일·문서 지문·키워드/금액만 보존하며 원문·이름·주민번호 주변 문장을 저장하지 않는다.
- 비교사례 표시와 신뢰도는 `comparable_matching.py`의 같은 기준을 사용한다. 구 대체 사례의 첫 단지를 동일 단지로 간주하거나 동 이름만 있다는 이유로 동일 동으로 분류하지 않는다.
- `review_ready`는 등록 자료와 검토 항목의 확인 상태이며 거래 안전성이나 매수 승인이 아니다.
- 조회 중 LLM·외부 API·새 작업을 실행하거나 후보 선택 상태를 변경하지 않는다. 선택은 사용자가 한다.

회귀 테스트는 `tests/test_case_decision_assessment.py`, 화면 검증은
`scripts/verify_decision_assessment_browser.cjs`다. 기준은 [의사결정 검토 문서](docs/features/decision.md#decision-assessment)를 따른다.

### 2-12. 자금 입력 의미와 후보별 저장 조건을 유지한다

`owned_homes`는 **이번 취득 후 주택 수**다. 첫 주택은 1이며 결과 입력에
`home_count_basis="after_purchase"`를 기록한다. 표시 문구만 바꾸고 계산기의 의미를 다르게 두지 않는다.
화면·채팅·케이스 시나리오는 `services/intelligence/schemas/simulation.py`의 공통 변환을 사용한다.

공통 프로필의 비상자금은 가용 현금에서 한 번만 제외한다. 후보별 저장 입력은 이미 반영된
가용 현금이므로 재계산 화면에서 다시 빼지 않는다. 저장된 개별 조건은 공통 조건과 다를 수 있다.
공통 조건으로 조용히 덮어쓰거나 다르다는 이유만으로 분석을 만료시키지 않는다.
후보의 현재 가격과 분석에 사용한 가격은 일치해야 한다.

회귀 테스트는 `tests/test_funding_consistency.py`, 화면 검증은
`scripts/verify_candidate_funding_browser.cjs`다. [자금 입력 기준](docs/features/decision.md#funding-input)을 따른다.

### 2-13. 매물 거래 상태·자료 시점·확인 출처를 섞지 않는다

사용자 등록 호가·실거래·AVM 추정가는 다른 자료다. 출처와 확인 시각을 유지하고,
원본 관측 실패나 페이지 미노출을 거래 완료로 판단하지 않는다.
변경/관측 이력과 후보의 재검토 상태를 함께 유지한다. 재수집 실패로 마지막 성공 값을 덮어쓰지 않는다.

주소가 같은 광고를 같은 개별 호로 자동 합치지 않는다. 단지 수준 확인과 개별 매물 확인을 구분한다.
권리 원문 PDF는 저장하지 않는다. 후보에는 페이지·문서 지문·명시 발급일과 위험 키워드/금액의 최소 근거만 저장한다.
문서 근거 보관을 확장할 때도 사용자 소유 범위·최소화·보관 정책을 유지하고 원문 자동 영구 저장을 도입하지 않는다.
`identity`의 동·호·층·면적 기준은 기존 매물 payload와 후보 스냅샷에 저장한다. 개별 호는 사용자 입력이며 주소 조회로 확인됐다고 표시하지 않는다.
물건 정보 변경은 이전 분석·선택 이력을 보존하고 재검토한다. 분석의 `expected_inputs`에는 물건 정보도 포함한다.
공급면적을 전용면적으로 AVM에 넘기지 않는다. 선택 필드가 없는 기존 CSV의 면적 기준은 미확인이다.
상태 및 수집 계약은 [매물 등록](docs/features/listings.md#listing-registration)과 [매물 수집](docs/features/listings.md#listing-collection)을 따른다.

주소 기반 등록은 서버가 선택 확인 정보의 서명·사용자·만료와 이름·주소를 대조한다.
`alias`는 선택적인 표시용 별칭이고 AVM 단지 매칭이나 확인된 `name`을 대체하지 않는다.
확인 정보 자체를 DB·이력에 저장하거나 인증 JWT처럼 사용하지 않는다. 기존 JSON에 주소 근거와
별칭을 저장하며 CSV에 새 선택 필드가 없는 입력도 유지한다. [주소 등록 계약](docs/features/listings.md#address-registration)을 따른다.

건축물대장 공개 조회는 Spring `BuildingRegisterService`가 수행한다. 단지·건물·층·호실 면적을 구분하고 첫 부속건물이나 다중 동을 임의로 선택하지 않는다.
동·호는 각각 선택이며 필지·동·호·대장번호를 대조한 전유면적만 사용자가 적용한다. 공용면적을 공급면적으로 합산하거나 자료 생성일을 사용승인일로 대체하지 않는다.
`building_token`은 주소 확인과 별도 서명이며 사용자·필지·입력 동호에 묶이고 저장하지 않는다. 공개 근거만 기존 `address_details.building_register`에 보존한다.
유형·주소·동호 변경 후 이전 결과 적용과 저장 근거를 차단하고 조회 실패에도 직접 입력을 유지한다. [건축물 조회 계약](docs/features/listings.md#building-register)을 따른다.
공공데이터 API 키는 원문과 인코딩 형식을 모두 지원한다. 원문 `+`를 URLDecoder로 공백으로 바꾸면 실제 조회가 거절된다.
Spring `decodeDataGoKey`를 통해 정규화하고 쿼리 값은 한 번 인코딩한다. 키·키 포함 요청 URL을 로그나 검증 아티팩트에 출력하지 않는다.

---

## 3. 실측으로 확인한 함정

여기 적힌 것들은 전부 **실제로 재현해서 확인한 것**이다. 추측이 아니다.

### 3-1. pydantic 은 모르는 필드를 조용히 무시한다

```python
AppraisalResult(judgement="저평가")   # judgement 는 존재하지 않는 필드 — 오류 없이 버려짐
```

`AppraisalResult` 에서 제거된 `judgement` · `gap_rate` 를 테스트가 계속 넘기고 있었고,
**아무것도 검증하지 않으면서 통과하는 상태**였다. 스키마를 바꾸면 테스트도 함께 갱신할 것.

### 3-2. `create_all` 은 멀티 프로세스에서 경합한다

빈 DB에 4개 워커를 동시에 붙이면 **매번** 3개가 죽는다. 예상과 달리 테이블
(`ProgrammingError` / DuplicateTable)뿐 아니라 **SERIAL 컬럼의 시퀀스에서도
`IntegrityError` / UniqueViolation** 이 난다. 두 예외를 모두 잡아야 한다
(`services/intelligence/db/base.py` 의 `init_db()` 참고).

### 3-3. Next.js 16 · React 19

- **`middleware.ts` 가 아니라 `proxy.ts`** 다. Next 16에서 이름이 바뀌었다(`src/proxy.ts`).
- `web/AGENTS.md` 의 경고대로, 코드 작성 전 `web/node_modules/next/dist/docs/` 를
  확인할 것. 학습 데이터와 다르다.
- **effect 안에서 동기 `setState` 금지** (`react-hooks/set-state-in-effect`). CI 린트가 잡는다.
  - sessionStorage 읽기는 반드시 `web/src/lib/sessionStore.ts` 의
    `useSessionValue` / `setSessionValue` / `removeSessionValue` 를 쓴다.
    raw `sessionStorage.setItem` 으로 쓰면 구독자가 갱신되지 않는다.
  - 마운트 시 fetch는 `await` 이후에 setState 하고 취소 플래그를 둔다.
  - 경로 변경 시 상태 초기화는 `key` 기반 재마운트로 한다 (`Navbar.tsx` 참고).

### 3-4. 클라이언트 전용 값 때문에 페이지 전체를 비우지 말 것

`if (value === undefined) return null` 로 페이지를 통째로 막으면 **SSR이 빈 셸로 내려간다**
(`/appraisal` 이 20.6KB → 16.5KB 로 줄고 본문이 사라졌던 실제 회귀).

대신:
- 파생 값으로 처리 (`typed ?? seed ?? ""`) — `appraisal/page.tsx`
- 또는 `key` 로 재마운트 — `simulation/page.tsx`

`/report` · `/comparison` 은 예외적으로 게이트를 쓴다 — 이전에 "결과 없음"이 한 번 그려졌다
사라지는 깜빡임이 있었고, 빈 화면이 잘못된 내용보다 낫다고 판단했다.

### 3-5. 시드 값 삭제는 언마운트에서

프리필 값(`heroQuery`, `simFromListing`)을 마운트 시점에 지우면, 파생 값/`key` 가 즉시
바뀌어 **입력이 스스로 비워진다**. 반드시 `useEffect` cleanup 에서 지울 것.

---

## 4. 개발 환경 (이 저장소 특이사항)

WSL과 Windows가 섞여 있다. 툴별로 위치가 다르니 주의.

| 대상 | 위치 | 비고 |
|---|---|---|
| Python venv | `venv-wsl/` (WSL 전용) | `bin/pip` 의 shebang이 깨져 있음 → **`./venv-wsl/bin/python -m pip`** 로 실행 |
| node · npm | **Windows 쪽만** 존재 | WSL 에는 없다. `npx next build` 는 WSL에서 되지만 `node script.js` 는 PowerShell로 |
| docker | WSL에서 사용 가능 | 컨테이너: `property_concierge_pgvector`, `property_concierge_redis` |

WSL의 `127.0.0.1` 과 Windows의 `127.0.0.1` 은 **다른 네트워크 네임스페이스**다.
Windows에서 띄운 서버를 WSL curl로 때리면 연결되지 않는다.

---

## 5. 명령어

```bash
# ── 백엔드 ──────────────────────────────────────────────
sh scripts/compose.sh dev up -d pgvector redis          # DB·캐시 먼저

./venv-wsl/bin/python scripts/run_isolated_tests.py tests/ -q

alembic -c services/intelligence/alembic.ini upgrade head                          # 마이그레이션 적용

# ── 프론트엔드 ──────────────────────────────────────────
cd web
npx tsc --noEmit    # 타입 체크
npm run lint        # ESLint (set-state-in-effect 등)
npm run build       # 프로덕션 빌드

# ── 전체 실행 ───────────────────────────────────────────
sh scripts/compose.sh dev up --build                     # 개발 (override 명시 병합)
sh scripts/compose.sh local up -d --build   # 운영 (override 배제)

# ── 백업 ────────────────────────────────────────────────
./scripts/backup_db.sh
./scripts/restore_db.sh backups/property_concierge_<타임스탬프>.dump
```

**CI**(`.github/workflows/ci.yml`)는 세 job을 병렬 실행한다:
- `test` — PostgreSQL·Redis 서비스 컨테이너 + `alembic -c services/intelligence/alembic.ini upgrade head` + `pytest` + 오프라인 평가.
- `frontend` — `tsc --noEmit` + `npm run lint` + `npm run build`
- `spring` — 별도 API·작업 실행기를 띄우고 저장·권한·계산·프록시와 브라우저 흐름 8종을 검증한다.
  주소 등록·선택 별칭·매물 변경 재검토를 포함하며 결과 JSON과 화면 이미지를 아티팩트로 보관한다.

**변경 후에는 양쪽을 모두 돌려볼 것.** 백엔드만 고쳤다고 프론트가 안전한 게 아니다
(API 응답 형태가 바뀌면 `web/src/lib/api.ts` 의 타입도 함께 고쳐야 한다).

현재 실행 중인 로컬 서비스의 후보 흐름 확인은 저장소 루트의 **PowerShell**에서 실행한다:

```powershell
node scripts/verify_candidate_funding_browser.cjs
node scripts/verify_decision_assessment_browser.cjs
```

이 브라우저 검증은 연결한 API에 임시 계정과 데이터를 만들고 종료 시 삭제한다.
격리 DB 보호가 적용되는 pytest와 구분할 것. 명령 뒤에 API 주소를 주면 개발 프론트엔드를
따로 띄우는 모드로 실행한다. 로컬 통과와 원격 GitHub Actions 완료는 별도로 기록한다.

---

## 6. 코드 컨벤션

- **주석·문서는 한국어.** 기존 코드 톤을 따를 것.
- **주석은 "무엇"이 아니라 "왜"를 적는다.** 특히 되돌리기 쉬운 결정에는 이유를 남긴다.
- 프론트엔드에 `any` · `@ts-ignore` 를 쓰지 않는다 (현재 0건).
- 금액 단위는 **원(int)**, 면적은 **㎡(float)**.
  예외: `services/intelligence/backend/models.py` 의 `ValuationResult` 는 만원 단위 — 리포트 생성 시 변환한다.
- 파일명은 구체적으로. `report.py` · `utils.py` 같은 흔한 이름은 외부 패키지와 충돌한다
  (실제로 겪어서 `appraisal_report.py` 로 바꾼 이력이 있음).

---

## 7. 제품상 알아둘 것

기능을 고칠 때 **사실과 다르게 말하지 않도록** 알아둬야 하는 것들.

- **샘플 매물추천·비교 도구는 개발용 가상 데이터**(`data/sample_listings.csv`, 43건)를 쓴다.
  매물 보관함과 매수 케이스는 사용자 제공 매물과 저장된 분석을 사용한다. 출처·확인 시각을
  표시하지만 실호가를 서비스가 독립 검증한 것은 아니다. **시세추정은 국토부 실거래가 실데이터**를 쓴다.
  동네 탐색의 실거래 기반 단지 추천은 현재 거래 가능한 개별 매물 목록이 아니다.
- 다섯 판단 축의 `등록 자료 확인`은 기록된 기준을 비교할 수 있다는 뜻이다. 통근·학군·소음·주차,
  문서 발급일·페이지 근거·개별 호의 동일성을 확인하지 못했다면 그 한계를 표시한다.
  거래 준비 작업을 완료해도 실제 계약·잔금·등기까지 완료된 것으로 설명하지 않는다.
- **AVM 신뢰도 편차가 크다.** 백테스트(서초구 434건) 실측 기준 동일 단지 매칭은
  ±10% 적중률 69~84%지만 **동일동·구 매칭은 8~33%** 다.
  신뢰도는 이 실측치를 블렌딩해 하향 보정된다(`services/intelligence/backend/confidence.py`).
- **시점수정은 주거용·토지만** 부동산원 R-ONE 지수를 적용한다. 상업·업무·산업용은
  적합한 월간 시군구 지수가 없어 근사 변동률을 쓴다.
- **의도분석의 `clarification_question` 은 사용자에게 노출되지 않는다.**
  내부 재분석 루프(최대 2회)에만 쓰이고, 그래도 부족하면 오류로 끝난다.
  "사용자에게 보완 질문을 던진다"고 설명하면 사실과 다르다.
- 시세추정은 **AVM 기반 참고용 분석**이며 「감정평가 및 감정평가사에 관한 법률」에 따른
  감정평가가 아니다. UI·문서에서 이 고지를 빼지 말 것.
- **비밀번호 재설정 메일은 아직 실제로 발송되지 않는다.** `RESEND_API_KEY` 가 비어 있으면
  Spring `PasswordResetMail`이 **서버 로그에 재설정 링크를 출력**한다(의도적 폴백 — 로컬·CI가
  외부 메일 서비스에 의존하지 않게 함). 실발송하려면 Resend 계정 + 도메인 인증(SPF/DKIM)이
  필요하고 아직 하지 않았다. "메일이 나간다"고 설명하면 사실과 다르다.
- **재설정 요청 응답은 계정 존재 여부와 무관하게 항상 동일하다**(`_RESET_GENERIC_RESPONSE`).
  가입 여부를 알려주면 계정 열거(account enumeration)가 된다. "없는 메일입니다" 같은
  친절한 안내로 바꾸지 말 것.

---

## 8. 현재 알려진 부채

**코드 쪽**
- **프론트엔드 단위 테스트 0건.** CI에는 타입체크·린트·빌드와 브라우저 흐름 8종이 있다.
- 후보 → 자금 화면의 입력 전달·저장·새로고침과 판단 축 표시는 브라우저로 검증했다.
  홈 → `/appraisal`, 샘플 추천 → `/simulation`의 프리필은 별도 브라우저 검증이 필요하다.
- 실제 AVM과 권리 PDF까지 연결한 전체 흐름의 품질 검증은 아직 별도 작업이다.
  가상 텍스트 PDF의 실제 판독·페이지 근거·후보 저장은 `verify_property_evidence_browser.cjs`로 검증하지만 실제 발급 문서의 정확도 실적은 아니다.
  현재 검증 범위와 최신 기록은 [의사결정 검토 문서](docs/features/decision.md#decision-assessment-검증-범위)를 따른다.

**운영 쪽 (배포 전에 해야 하는 것)**
- **공개 서버·도메인의 HTTPS 운영은 미적용.** Caddy·운영 배포 설정은 준비했지만 실제 도메인
  인증서·외부 접속·프록시 IP 신뢰 설정을 확인해야 한다(2-5, `docs/operations.md#administration`).
- **Resend 도메인 인증 미완료** — 위 7절 참고. 그 전까지 재설정은 운영자가 로그의 링크를
  수동 전달하는 방식으로만 가능하다.
- **Google OAuth 리다이렉트 URI 가 localhost 로만 등록**되어 있다. 실도메인 등록 필요.
- **국토부 API 지역 시딩은 서울 25개 구 매매 거래에 적용했다.** 매물 원문은 정기 수집하지 않는다. 로컬 Docker의 실거래 갱신은 2026-09-27에 `transaction-refresh` 유지보수 프로필을 활성화했다. 다른 배포 환경에서는 별도로 활성화해야 한다.

**제품 쪽**
- 자체 대규모 활성 매물 DB·공식 공급 제휴는 없다. 초기 핵심 흐름은 사용자 직접 등록을 기반으로 하며,
  샘플 추천과 실제 사용자 후보를 구분한다. 비공식 포털 수집에 제품 전체를 의존하지 않는다.
- 주소·부동산 객체 연결, 원자료 근거, 실제 아파트 전체 흐름 평가가 1단계의 남은 우선 작업이다.
  모바일 앱·Marketplace·자동 개인화·실제 거래 당사자 연결은 후속 계획이다.

---

## 9. 작업 이력 — 지금 구조가 된 이유

새로 합류한 사람이 "왜 이렇게 복잡한가"를 되묻지 않도록 남긴다. **각 항목은 위 2·3절의
어느 규칙이 왜 생겼는지**를 가리킨다.

### 초기 → 현재

1. **n8n 워크플로 프로토타입**으로 가설을 검증한 뒤, 분기·재시도·상태 관리가 노드 그래프에서
   감당이 안 되어 **LangGraph 파이프라인 4종**으로 재작성했다.
2. 인증을 붙이면서 **SQLite** 로 시작 → 멀티 워커 배포를 전제하자 상태 공유가 깨져
   **PostgreSQL + Redis 로 전면 이전**했다 (2-1).
3. 실서비스 준비 점검을 하며 보안·운영 항목을 순차 처리: 시크릿 분리(2-4) → 백업 스크립트 →
   멀티 워커(3-2) → 운영/개발 compose 분리 → Sentry → Alembic(2-2).
4. 계정 관리로 **비밀번호 재설정 + 세션 무효화**(2-7), 외부 도메인 배포를 위해
   **프록시 헤더**(2-5) 와 **쿠키 SameSite**(2-8) 를 정리했다.
5. 2026-10-01, **사용자 매물의 의사결정 지원**을 첫 개발 범위로 확정했다. 취득 후 주택 수와
   비상자금 적용을 통일하고 후보별 저장 조건을 유지했다(2-12). 미확인 자료가 검토 완료로 보이지 않도록
   다섯 판단 축의 공통 계약을 도입해 후보 비교와 매수 검토 요약에 함께 적용했다(2-11).
   기존 매물·케이스 모델을 재사용하고, 모바일 앱 개발은 후속 단계로 남겼다.

### 실제로 잡은 결함 (전부 재현 → 수정 → 검증 순으로 처리)

| 결함 | 어떻게 확인했나 | 규칙 |
|---|---|---|
| IDOR — 남의 이력 전량 조회 가능 | 수정을 되돌려 테스트가 실패하는지 확인 | 2-3 |
| 멀티 워커 `create_all` 경합 | 4워커 기동 시 3개 사망을 3회 재현, 수정 후 5회 검증 | 3-2 |
| 레이트 리밋 XFF 위조 우회 | 3조건 대조 실험 (201 / 429 / 429) | 2-5 |
| 프론트 무한 폴링 | Node 로 4시나리오 검증 후 `AbortController` + 데드라인 도입 | — |
| Alembic 이 RAG 테이블을 drop | 마이그레이션 파일 육안 검토 중 발견 | 2-2 |
| SSR 빈 셸 회귀 (**작업 중 스스로 만든 것**) | 서버 응답 HTML 바이트 수 실측 (20,592 → 16,503) | 3-4 |

### 검증 원칙

이 저장소에서 "고쳤다"는 **재현 → 수정 → 재현 안 됨 확인**까지 끝난 상태를 말한다.
2·3절 수치가 전부 실측인 것도 같은 이유다. 추측을 사실처럼 적지 말 것 — 특히
포트폴리오·이력서용 문서를 만들 때 위 수치를 각색하면 그대로 거짓이 된다.

### 포트폴리오와 외부 참고 자료

포트폴리오 HTML은 사용자 요청에 따라 `docs/portfolio/`에서 원본·이미지·생성기·산출물을 함께 관리한다.
수정·생성 방법은 `docs/portfolio/README.md`를 따른다. `index.html` 직접 수정 대신 `src/`를 수정하고 재생성한다.
기존 바탕화면 문서(`부동산컨시어지_포트폴리오.md`, `포트폴리오_Gamma_프롬프트.md`)는 별도 참고 자료다.

> ⚠️ **`sh scripts/compose.sh dev config` 출력에는 실제 API 키가 그대로 찍힌다.** 로그·이슈·스크린샷에
> 붙여넣지 말 것. 과거 세션 로그에 노출된 적이 있어 해당 키들은 교체 대상이다.
