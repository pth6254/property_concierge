# Property Concierge — 부동산 AI 시세추정 · 매물 추천 · 투자 시뮬레이션 종합 컨시어지

포트폴리오: [HTML](docs/portfolio/index.html) · [원본 수정·생성·검증 안내](docs/portfolio/README.md)

AI 기반 부동산 종합 분석 서비스. 자연어 입력으로 국토부 실거래가 데이터와 LLM 추론을 결합한
**AI 시세추정(AVM, Automated Valuation Model) 리포트**를 생성하고,
조건 기반 매물 추천 · 투자 수익성 시뮬레이션 · 매물 비교를 제공한다.

> ⚖️ **법적 고지**: 본 서비스의 시세추정은 자동가치산정(AVM) 기반 **참고용 분석**이며,
> 「감정평가 및 감정평가사에 관한 법률」에 따른 감정평가가 아니다.
> 담보·소송·과세 등 법적 효력이 필요한 가치 판단은 감정평가사에게 의뢰해야 한다.

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **매수 검토 케이스** | 매수 목표·예산·관심 지역·후보를 묶고 시세·자금·권리 분석과 체크리스트를 관리하며, 후보 2~4개를 비교해 최종 후보와 선택 근거를 저장. 시세 30일·자금 14일·권리 7일이 지나면 갱신 필요로 표시 |
| **후보별 다음 행동** | 예산·권리 위험, 희망가 누락, 분석 누락·실패·만료, 미완료 체크리스트를 규칙으로 안내하고 해당 분석·검토 화면으로 연결. 희망가를 수정할 수 있으며 기존 자금분석의 매수가와 다르면 재확인을 안내. 제외 후보는 안내에서 제외하며 검토 항목 완료가 매수 안전성을 의미하지 않음 |
| **거래 실행 계획** | 최종 후보 선택 후 계약 전·잔금 전·잔금일·거래 후의 기본 작업 18개를 자동 생성. 계약·잔금 예정일 기준 권장일, 기한 경과·문제·외부 대기와 준비도를 표시하고 실제 확인자·결과·근거·후속 조치를 같은 케이스에 기록 |
| **동네·단지 탐색** | 전국 행정구역 코드 구조에서 수집된 서울 실거래를 중앙값·분위수·예산 적합률·표본 신뢰도로 비교하고, 관심 지역과 아파트 단지 후보를 케이스에 저장 |
| 🏡 **컨시어지 홈** | 사용자 여정(매물 탐색 → 가치 분석 → 안전 점검 → 법률·세금 상담) 기반 홈 화면. 주소 검색 히어로에서 바로 시세추정으로 연결, 시세추정·권리점검·상담을 합친 최근 활동 피드 |
| 🏠 **AI 시세추정** | 자연어/단계별 입력 → 실거래 비교·수익환원·원가법 기반 추정 시세 산출, 공식 문서 형식 리포트 |
| 📊 **리포트 영속화** | 결과가 이력 DB에 저장되어 `/report/{id}` URL로 재열람·공유·인쇄(PDF) 가능 |
| ⏱ **비동기 작업 큐** | 30초~2분 걸리는 파이프라인을 job으로 실행, 단계별 진행 상황 실시간 표시. 상태는 Redis에 저장돼 멀티 워커에서도 어느 워커가 폴링을 받든 동일한 진행 상황을 본다 |
| ✨ **매물 추천** | **실거래 기반 단지 추천 (전국 시군구)** — 예산·면적 조건으로 실거래 데이터를 집계·점수화. 샘플 매물 모드 병행 |
| 📈 **투자 시뮬레이션** | 취득세·대출 상환·현금흐름·3개 시나리오(기준/강세/약세) 수익률 계산 |
| ⚖️ **매물 비교** | 복수 매물 점수 비교 + 우승 매물 선정 결정 리포트 |
| 🔍 **권리관계 위험 점검** | 등기부등본·건축물대장 **PDF 업로드** → 가압류·신탁·근저당 검출, 깡통전세 위험도(경매 배당 시뮬레이션), 소액임차인 최우선변제 판정 |
| 💬 **법률·세금 AI 안내** | RAG(법령·분쟁사례) + 세금 계산기 도구 호출(증여·상속·양도·보유세) 챗봇 — 수치 가드레일로 계산기 값만 인용, `tools/build_law_corpus.py`로 법령·판례 코퍼스 확장 |
| 📋 **이력 대시보드** | 사용자별 시세추정 이력 검색·통계 차트·리포트 재열람 |
| 🔐 **인증·보안** | 이메일/비밀번호 + Google OAuth, JWT 쿠키 세션, 사용자별 이력 분리, 회원 탈퇴(전체 삭제), 로그인 잠금(5회 실패), 엔드포인트별 레이트 리밋, 챗봇 일일 상한, 비밀번호 재설정(계정 열거 방지) + 재설정 시 기존 세션 전부 무효화, 배포 형태별 쿠키 `SameSite` 설정 |
| 🔒 **개인정보 보호** | 업로드 PDF는 메모리에서만 분석 후 즉시 파기(무저장), 활동 기록은 주소 마스킹·질문 축약 저장, 개인정보처리방침·이용약관 페이지(`/privacy`·`/terms`) |
| 🗄 **실거래가 로컬 스토어** | MOLIT API 응답을 PostgreSQL에 적재 — 반복 조회 시 API 호출 없이 즉시 응답, 배치 수집 CLI 제공 |

---

## 아키텍처 개요

```
[Next.js 16 프론트엔드 :3000]
         │  HTTP (REST) · JWT 쿠키
[FastAPI 백엔드 :8000]  (uvicorn --workers N 스케일아웃 가능)
   ├── 작업 큐 (api/jobs.py — Redis Stream 입력·상태, 별도 api.job_worker 실행)
   ├── 레이트 리밋 · 로그인 잠금 (Redis — 워커 간 카운터 공유)
   ├── 인증 / 이력 / 활동 피드 (api/auth_db.py, history_db.py, activity_db.py
   │                          — SQLAlchemy ORM, db/ 공용 세션)
   ├── 비밀번호 재설정 메일 (api/email_service.py — Resend, 키 없으면 서버 로그 폴백)
   │
[LangGraph 파이프라인 (backend/)]
   ├── 캐시·지역코드 (backend/cache_db.py)         │  PostgreSQL
   ├── 실거래가 로컬 스토어 (backend/transaction_store.py)  │  (real_estate_db,
   ├── 법률·세금 상담 코퍼스 (backend/chat_corpus.py)       │   pgvector 공유)
   │        ↑ 미스 시 폴백           ↑ 배치 수집
   ├── 국토부 MOLIT API      backend/tools/ingest_transactions.py
   ├── 결정론적 지오코딩 (카카오 주소·좌표 → 건축물대장 주용도 → 검증된 장소 규칙)
   ├── Vworld 용도지역·공시지가 보강 (선택, 조회 결과가 없을 수 있음)
   └── LLM (Ollama Qwen3.5 9B / OpenAI / Anthropic — 자연어 후보 추출·분석 의견)
```

- **프론트엔드**: Next.js 16 (App Router, TypeScript, Tailwind v4) — 딥 그린 브랜드 디자인 토큰,
  Pretendard 가변 폰트(`next/font/local` 셀프호스팅), lucide-react 아이콘, 모바일 반응형 내비게이션
- **백엔드 API**: FastAPI (`api/`) — uvicorn 실행, 비동기 job + 동기 엔드포인트 병행
- **파이프라인**: LangGraph (`backend/`) — 시세추정·추천·시뮬레이션·비교 4개 그래프
- **저장소**: PostgreSQL 단일 인스턴스(`real_estate_db`) — 앱 테이블(사용자·이력·활동·캐시·
  지역코드·실거래가·상담 코퍼스, `db/models.py`)과 RAG 벡터스토어(pgvector, `real_estate_docs`)가
  같은 컨테이너를 공유 + Redis(작업 큐 상태·레이트 리밋·로그인 잠금 카운터)
  — 둘 다 로컬 개발 포함 필수 (SQLite/인프로세스 메모리 폴백 없음, `docker compose up pgvector redis`)

### 시세추정 실행 흐름 (비동기 job)

```
POST /api/appraisal/jobs               → { job_id } 즉시 반환
  └─ 백그라운드: LangGraph 파이프라인 실행
GET  /api/appraisal/jobs/{job_id}      → { status, step, ... }  (프론트 2초 폴링)
  └─ 완료 시: history DB 저장 → { status: done, history_id, result }
프론트 → /report/{history_id}          → 영속 리포트 (새로고침·공유 가능)
```

---

## 빠른 시작 (Docker Compose)

```bash
# 1. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 API 키 + POSTGRES_PASSWORD 입력 (예: openssl rand -base64 32)

# 2. 전체 서비스 실행 (백엔드 + 프론트엔드 + PostgreSQL + Redis)
docker compose up --build

# 서비스 주소
# 프론트엔드: http://localhost:3000
# 백엔드 API: http://localhost:8000
# API 문서:   http://localhost:8000/docs
```

`-f` 없이 실행하면 Compose가 `docker-compose.yml`(운영 기준 베이스)과
`docker-compose.override.yml`(로컬 편의: 소스 핫리로드·PostgreSQL/Redis 포트 호스트
노출)을 자동 병합한다. 위 명령이 바로 그 상태 — 로컬 개발에서 쓰는 명령이다.

**운영 배포**는 override를 명시적으로 배제한다:

```bash
docker compose -f docker-compose.yml up -d --build
```

베이스 파일만 쓰면 소스는 이미지에 구운 것만 실행되고(볼륨 마운트 없음),
PostgreSQL·Redis 포트는 호스트에 노출되지 않는다(도커 내부 네트워크로만 통신).
`scripts/backup_db.sh`·`restore_db.sh`는 호스트 포트가 아니라 `docker exec`로
컨테이너 내부에 접속하므로 이 차이와 무관하게 그대로 동작한다.

### 로컬 개발 (백엔드만 네이티브 실행)

앱 테이블(사용자·이력·활동·캐시·실거래가·상담 코퍼스)이 PostgreSQL, 작업 큐·레이트
리밋·로그인 잠금이 Redis 필수라 — SQLite나 인프로세스 메모리로 도망칠 폴백이 없다.
**Postgres·Redis는 항상 Docker로 띄우고, FastAPI만 네이티브로 돌리는 것**이 기본 흐름이다.

```bash
# 1. DB·캐시만 Docker로 기동 (백엔드는 아래에서 네이티브로 띄울 것이므로 제외)
docker compose up -d pgvector redis

# 2. Python 패키지 설치
pip install -r requirements.txt

# 3. Ollama 모델 다운로드 (시세추정 LLM 의견 생성에 필요)
ollama pull qwen3.5:9b
ollama pull nomic-embed-text

# 4. 환경변수 설정 (.env 에 DATABASE_URL·REDIS_URL 이 로컬 포트를 가리키는지 확인)
cp .env.example .env

# 5. FastAPI 백엔드 실행
uvicorn api.main:app --reload --port 8000

# 6. Next.js 프론트엔드 실행 (별도 터미널)
cd frontend
npm install
npm run dev
# http://localhost:3000
```

### 실거래가 배치 수집 (선택 — 응답 속도 대폭 개선)

시세추정은 로컬 스토어를 우선 조회하고, 미스 시에만 MOLIT API를 호출한 뒤 자동 적재한다(write-through).
자주 조회하는 지역을 미리 수집해두면 API 호출 없이 즉시 응답한다.

```bash
# 서초구·강남구 주거용 최근 12개월
python backend/tools/ingest_transactions.py --regions 서초구,강남구 --months 12

# 서울특별시의 모든 자치구, 현재월 포함 최근 12개월 매매 원천 전체
python backend/tools/ingest_transactions.py --sido 서울특별시 --months 12 --yes

# 기존 범위보다 이전·이후 월을 증분 수집 (완료된 월은 자동으로 건너뜀)
python backend/tools/ingest_transactions.py --sido 서울특별시 --from 202401 --to 202508 --yes

# 등록된 전체 지역(수도권+광역시 약 60개), 주거용+상업용 6개월
python backend/tools/ingest_transactions.py --all --categories 주거용,상업용

# 강제 재수집 / 스토어 현황 확인
python backend/tools/ingest_transactions.py --regions 서초구 --force
python backend/transaction_store.py
```

배치는 `지역 × API 원천 × 거래월`의 완료 이력을 기준으로 증분 실행한다. 완료된 과거 월은
다시 호출하지 않고 실패·중단된 월만 재시도한다. 신고·해제·정정이 계속 유입되는 당월과
전월은 TTL이 지난 경우 해당 월 전체 스냅샷을 다시 받아 트랜잭션으로 교체하므로 중복 적재 없이
최신 상태를 유지한다. `--force`를 지정한 경우에만 완료된 범위를 강제로 다시 수집한다.

> 공공데이터포털 개발계정은 일일 트래픽 제한(보통 1,000건)이 있다.
> 실행 전 출력되는 예상 호출 수(지역 × 엔드포인트 × 월)를 확인할 것.

**신선도(TTL) 정책**: 완결 월(기준 2개월 이전)은 30일, 최근 월(당월·전월)은 12시간 후 재수집
— 실거래 신고 기한(30일) 내 데이터 유입을 반영한다.

### 전국 법정동코드 동기화

동네 탐색은 이름이 기본키인 기존 `region_codes`가 아니라 행정안전부 10자리
법정동코드를 사용하는 `legal_regions` 계층 마스터를 기준으로 한다. 시도부터
법정리까지 현행 전체를 가져오며, 전체 조회가 성공한 경우에만 DB를 갱신한다.

```bash
# 공식 API 조회·계층 검증만 수행
python backend/tools/sync_legal_regions.py --dry-run

# legal_regions 테이블에 업서트
python backend/tools/sync_legal_regions.py
```

`MOIS_REGION_API_KEY`가 있으면 우선 사용하고, 없으면 data.go.kr 공용 키인
`MOLIT_API_KEY`를 사용한다. 목록 API는 공식 폐지일을 제공하지 않으므로 이전
동기화에 있던 코드가 새 전체 목록에서 사라지면 비활성화만 하고 폐지일을 추정해
채우지 않는다.

---

## 폴더 구조

```
property_concierge/
│
├── db/                              공용 PostgreSQL 데이터 계층 (SQLAlchemy)
│   ├── base.py                     엔진·세션 (DATABASE_URL, 지연 생성)
│   ├── models.py                   ORM 모델 13종 (User/HistoryRecord/PurchaseCase/CaseProperty/CaseRegion/...)
│   ├── redis_client.py             Redis 커넥션 팩토리 (REDIS_URL)
│   └── migrations/                 Alembic 마이그레이션 (env.py + versions/)
├── alembic.ini                      Alembic 설정 (접속 문자열은 DATABASE_URL 환경변수로)
│
├── scripts/
│   ├── backup_db.sh                 PostgreSQL 논리 백업 (pg_dump)
│   └── restore_db.sh                백업 복원 (pg_restore, 확인 프롬프트 있음)
│
├── api/                            FastAPI 진입점 & 라우터
│   ├── main.py                     FastAPI 앱 설정, CORS, 라우터 등록
│   ├── jobs.py                     작업 큐 (상태: Redis, 실행: 인프로세스 스레드)
│   ├── auth_db.py                  사용자 인증 (db/ 공용 세션)
│   ├── auth_utils.py               JWT 발급·검증 (비밀번호 변경 시각을 클레임에 심어 세션 무효화)
│   ├── email_service.py            비밀번호 재설정 메일 발송 (Resend, 키 없으면 로그 출력 폴백)
│   ├── deps.py                     인증 의존성 (get_current_user / get_optional_user — 둘 다 세션 유효성 검사)
│   ├── history_db.py               시세추정 이력 (db/ 공용 세션, 리포트 영속화)
│   ├── activity_db.py              권리점검·상담 활동 (db/ 공용 세션, 홈 통합 피드 데이터 소스)
│   └── routes/
│       ├── appraisal.py            POST /api/appraisal (동기) · /api/appraisal/jobs (비동기)
│       ├── auth.py                 회원가입 / 로그인 / Google OAuth / me / logout
│       ├── recommendation.py       POST /api/recommendation
│       ├── simulation.py           POST /api/simulation
│       ├── comparison.py           POST /api/comparison
│       ├── history.py              GET/DELETE /api/history, GET /api/history/{id}
│       ├── activity.py             GET /api/activity (시세추정+권리점검+상담 통합 피드)
│       ├── rights.py               POST /api/rights/analyze (등기부·건축물대장 PDF 권리 점검)
│       ├── chat.py                 POST /api/chat (법률·세금 AI 안내 챗봇)
│       └── address.py              GET /api/address/search
│
├── frontend/                       Next.js 16 (App Router, TypeScript, Tailwind v4)
│   ├── src/app/
│   │   ├── page.tsx                홈 — 컨시어지 데스크(주소 검색) + 여정 4단계 서비스 + 통합 활동 피드
│   │   ├── appraisal/page.tsx      시세추정 입력 (3단계 폼 + 진행 단계 표시)
│   │   ├── report/page.tsx         방금 실행한 결과 (sessionStorage)
│   │   ├── report/[id]/page.tsx    저장된 리포트 재열람 (영속 URL)
│   │   ├── dashboard/page.tsx      이력 대시보드 (검색·차트·리포트 링크)
│   │   ├── recommendation/page.tsx 매물 추천
│   │   ├── simulation/page.tsx     투자 시뮬레이션
│   │   ├── comparison/page.tsx     매물 비교
│   │   ├── rights/page.tsx         권리관계 위험 점검 (PDF 업로드 → 위험도 리포트)
│   │   ├── chat/page.tsx           법률·세금 AI 안내 챗봇
│   │   ├── login/ · register/      인증 페이지
│   │   ├── fonts/                  Pretendard 가변 폰트 (셀프호스팅)
│   │   └── api/auth/               Next.js API 라우트 (인증 프록시)
│   ├── src/components/
│   │   ├── AppraisalReport.tsx     시세추정 리포트 문서 렌더러 (공용, 인쇄 지원)
│   │   └── Navbar.tsx              사이드바 내비게이션 (분석/안전·상담/내 기록 그룹, 모바일 드로어)
│   └── src/lib/
│       ├── api.ts                  API 클라이언트 (job 폴링 포함)
│       ├── auth.tsx                인증 컨텍스트
│       └── types.ts                TypeScript 타입 정의
│
├── backend/                        비즈니스 로직 + LangGraph 파이프라인
│   ├── router.py                   공개 API — run_appraisal(progress_cb 지원) 외 3종
│   ├── state.py                    LangGraph 공유 상태 (AgentState)
│   ├── intent_agent.py             자연어 → PropertyIntent 구조화
│   ├── geocoding.py                자연어 후보 → 공식 주소·좌표·유형 (카카오+건축물대장+규칙)
│   ├── agents.py                   5개 유형별 가치 분석 에이전트
│   ├── price_engine.py             가격 계산 엔진 (로컬 스토어 우선 → MOLIT API 폴백)
│   ├── transaction_store.py        실거래가 로컬 스토어 (PostgreSQL, TTL 기반)
│   ├── appraisal_report.py         시세추정 마크다운 리포트 노드
│   ├── deep_analysis.py            심층 분석 노드
│   ├── rag_pipeline.py             RAG 검색 파이프라인
│   ├── chat_corpus.py              법률·세금 상담 RAG 코퍼스 (시드 청크 + 임베딩 검색, PostgreSQL chat_chunks)
│   ├── tax_rules.py                세금·규제 법령 테이블 (증여·상속·양도·보유세, 기준일 명시)
│   ├── llm_utils.py                LLM 의견 생성 (수치 창작 금지 가드레일)
│   ├── model_factory.py            LLM 프로바이더 선택 (ollama/openai/anthropic)
│   ├── cache_db.py                 PostgreSQL 캐시 + 지역코드 룩업
│   ├── building_info.py            건물 정보 조회
│   ├── models.py                   내부 모델 (ValuationResult)
│   │
│   ├── graphs/                     LangGraph 그래프 4종 (appraisal/recommendation/simulation/comparison)
│   ├── services/
│   │   ├── chat_service.py             법률·세금 챗봇 서비스 (RAG 검색 + 세금 계산기 도구 라우팅)
│   │   └── rights_analysis_service.py  권리관계 위험 점검 서비스 (등기부·건축물대장 파싱·위험도 산정)
│   └── tools/
│       ├── ingest_transactions.py  실거래가 배치 수집 CLI
│       ├── sync_legal_regions.py    전국 10자리 법정동코드 계층 동기화 CLI
│       ├── build_law_corpus.py     국가법령정보센터 법령·판례 수집 → chat_corpus 확장
│       ├── listing_tool.py         샘플 CSV 매물 조회
│       ├── scoring_tool.py         매물 종합 점수 산출
│       └── simulation_tool.py      시뮬레이션 계산
│
├── schemas/                        Pydantic 스키마 (단위: 원·㎡)
├── data/
│   └── sample_listings.csv         개발·테스트용 가상 매물 43건 (유일하게 파일로 남은 데이터 — 나머지는 전부 PostgreSQL)
├── tests/                          pytest 테스트 (30개 파일, 743개 — 접근제어·시장탐색·케이스 소유권·실행 계획 등 포함)
├── docker/init.sql                 PostgreSQL 초기화 스크립트 (vector 익스텐션·pgvector 테이블)
├── Dockerfile.backend / .frontend  서비스 이미지
├── docker-compose.yml              pgvector(app 테이블 겸 RAG 벡터스토어) + redis + api + frontend
└── requirements.txt
```

---

## REST API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/health` | 헬스체크 |
| `POST` | `/api/appraisal` | 시세추정 실행 (동기, 하위 호환) |
| `POST` | `/api/appraisal/jobs` | 시세추정 작업 생성 → `{job_id}` (`address`·`property_category`·`property_detail`·`area_sqm` 구조화 입력 지원) |
| `GET` | `/api/appraisal/jobs/{id}` | 작업 상태 폴링 → `{status, step, history_id?, result?}` |
| `POST` | `/api/auth/register` | 회원가입 (이메일/비밀번호) |
| `POST` | `/api/auth/login` | 로그인 → JWT 쿠키 |
| `POST` | `/api/auth/password-reset/request` | 재설정 링크 발송 — 응답은 계정 존재 여부와 무관하게 항상 동일(계정 열거 방지) |
| `POST` | `/api/auth/password-reset/confirm` | 토큰 검증 후 비밀번호 변경 — **기존 세션 전부 무효화** |
| `GET` | `/api/auth/google` → `/callback` | Google OAuth |
| `GET` | `/api/auth/me` | 현재 사용자 조회 |
| `DELETE` | `/api/auth/me` | 회원 탈퇴 — 계정·이력·활동 즉시 삭제 |
| `POST` | `/api/auth/logout` | 로그아웃 |
| `POST` | `/api/recommendation` | 샘플 매물 추천 실행 |
| `POST` | `/api/recommendation/complexes` | **실거래 기반 단지 추천 (전국)** |
| `POST` | `/api/simulation` | 투자 시뮬레이션 실행 (세후·DSR·민감도 포함) |
| `GET` | `/api/simulation/market-rate` | 최신 주담대 평균금리 (한국은행 ECOS) |
| `POST` | `/api/comparison` | 매물 비교 실행 |
| `GET` | `/api/history` | 시세추정 이력 목록 (사용자별) |
| `GET` | `/api/history/{id}` | 저장된 리포트 1건 (영속 리포트 데이터 소스) |
| `DELETE` | `/api/history/{id}` | 이력 삭제 |
| `GET` | `/api/activity` | 시세추정·권리점검·상담을 합친 홈 최근 활동 피드 (사용자별) |
| `GET` | `/api/address/search` | 주소 검색 (카카오 API) |
| `POST` | `/api/rights/analyze` | 등기부·건축물대장 PDF 권리 위험 점검 (base64) |
| `POST` | `/api/chat` | 법률·세금 AI 정보 안내 챗봇 |

> 전체 API 명세: `http://localhost:8000/docs` (Swagger UI)

---

## 파이프라인 흐름

### 시세추정 파이프라인 (LangGraph)

```
사용자 자연어 입력
  → intent_agent.py       LLM 의도 분석 (주소·건물명·카테고리 검색 후보, 면적/호가/기준시점)
  → 검증                   필수 정보 확인 (미비 시 오류처리)
  → geocoding.py          공식 주소·좌표·법정동·지번 확정
  │     ├─ 사용자 직접 선택 유형
  │     ├─ 건축물대장 주용도 규칙
  │     └─ 주소·건물명·거리 검증을 통과한 카카오 장소 규칙
  │        ※ LLM 카테고리 후보는 최종 유형으로 사용하지 않음
  → Vworld                 용도지역·공시지가 보강 (선택)
  → deep_analysis.py      심층 분석 (실거래 + RAG)
  │     └─ price_engine.py: transaction_store 조회 → 미스 시 MOLIT API → write-through 적재
  → 라우터                 카테고리별 에이전트 분기
  → agents.py             유형별 가치 분석 (주거/상업/업무/산업/토지)
  │     └─ llm_utils.py: LLM 분석 의견 생성 (계산 수치만 인용, 재생성 금지)
  → appraisal_report.py   마크다운 리포트 + 구조화 결과 (AppraisalReport)
```

각 노드 완료 시 `progress_cb`가 호출되어 job의 `step`이 갱신되고,
프론트엔드가 5단계(요청 분석 → 주소 확인 → 실거래 수집 → AI 분석 → 리포트 생성)로 표시한다.

### 지오코딩 책임 분리와 트러블슈팅

지오코딩은 가격·법정동 코드처럼 사실성이 중요한 데이터이므로 LLM이 좌표나 최종 부동산
유형을 생성하지 않는다. Qwen3.5 9B를 포함한 LLM의 책임은 자연어에서 주소·건물명·유형
**검색 후보**를 추출하는 데서 끝난다. 이후 값은 다음 우선순위로 확정한다.

1. 프론트/API에서 사용자가 직접 선택한 유형 (`category_source=user`)
2. 동·호가 있으면 건축물대장 전유부 용도 (`unit_register`)
3. 카카오 주소 API의 좌표·법정동 코드·지번으로 조회한 건축물대장 주용도
   (`building_register`)
4. `아파트`·`오피스텔`·`공장`·`파이낸스센터`처럼 의미가 명확한 건물명 규칙
   (`building_name_rule`)
5. 건물명·주소·동일 시군구·300m 거리를 점수화하고 경합 여부까지 통과한 카카오 장소
   (`kakao_exact`)
6. 모두 실패하면 `unknown` — LLM 후보로 채우지 않고 물건 종류 직접 선택 요청

**실제로 발생한 오분류:** `서울 강남구 테헤란로 152`의 주소와 건물명은
강남파이낸스센터로 정상 변환됐지만, 건물명 카테고리를 찾지 못한 뒤 주소 전체를 키워드
검색하면서 같은 주소의 나이키 매장을 첫 결과로 골라 `상업용/상가`로 분류했다.

**해결:** 주소 전체 키워드 검색의 첫 결과를 유형 근거로 쓰는 폴백을 제거했다. 사용자
선택값을 구조화 필드(`address`, `property_category`, `property_detail`)로 LLM 입력과 분리하고,
건축물대장과 검증된 규칙만 최종 유형을 변경할 수 있게 했다. 현재 같은 주소는 건축물대장
`업무시설`을 근거로 `업무용/사무실`을 반환한다.

판정 결과에는 `category_confidence`·`category_evidence`와 사용자 선택/공식 유형을 함께
보존한다. 두 유형이 다르면 사용자 선택을 유지하되 `category_conflict=true`와 경고 문구를
리포트 주의사항에 표시한다. 캐시 키에는 알고리즘 버전(`v4`)과 동·호를 넣어 구버전 판정이나
다른 호실의 용도가 재사용되지 않게 했다. 주소 원문 없이 source·conflict·Vworld 상태를
남기는 `[geocode-metric]` 로그로 운영 품질도 집계할 수 있다.

**진단 포인트:**

- 좌표·법정동 코드가 비었으면 `KAKAO_REST_API_KEY`와 카카오 주소 검색 응답을 확인한다.
- `category_source=unknown`이면 LLM 장애가 아니라 공식·규칙 근거 부족이다. UI에서 유형을
  직접 선택하거나 건축물대장 조회 결과를 확인한다.
- 건축물대장 조회는 공공 API가 간헐적으로 503을 반환할 수 있다. 표제부 → 총괄표제부 →
  기본개요 순으로 폴백하며, 그래도 주용도가 없으면 건물명·정확한 장소 규칙으로 넘어간다.
- Vworld가 HTTP 200과 함께 `NOT_FOUND`를 반환할 수 있다. 이는 지오코딩 실패가 아니라 해당
  좌표의 용도지역·공시지가 보강 데이터가 없다는 뜻이며 빈 값으로 유지한다.
- 사용자가 직접 고른 유형은 최우선이라 건축물대장과 달라도 자동으로 덮어쓰지 않는다.
  향후에는 이 충돌을 오류가 아닌 경고로 사용자에게 표시하는 개선이 필요하다.

회귀 테스트는 `tests/test_geocoding_rules.py`에 있다. 사용자 선택 우선순위, 전유부 용도,
충돌 경고, 건축물대장 매핑, 주변 입점 매장 배제, 후보 점수 경합, 캐시 버전, Vworld 상태,
LLM 후보 비확정과 5개 서비스 유형 규칙을 고정한다.

### 매물 추천 파이프라인

```
PropertyQuery (지역·예산·면적·유형)
  → 쿼리 검증 → 후보 필터링 (listing_tool, 샘플 CSV)
  → scoring_tool.py 4축 점수 (가격 35% · 입지 30% · 투자 20% · 위험 15%)
  → 마크다운 추천 리포트
```

### 시뮬레이션 · 비교 파이프라인

```
시뮬레이션: dict | SimulationInput | listing+overrides
  → 입력 정규화 → 취득세·대출·현금흐름·시나리오 계산 → 리포트

비교: listings (+recs/sims)
  → 입력 정규화 → 점수 산출·우승자 선정 → 결정 리포트
```

---

## 필수 API 키

| 키 이름 | 용도 | 발급처 |
|--------|------|--------|
| `KAKAO_REST_API_KEY` | 지오코딩 + 주변시설 | [developers.kakao.com](https://developers.kakao.com) |
| `MOLIT_API_KEY` | 국토부 실거래가 | [data.go.kr](https://www.data.go.kr) |
| `MOIS_REGION_API_KEY` | 행정안전부 법정동코드 동기화 (선택, 없으면 `MOLIT_API_KEY` 재사용) | [data.go.kr](https://www.data.go.kr/data/15077871/openapi.do) |
| `RBONE_API_KEY` (또는 `REB_API_KEY`) | 부동산원 R-ONE 월간지수 — 시점수정 정밀화 (선택) | [reb.or.kr/r-one](https://www.reb.or.kr/r-one/portal/openapi/openApiIntroPage.do) |
| `ECOS_API_KEY` | 한국은행 금리 — 시뮬레이션 금리 자동 세팅 (선택, 없으면 sample 키 시도) | [ecos.bok.or.kr](https://ecos.bok.or.kr) |
| `LAW_OC_KEY` | 국가법령정보 — 챗봇 코퍼스 확장용 법령·판례 수집 (선택, 시드 코퍼스만으로도 동작) | [open.law.go.kr](https://open.law.go.kr) |
| `TAVILY_API_KEY` | 웹 시세 검색 (선택) | [tavily.com](https://tavily.com) |
| `VWORLD_API_KEY` | 토지 용도지역 (선택) | [vworld.kr](https://www.vworld.kr) |
| `GOOGLE_CLIENT_ID/SECRET` | Google OAuth (선택) | [console.cloud.google.com](https://console.cloud.google.com) |
| `JWT_SECRET_KEY` | 세션 토큰 서명 — **운영(`APP_ENV=production`)에서는 필수, 미설정 시 기동 실패** (개발은 기본값 허용) | 임의 문자열 |
| `CORS_ORIGINS` | 허용 오리진 (콤마 구분) — **배포 시 실제 도메인으로 교체 필수**, 미설정 시 localhost만 허용 | 예: `https://example.com` |
| `COOKIE_SAMESITE` | 세션 쿠키 SameSite — `lax`(기본, 프론트·API 동일 출처) / `none`(다른 사이트 배포 시, HTTPS 필수) / `strict` | `lax` |
| `FORWARDED_ALLOW_IPS` | 리버스 프록시 뒤에 배포 시 **필수** — 없으면 모든 요청이 프록시 IP로 뭉쳐 레이트 리밋·로그인 잠금이 사실상 무력화 | 예: `172.18.0.0/16` |
| `RESEND_API_KEY` | 비밀번호 재설정 메일 발송 (선택, 비워두면 서버 로그에 재설정 링크 출력) | [resend.com](https://resend.com) |
| `DATABASE_URL` | 앱 테이블(사용자·이력·활동·캐시·실거래가·상담 코퍼스) — **필수, 폴백 없음** | `docker compose up pgvector` |
| `REDIS_URL` | 작업 큐 상태·레이트 리밋·로그인 잠금 카운터 — **필수, 폴백 없음** | `docker compose up redis` |
| `SENTRY_DSN` | 에러 추적 (선택, 비워두면 완전히 비활성 — 로컬·CI에 영향 없음) | [sentry.io](https://sentry.io) |

> 전체 환경변수 목록과 설명은 `.env.example` 참고.

LLM 프로바이더 (`model_factory.py`):

| 환경변수 | 기본값 |
|---------|--------|
| `LLM_PROVIDER` | `ollama` (`openai` / `anthropic` / `google` 지원) |
| `OLLAMA_MODEL` | `qwen3.5:9b` |
| `OPENAI_MODEL` / `ANTHROPIC_MODEL` | 프로바이더 전환 시 |

> **카카오 403 오류** 발생 시: 개발자 콘솔 → 플랫폼 → Web → `http://localhost` 등록

---

## 스키마

모든 스키마는 `schemas/` 디렉터리의 Pydantic 모델. **금액 단위: 원(int), 면적 단위: ㎡(float).**
(단, `backend/models.py`의 `ValuationResult`는 만원 단위 — 리포트 생성 시 변환)

| 스키마 | 핵심 필드 |
|--------|----------|
| `PropertyQuery` | `intent`, `region`, `property_type`, `area_m2`, `budget_min/max`, `purpose` |
| `PropertyListing` | `listing_id`, `address`, `property_type`, `area_m2`, `asking_price`, `deposit_price`, `station_distance_m`, `built_year` |
| `AppraisalResult` | `estimated_price`, `low/high_price`, `confidence`, `appraisal_date`, `land_use_zone`, `official_land_price`, `exclusive_area_m2`, `valuation_breakdown`, `comparables`, `legal_restrictions`, `warnings` |
| `ComparableTransaction` | 시점수정(`time_adj_factor`)·지역/개별요인 보정 포함 비교사례 |
| `RecommendationResult` | `listing`, `total_score`, 4축 점수, `recommendation_label`, `reasons`, `risks` |
| `SimulationResult` | `acquisition_cost`, `loan`, `cash_flow`, `scenario_base/bull/bear` |
| `ComparisonResult` | `rows`, `decision_report` |

---

## 공개 API (Python)

### 시세추정

```python
from backend.router import run_appraisal

result = run_appraisal(
    "마포구 아파트 84㎡",
    building_name="마포래미안푸르지오",
    address="서울 마포구 마포대로 201",
    property_category="주거용",
    property_detail="아파트",
)
# result["final_report"]              — 마크다운 리포트
# result["analysis_result"]           — 수치 데이터 dict
# result["report_output"].structured  — AppraisalResult (구조화)

# 진행 콜백 (노드 완료마다 호출 — job 큐가 사용)
result = run_appraisal("서초구 아파트 59㎡", progress_cb=lambda node: print(node))
```

### 매물 추천 / 시뮬레이션 / 비교

```python
from backend.router import run_recommendation, run_simulation, run_comparison
from schemas.property_query import PropertyQuery
from schemas.simulation import SimulationInput

state = run_recommendation(PropertyQuery(region="마포구", budget_max=1_200_000_000), limit=5)
# state["results"] — total_score 내림차순

state = run_simulation(data=SimulationInput(
    purchase_price=1_000_000_000, loan_amount=500_000_000,
    annual_interest_rate=4.0, holding_years=3, rent_fee=2_000_000, owned_homes=1,
))
# state["result"].scenario_base.annual_equity_roi — 연환산 수익률 (%)

state = run_comparison(listings=[...])
# state["result"].rows[0] — 우승 매물
```

---

## 시세추정 모델

| 출력물 | 산출 방식 |
|--------|----------|
| 추정 시장가치 | 인근 실거래 평균 ㎡당 단가 × 면적 (±10% 범위) |
| 시점수정 | **부동산원 월간 매매가격지수** (`RBONE_API_KEY` 설정 시, 시군구 단위) → 미공표·미지원 시 유형별 근사 변동률 폴백 |
| 실거래 폴백 | 실거래 없을 시 공시가격 ÷ 현실화율 역산 (주거용) |
| 고/저평가 판단 | (추정가 − 인근 평균) / 인근 평균 × 100 |
| 투자 수익률 | 추정가 × 유형별 Cap Rate |
| 신뢰도 | **다요인 모델 + 백테스트 보정** (`confidence.py`) — 매칭수준·표본수·산포(CV)·신선도·시점수정 방식 기반점에, 백테스트 실측 적중률(`data/avm_calibration.json`)을 버킷별로 블렌딩. 정의: "유사 조건에서 추정치가 실거래가 ±10% 이내에 들 확률" |
| AI 분석 의견 | LLM 생성 + **수치 가드레일** (`opinion_guard.py`) — 컨텍스트로 주입한 수치 외의 숫자가 든 문장은 자동 삭제, 위반 시 1회 재시도 후 결정론적 폴백. 출력은 프로바이더 무관 OpinionOutput 스키마로 강제 |

### 시점수정 상세 (부동산원 지수 기반)

`backend/reb_index.py` — R-ONE OpenAPI `SttsApiTblData` 사용, 통계표 `A_2024_00045` (월간 아파트 매매가격지수, 시군구 단위).

```
시점수정 계수 = 기준시점 월 지수 / 거래 월 지수
```

- **지역 매칭**: 시군구 정확 매칭 (동명이구는 시도로 판별) → 시도 → 전국 순 폴백
- **공표 시차 처리**: 지수는 익월 중순 공표 — 기준시점 월이 미공표면 최근 공표월까지 지수로 보정하고, 잔여 월수는 근사 변동률로 이어서 보정
- **캐싱**: 월별 전 지역 지수를 `cache.db`에 캐시 (완결 월 30일 / 최근 월 24시간)
- **동작 확인**: `python backend/reb_index.py 서초구` — 키 상태·지수 조회·계수 산출 진단
- 통계표 교체: env `REB_STATBL_RESIDENTIAL` (주거용), `REB_STATBL_LAND` (토지)

### 비교사례 매칭 전략 (단계적 확장)

```
1) 단지명 정확/공백제거/부분 매칭 (3 → 6 → 12개월)
2) 동 필터링 (3 → 6개월)
3) 구 전체 (3 → 6개월)
4) 공시가격 역산 폴백 (주거용 한정)
```

### 백테스트 (AVM 정확도 실측)

`backend/tools/backtest_avm.py` — 대상 월 거래를 이전 데이터만으로 추정(홀드아웃)해
실거래가와 비교하고, 버킷(매칭수준×표본수)별 적중률을 신뢰도 보정테이블로 저장한다.

```bash
python backend/tools/ingest_transactions.py --regions 서초구 --months 12 --yes
python backend/tools/backtest_avm.py --regions 서초구 --target-months 3
# → data/avm_calibration.json 생성 → confidence.py 가 자동 반영
```

서초구 434건 실측 예시: 동일단지 매칭은 ±10% 적중률 69~84%로 양호하지만,
동일동/구 매칭은 8~33%에 불과 — 휴리스틱만으로는 과대평가되던 신뢰도가
실측 기반으로 하향 보정된다.

### 유형별 Cap Rate

| 주거용 | 상업용 | 업무용 | 산업용 | 토지 |
|-------|-------|-------|-------|------|
| 3.5% | 5.0% | 4.5% | 6.0% | 2.5% |

---

## 투자 시뮬레이션 모델

순수 계산 엔진 (`simulation_tool.py`) + 법령 규칙 테이블 (`tax_rules.py`, 기준일 명시) + 한국은행 금리 (`bok_rates.py`).

```
SimulationResult
├── acquisition_cost   취득세 + 중개보수 + 기타 비용
├── required_cash / equity / loan / cash_flow
├── scenario_base/bull/bear   성장률 ±spread — 세후 순손익
│     └── 세전 순손익 − 양도소득세 − 보유세(재산세+종부세) − 매도 중개보수
├── finance_check      LTV·스트레스 DSR 검증 (연소득 입력 시)
├── breakeven_growth_rate   세후 손익분기 연 상승률 (이분탐색)
└── rate_sensitivity   금리(±1%p) × 상승률(±spread) 3×3 민감도
```

### 세금·규제 규칙 (`tax_rules.py` — 세법 기준일 명시, 골든 테스트로 개정 감지)

| 항목 | 규칙 | 데이터 |
|------|------|--------|
| 양도소득세 | 1주택 12억 비과세·고가 안분·장특공(최대 80%)·단기 70/60%·누진 6~45%·지방세 10% | 법령 테이블 |
| 보유세 | 재산세(공정시장가액비율·1주택 특례세율) + 종부세(공제 12억/9억) — 연도별 합산 | 공시가격 (입력 or 시세×현실화율 추정) |
| 취득세 | 1주택 1.1~3.3% / 2주택 8% / 3주택+ 12% / 비주거 4.4% | 법령 테이블 |
| DSR | 스트레스 금리(+1.5%p) 원리금균등 환산, 한도 40%, 가능 대출액 역산 | 연소득 (사용자 입력) |
| LTV | 무주택·1주택 70% / 다주택 60% / 조정지역 50%·30% | 규정 테이블 |
| 공실률 | 월세 수입 × (1 − 공실률), 기본 5% | 사용자 입력 |
| 금리 기본값 | 예금은행 주담대 가중평균금리 (월별, 24h 캐시) | **한국은행 ECOS** (`ECOS_API_KEY`, 없으면 4.0% 폴백) |

> ⚠️ 간이 계산 — 감면 특례·1세대 판정 등 개별 사정 미반영. 실제 세액은 세무사 상담 필요.
> 무자본 갭투자(실투자금 ≤ 0)는 수익률 대신 "무한 레버리지"로 표시하고 역전세 리스크를 경고한다.

---

## 매물 추천 점수 모델

```
total = 가격적정성×0.35 + 입지×0.30 + 투자가치×0.20 + (10 − 위험도)×0.15
```

| 총점 | 8.0+ | 6.5+ | 5.0+ | 5.0 미만 |
|------|------|------|------|---------|
| 레이블 | 적극 추천 | 추천 | 검토 필요 | 비추천 |

### ⚠️ 샘플 매물 데이터 고지

추천·비교·시뮬레이션의 매물 데이터(`data/sample_listings.csv`)는 **개발·테스트 전용 가상 데이터**
(서울 8개 구 43건)다. 가격·좌표·단지명은 임의 생성 값이며 실제 거래 판단에 사용할 수 없다.
반면 **시세추정은 국토부 실거래가 실데이터**를 사용한다.

---

## 백업 · 복구

사용자 계정·시세추정 이력·활동 기록·실거래가 캐시·RAG 벡터스토어가 전부
`pgvector` 컨테이너 하나(`pgvector_data` 볼륨)에 있다. `docker compose down -v`
또는 볼륨 손상 시 별도 백업이 없으면 전체 데이터가 복구 불가능하게 사라진다.

```bash
# 백업 — backups/ 에 타임스탬프 덤프 생성, 14일 초과분 자동 정리
./scripts/backup_db.sh
./scripts/backup_db.sh --out /mnt/backup --retention-days 30   # 저장 위치·보존기간 지정

# 운영 환경: cron으로 매일 새벽 실행
# 0 3 * * * cd /path/to/property_concierge && ./scripts/backup_db.sh --out /mnt/backup >> /var/log/pc_backup.log 2>&1

# 복구 — 대상 DB를 DROP 후 덤프로 재생성 (되돌릴 수 없음, 확인 프롬프트 있음)
./scripts/restore_db.sh backups/property_concierge_20260725_030000.dump
docker compose restart api   # 커넥션 풀 재연결
```

두 스크립트 모두 `.env`의 `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`를 읽고,
`property_concierge_pgvector` 컨테이너([docker-compose.yml](docker-compose.yml)의
`container_name`)에 대해 `pg_dump`/`pg_restore`를 실행한다. 컨테이너 이름을 바꿨다면
스크립트 안의 이름도 함께 바꿔야 한다.

> 백업 파일(`backups/`, `*.dump`)은 `.gitignore`에 등록돼 있다 — 사용자 개인정보가
> 담긴 덤프를 저장소에 커밋하지 않도록 주의할 것.

---

## 스키마 마이그레이션 (Alembic)

앱 테이블(`db/models.py`, 13종)의 스키마 변경 이력은 `db/migrations/`가 관리한다.
운영 배포는 `alembic upgrade head`가 uvicorn 워커보다 먼저, 단일 프로세스로
실행된다([Dockerfile.backend](Dockerfile.backend)) — 여러 워커가 동시에 스키마를
바꾸려는 경합 자체를 원천 차단하기 위해서다.

```bash
# 모델(db/models.py) 변경 후 마이그레이션 생성
alembic revision --autogenerate -m "설명"
# 생성된 db/migrations/versions/*.py 파일을 반드시 검토할 것 —
# autogenerate는 인덱스명·서버 기본값 등을 놓치거나 과도하게 잡아낼 수 있다.

# 로컬 DB에 적용
alembic upgrade head

# 현재 DB가 어느 리비전인지 확인
alembic current
```

`create_all()`(`db/base.py`)은 alembic 없이 `uvicorn`을 직접 띄우는 로컬 개발·
테스트 경로를 위한 안전망으로 남겨뒀다 — 정상 배포 경로에서는 alembic이 먼저
스키마를 확정하므로 `create_all()`은 아무 일도 하지 않는다(이미 존재하는
테이블은 건드리지 않음). 다만 `create_all()`은 컬럼 삭제·타입 변경처럼
alembic이 다루는 변경은 반영하지 못하므로, 그런 변경은 반드시 마이그레이션을
거쳐야 한다.

---

## 테스트

```bash
# DB·Redis 필요 테스트(test_access_control.py, test_transaction_store.py,
# test_rights_and_chat.py 일부)를 돌리려면 먼저 컨테이너를 띄운다.
docker compose up -d pgvector redis

pytest tests/                              # 전체 실행

# 주요 파일
pytest tests/test_price_engine_calc.py    # 가격 계산
pytest tests/test_transaction_store.py    # 실거래가 로컬 스토어 (TTL·멱등·동시성, PostgreSQL 필요)
pytest tests/test_simulation_service.py   # 시뮬레이션
pytest tests/test_comparison_service.py   # 비교
pytest tests/test_rights_and_chat.py      # 권리관계 위험 점검 · 법률·세금 챗봇
pytest tests/test_access_control.py       # 이력·작업 소유자 격리 (타인 리포트 열람 차단, PostgreSQL·Redis 필요)
pytest tests/test_password_reset.py       # 비밀번호 재설정 + 세션 무효화 (계정 열거 방지 포함, PostgreSQL·Redis 필요)
pytest tests/test_cookie_config.py        # 쿠키 SameSite/Secure 설정 → 실제 Set-Cookie 헤더 매핑
pytest tests/test_geocoding_rules.py      # LLM 후보와 결정론적 주소·유형 확정 경계
pytest tests/test_purchase_cases.py       # 케이스·후보 비교·최종 선택·거래 실행 계획
```

DB에 접근하지 않는 테스트는 Postgres·Redis 없이도 동작한다 —
`db/base.py`가 엔진을 지연 생성해 실제로 DB를 쓰는 시점에만 `DATABASE_URL`을 확인하기 때문이다.

GitHub Actions(`.github/workflows/ci.yml`)에서 push·PR마다 postgres·redis 서비스 컨테이너와
함께 전체 스위트를 실행한다.

### 별도 평가·검증 도구

`evaluation/`에서 핵심 매수 의사결정 상태·AVM 백테스트·종합 컨시어지 의도 추출과 계산기·RAG·법률 챗봇을 공통 JSON·HTML 보고서로 평가한다.
기존 회귀 테스트와 함께 사용하며, 자동 검사와 사람 채점을 구분한다. [실행·데이터셋·결과 해석 안내](evaluation/README.md)를 참고한다.

```bash
./venv-wsl/bin/python -m evaluation run --suite all                   # 의사결정·가상 AVM·계산·시드 검색
./venv-wsl/bin/python -m evaluation run --suite decision              # 후보별 위험·비교·거래 준비 상태
./venv-wsl/bin/python -m evaluation run --suite avm --live            # 저장소 실거래 홀드아웃 (보정 파일 미갱신)
./venv-wsl/bin/python -m evaluation run --suite intent --live --max-cases 1
./venv-wsl/bin/python -m evaluation run --suite chat --live --max-cases 1 --timeout 300
./venv-wsl/bin/python -m evaluation run --suite rag --live            # 설정된 실제 코퍼스 검색
```

결과는 `evaluation-results/<실행ID>/report.html`에서 확인한다. `--live`는 설정된 모델·임베딩을 실제 호출한다.
초기 계산 기대값은 기존 수기 회귀값으로, 현행 법령이나 외부기관 계산기 대조 완료를 의미하지 않는다.
CI에는 외부 호출 없는 계산·시드 검색 평가만 포함한다.

> **주의**: `AppraisalResult`는 pydantic 기본 설정상 **모르는 필드를 조용히 무시**한다.
> 제거된 `judgement`·`gap_rate` 같은 인자를 테스트에서 넘겨도 오류 없이 통과하므로
> (실제로는 아무것도 검증하지 않는 상태가 된다), 스키마 변경 시 테스트도 함께 갱신할 것.

---

## 알려진 제약

후보 자금 분석은 취득비용 포함 필요 현금·보유 현금·부족 자금·첫 달 대출 상환액·사용자 상환 한도를
후보 비교에 연결한다. 정보 누락이나 자금 부담이 있으면 다음 행동을 안내하고, 보완 후 재계산하면 갱신한다.

케이스의 **공통 매수 조건**에는 예산, 보유 현금·비상자금, 상환 한도·대출 가정, 관심 유형·최소 면적·연식과 우선순위를 저장한다. 후보 비교 화면의 자금 시나리오는 이 조건을 최대 4개 후보에 동일하게 적용해 매수가·금리·비상자금 변화의 영향을 보여준다. 시나리오 결과는 기존 후보 분석이나 최종 선택을 변경하지 않는다. 아파트 단지 추천은 케이스 예산·면적·연식과 가격·거래량·연식 우선순위를 반영한다. 비아파트는 개별 매물 추천 데이터가 부족하므로 지역 실거래 현황을 보여주고, 확인한 개별 물건을 후보로 등록해 검토한다. 케이스를 선택한 종합 컨시어지의 자금 분석은 공통 조건을 기본값으로 사용하며 대화에서 명시한 조건을 우선한다.
`케이스 조건 보유 현금 4억원으로 변경`처럼 저장을 명시한 대화에서는 새로 추출·검증한 금융 조건과 예산만 케이스에 기록한다. 가정형 질문의 값은 케이스에 저장하지 않는다.
후보에서 다시 열면 직전 금융 조건을 복원하며, 희망가 변경 시 재검토가 필요하다.
이전 저장 결과에 필요 현금·상환액이 없으면 재계산을 안내한다. 임대보증금은 잔금 자금에서 자동 차감하지 않는다.
계산 결과는 금융기관의 대출 승인을 뜻하지 않으며 실행 계획의 은행 확인 작업은 별도로 유지한다.

- **시점수정**은 주거용·토지만 부동산원 지수 적용 — 상업·업무·산업용은 적합한 월간 시군구 지수가 없어 근사 변동률 사용. 주거용은 아파트 지수를 연립·단독에도 대표 적용
- **시세추정·단지 추천은 전국 시군구 지원** — 지오코딩 시군구코드 직접 사용 + 전국 250개 지역코드 시드(`tools/seed_region_codes.py`) + 지오코딩 자동 등록
- **Vworld 토지 보강은 선택 데이터** — 키와 HTTP 호출이 정상이더라도 좌표에 따라 `NOT_FOUND`가 반환될 수 있으며, 이때 용도지역·공시지가는 빈 값으로 유지
- **사용자 선택 유형이 공식 주용도보다 우선** — LLM 오분류 방지를 위한 현재 정책. 건축물대장과 충돌할 때 UI 경고를 표시하는 기능은 아직 없음
- **단지 추천**은 실거래 기반 추정 시세 — 실제 매물 존재 여부·호가는 미포함 (호가 매물은 데이터 제휴 필요). 샘플 매물 모드는 개발용 가상 데이터 유지
- **로컬 개발도 Docker(PostgreSQL·Redis) 필수** — SQLite·인프로세스 메모리 폴백을 두지 않았다. 완전 오프라인 개발이 필요해지면 SQLite 폴백 재도입을 검토할 것
- **비밀번호 재설정 메일은 아직 실제로 발송되지 않는다** — `RESEND_API_KEY` 미설정 시 서버 로그에 재설정 링크를 출력하는 폴백만 동작. 실발송하려면 Resend 도메인 인증(SPF/DKIM)이 필요
- **TLS·리버스 프록시 미구성** — 외부 도메인으로 배포하려면 프록시 컨테이너 추가 + `FORWARDED_ALLOW_IPS` 지정이 선행되어야 한다 (레이트 리밋이 프록시 IP 하나로 뭉치는 것을 막기 위함)
