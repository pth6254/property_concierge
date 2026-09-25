# 에이전트 작업 지침 — 부동산 컨시어지

> 이 파일은 Claude Code · Codex 등 **모든 코딩 에이전트가 공유하는 단일 원본**이다.
> `CLAUDE.md` 는 이 파일을 `@AGENTS.md` 로 임포트만 한다 — 내용을 양쪽에 복제하지 말 것.
> 사람이 읽는 셋업·기능 설명은 `README.md` 에 있다. 여기에는 **코드를 고칠 때 알아야 할
> 제약과 함정**만 적는다.

---

## 1. 프로젝트 한눈에

자연어/단계별 입력 → 국토부 실거래가 기반 **AI 시세추정(AVM)** 리포트를 생성하고,
매물추천 · 투자시뮬레이션 · 매물비교 · 권리관계 점검 · 법률세금 챗봇을 제공한다.

```
Next.js 16 (App Router) :3000
   │ REST · JWT 쿠키
FastAPI :8000  (uvicorn --workers 4)
   ├── api/          라우터 · 인증 · Redis Stream 작업 큐/별도 실행기
   ├── backend/      LangGraph 파이프라인 4종 + 도메인 로직
   ├── db/           SQLAlchemy 모델 13종 + Alembic + Redis 클라이언트
   └── schemas/      Pydantic 스키마 (단위: 원 · ㎡)
        │
PostgreSQL(+pgvector) · Redis
```

시세추정은 `주거 / 상업 / 업무 / 산업 / 토지` **5개 유형별 에이전트**로 조건부 분기한다
(`backend/graphs/appraisal_graph.py` 의 `CATEGORY_TO_AGENT`). 신규 유형은 이 매핑에
에이전트를 추가하면 된다.

---

## 2. 절대 되돌리면 안 되는 결정

아래는 모두 **문제를 겪고 내린 결정**이다. "단순화"하려다 되돌리기 쉬우니 주의할 것.

### 2-1. SQLite · 인프로세스 메모리 폴백을 두지 않는다

`DATABASE_URL` / `REDIS_URL` 이 없으면 **기동을 막는다**(`db/base.py`, `db/redis_client.py`).
"로컬은 SQLite, 운영은 Postgres"로 갈라지면 로컬에서 검증되지 않은 쿼리가 운영에서만
깨진다. 로컬 개발도 `docker compose up -d pgvector redis` 를 전제로 한다.

작업 큐 · 레이트 리밋 · 로그인 잠금 상태도 **전부 Redis**다. 프로세스 메모리로 되돌리면
멀티 워커에서 상태가 갈려 다음이 조용히 깨진다:
- 워커 A가 만든 job을 워커 B가 못 찾음 → 폴링 404
- 레이트 리밋 · 로그인 잠금 한도가 워커 수만큼 실질 증가 → 브루트포스 방어 무력화

### 2-2. Alembic 은 워커 기동 "전에" 단일 프로세스로 실행한다

`Dockerfile.backend` 의 `CMD` 가 `alembic upgrade head && uvicorn ... --workers N` 인 것은
의도된 순서다. 스키마를 먼저 확정해야 여러 워커가 동시에 DDL을 치는 경합이 아예 생기지 않는다.

`db/base.py` 의 `init_db()`(create_all)는 alembic 없이 `uvicorn` 을 직접 띄우는
로컬·테스트 경로용 **안전망**이다. 지우지 말 것. 단, create_all 은 컬럼 삭제·타입 변경을
반영하지 못하므로 그런 변경은 반드시 마이그레이션을 만들어야 한다.

```bash
alembic revision --autogenerate -m "설명"   # 생성 후 파일을 반드시 검토
alembic upgrade head
```

**autogenerate 결과에서 아래 세 테이블의 `drop_table` 은 반드시 지울 것:**
`real_estate_docs` · `langchain_pg_collection` · `langchain_pg_embedding`

이 셋은 `docker/init.sql` 이 만드는 RAG 벡터스토어 테이블로 `db/models.py` 에 없다.
autogenerate 는 모델에 없으면 "삭제된 것"으로 간주해 **매번 drop 구문을 끼워 넣는다.**
그대로 적용하면 RAG 데이터가 전부 사라진다 (실제로 겪어서 `b7e42562ca36` 에서 제거함).

### 2-3. 소유자 검증 없이 레코드를 조회하지 않는다

`history` · `activity` 의 id는 순차 정수다. 사용자 요청 경로에서 소유자 필터 없이 조회하면
id를 훑어 타인 데이터를 전량 읽을 수 있다(실제로 있었던 취약점).

- 조회 함수에 `user_id` 를 넘긴다 (`history_db.load_one(record_id, user_id=...)`)
- 타인 레코드는 403이 아니라 **404** — 403은 "그 id에 무언가 있다"를 노출한다
- 회귀 테스트: `tests/test_access_control.py` (이 파일을 지우거나 약화시키지 말 것)

### 2-4. 시크릿을 저장소에 넣지 않는다

`docker-compose.yml` 은 `${POSTGRES_PASSWORD:?...}` 로 **미설정 시 기동 실패**하게 되어 있다.
편의를 위해 기본값을 넣으면 그 값이 그대로 운영에 올라간다.

`.github/workflows/ci.yml` 의 postgres 비밀번호는 예외다 — 워크플로 실행 중에만 존재하는
휘발성 컨테이너라 유출 리스크가 없다(주석에 명시되어 있음).

### 2-5. 리버스 프록시 뒤에 배포하면 FORWARDED_ALLOW_IPS 를 반드시 지정한다

레이트 리밋(`slowapi`)과 로그인 잠금이 **클라이언트 IP 기준**인데, 프록시를 거치면
FastAPI 에는 모든 요청이 프록시 IP 하나로 들어온다. 실제 IP 는 `X-Forwarded-For` 에 있다.

uvicorn 은 `proxy_headers=True` 가 기본이지만 `forwarded_allow_ips` 기본값이
`"127.0.0.1"` 이라 **같은 기계의 프록시만** 신뢰한다. docker compose 처럼 프록시가
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

`backend/opinion_guard.py` 는 LLM 출력에서 **컨텍스트로 주입한 수치 외의 숫자가 든 문장을
자동 삭제**한다. 부동산 가격에서 환각은 치명적이라 프롬프트 부탁이 아니라 출력 검증으로
막는다. 위반 시 1회 재생성 → 결정론적 폴백.

### 2-7. 비밀번호가 바뀌면 기존 JWT 를 전부 무효화한다

JWT 는 stateless 라 발급 후에는 서버가 취소할 방법이 원래 없다. 그래서 "비밀번호를 바꿨는데
탈취당한 세션이 만료(14일)까지 살아 있는" 상태가 된다 — 재설정 기능의 목적 자체가 무너진다.

세션 테이블을 만드는 대신 **버전 클레임**으로 해결했다:

- `users.password_changed_at` (ISO8601 문자열) 을 비밀번호 변경 시 갱신
- 토큰 발급 시 그 값을 `pwd_at` 클레임으로 심는다 (`api/auth_utils.py` 의 `create_jwt`)
- 요청마다 `is_session_valid(payload, user)` 로 대조 → 불일치면 401
  (`api/deps.py` 의 `get_current_user` · `get_optional_user` **양쪽 모두**)

`get_optional_user` 를 빼먹으면 비로그인도 되는 경로에서 옛 토큰이 계속 통한다. 둘 다 고칠 것.
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
  은 브라우저가 무시하기 때문 (`api/routes/auth.py` 의 `_COOKIE_SECURE`).
- 오타는 **기동 시점에 RuntimeError** 로 죽인다. 런타임에 잘못된 값이 조용히 나가면
  증상만 보고는 절대 못 찾는다.
- **로그아웃 시 삭제 쿠키도 같은 속성으로 내려야 한다.** 속성이 다르면 브라우저가 다른
  쿠키로 보고 지우지 않는다 (`_clear_cookie`).

회귀 테스트: `tests/test_cookie_config.py` (환경변수 → 실제 `Set-Cookie` 헤더 매핑까지 고정).

### 2-9. 오래 걸리는 작업은 별도 실행기에서 처리한다

API의 AVM·수집·채팅 경로는 `api/jobs.py`의 `create_task()`로 JSON 입력을 Redis Stream에
기록한다. `api/job_worker.py`가 별도 컨테이너에서 실행한다. API 내부 스레드 실행으로
되돌리면 서버 재시작 때 진행 중 작업이 사라진다. 운영 Redis의 AOF 설정과
`job-worker` 서비스도 함께 유지할 것. AVM 이력·수집 기록은 `job_id`로 중복 저장을 막는다.

실행 도중 죽은 채팅·종합 컨시어지 작업은 대화 중복을 피하려고 자동 재실행하지 않고
사용자 재질문을 안내한다. 정확한 경계는 `docs/job-recovery.md`를 따른다.

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
(`db/base.py` 의 `init_db()` 참고).

### 3-3. Next.js 16 · React 19

- **`middleware.ts` 가 아니라 `proxy.ts`** 다. Next 16에서 이름이 바뀌었다(`src/proxy.ts`).
- `frontend/AGENTS.md` 의 경고대로, 코드 작성 전 `frontend/node_modules/next/dist/docs/` 를
  확인할 것. 학습 데이터와 다르다.
- **effect 안에서 동기 `setState` 금지** (`react-hooks/set-state-in-effect`). CI 린트가 잡는다.
  - sessionStorage 읽기는 반드시 `frontend/src/lib/sessionStore.ts` 의
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
docker compose up -d pgvector redis          # DB·캐시 먼저

DISABLE_RATE_LIMIT=1 APP_ENV=development \
JWT_SECRET_KEY=dev-secret \
DATABASE_URL="postgresql://postgres:<pw>@localhost:5432/real_estate_db" \
REDIS_URL="redis://localhost:6379/0" \
./venv-wsl/bin/python -m pytest tests/ -q    # 전체 테스트 (격리 DB에서 934개 통과, 2026-09-24)

alembic upgrade head                          # 마이그레이션 적용

# ── 프론트엔드 ──────────────────────────────────────────
cd frontend
npx tsc --noEmit    # 타입 체크
npm run lint        # ESLint (set-state-in-effect 등)
npm run build       # 프로덕션 빌드

# ── 전체 실행 ───────────────────────────────────────────
docker compose up --build                     # 개발 (override 자동 병합)
docker compose -f docker-compose.yml up -d --build   # 운영 (override 배제)

# ── 백업 ────────────────────────────────────────────────
./scripts/backup_db.sh
./scripts/restore_db.sh backups/property_concierge_<타임스탬프>.dump
```

**CI**(`.github/workflows/ci.yml`)는 두 job을 병렬 실행한다:
- `test` — PostgreSQL·Redis 서비스 컨테이너 + `alembic upgrade head` + `pytest`
- `frontend` — `tsc --noEmit` + `npm run lint` + `npm run build`

**변경 후에는 양쪽을 모두 돌려볼 것.** 백엔드만 고쳤다고 프론트가 안전한 게 아니다
(API 응답 형태가 바뀌면 `frontend/src/lib/api.ts` 의 타입도 함께 고쳐야 한다).

---

## 6. 코드 컨벤션

- **주석·문서는 한국어.** 기존 코드 톤을 따를 것.
- **주석은 "무엇"이 아니라 "왜"를 적는다.** 특히 되돌리기 쉬운 결정에는 이유를 남긴다.
- 프론트엔드에 `any` · `@ts-ignore` 를 쓰지 않는다 (현재 0건).
- 금액 단위는 **원(int)**, 면적은 **㎡(float)**.
  예외: `backend/models.py` 의 `ValuationResult` 는 만원 단위 — 리포트 생성 시 변환한다.
- 파일명은 구체적으로. `report.py` · `utils.py` 같은 흔한 이름은 외부 패키지와 충돌한다
  (실제로 겪어서 `appraisal_report.py` 로 바꾼 이력이 있음).

---

## 7. 제품상 알아둘 것

기능을 고칠 때 **사실과 다르게 말하지 않도록** 알아둬야 하는 것들.

- **기본 매물추천 · 비교 · 시뮬레이션의 매물 데이터는 개발용 가상 데이터**
  (`data/sample_listings.csv`, 43건). 사용자 제공 매물은 별도 저장소에 보관하며 출처·확인 시각을 표시한다. 실호가를 서비스가 독립 검증한 것은 아니다.
  반면 **시세추정은 국토부 실거래가 실데이터**를 쓴다.
- **AVM 신뢰도 편차가 크다.** 백테스트(서초구 434건) 실측 기준 동일 단지 매칭은
  ±10% 적중률 69~84%지만 **동일동·구 매칭은 8~33%** 다.
  신뢰도는 이 실측치를 블렌딩해 하향 보정된다(`backend/confidence.py`).
- **시점수정은 주거용·토지만** 부동산원 R-ONE 지수를 적용한다. 상업·업무·산업용은
  적합한 월간 시군구 지수가 없어 근사 변동률을 쓴다.
- **의도분석의 `clarification_question` 은 사용자에게 노출되지 않는다.**
  내부 재분석 루프(최대 2회)에만 쓰이고, 그래도 부족하면 오류로 끝난다.
  "사용자에게 보완 질문을 던진다"고 설명하면 사실과 다르다.
- 시세추정은 **AVM 기반 참고용 분석**이며 「감정평가 및 감정평가사에 관한 법률」에 따른
  감정평가가 아니다. UI·문서에서 이 고지를 빼지 말 것.
- **비밀번호 재설정 메일은 아직 실제로 발송되지 않는다.** `RESEND_API_KEY` 가 비어 있으면
  `api/email_service.py` 가 **서버 로그에 재설정 링크를 출력**한다(의도적 폴백 — 로컬·CI가
  외부 메일 서비스에 의존하지 않게 함). 실발송하려면 Resend 계정 + 도메인 인증(SPF/DKIM)이
  필요하고 아직 하지 않았다. "메일이 나간다"고 설명하면 사실과 다르다.
- **재설정 요청 응답은 계정 존재 여부와 무관하게 항상 동일하다**(`_RESET_GENERIC_RESPONSE`).
  가입 여부를 알려주면 계정 열거(account enumeration)가 된다. "없는 메일입니다" 같은
  친절한 안내로 바꾸지 말 것.

---

## 8. 현재 알려진 부채

**코드 쪽**
- **프론트엔드 단위 테스트 0건.** CI는 타입체크·린트·빌드와 매물 등록→후보→변경 재검토→재선택의 브라우저 흐름 1종을 검증한다.
- 프리필 흐름(홈 → `/appraisal`, 추천 → `/simulation`)의 **런타임 동작은 브라우저로 검증되지
  않았다.** 타입·빌드·SSR만 확인된 상태다.

**운영 쪽 (배포 전에 해야 하는 것)**
- **TLS·리버스 프록시 없음.** 컨테이너를 붙이고 `FORWARDED_ALLOW_IPS` 를 지정해야 한다(2-5).
- **Resend 도메인 인증 미완료** — 위 7절 참고. 그 전까지 재설정은 운영자가 로그의 링크를
  수동 전달하는 방식으로만 가능하다.
- **Google OAuth 리다이렉트 URI 가 localhost 로만 등록**되어 있다. 실도메인 등록 필요.
- **국토부 API 지역 시딩은 서울 25개 구 매매 거래에 적용했다.** 매물 원문은 정기 수집하지 않는다. 실거래 배치 갱신은 `transaction-refresh` 유지보수 프로필을 활성화해야 시작된다.

**제품 쪽**
- 매물 데이터 제휴 없이는 추천·비교가 데모 수준을 벗어나기 어렵다.

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

### 저장소 밖 산출물

포트폴리오 HTML은 사용자 요청에 따라 `docs/portfolio/`에서 원본·이미지·생성기·산출물을 함께 관리한다.
수정·생성 방법은 `docs/portfolio/README.md`를 따른다. `index.html` 직접 수정 대신 `src/`를 수정하고 재생성한다.
기존 바탕화면 문서(`부동산컨시어지_포트폴리오.md`, `포트폴리오_Gamma_프롬프트.md`)는 별도 참고 자료다.

> ⚠️ **`docker compose config` 출력에는 실제 API 키가 그대로 찍힌다.** 로그·이슈·스크린샷에
> 붙여넣지 말 것. 과거 세션 로그에 노출된 적이 있어 해당 키들은 교체 대상이다.
