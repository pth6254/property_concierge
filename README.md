# Property Concierge — 부동산 매수 의사결정 플랫폼

포트폴리오: [보관 HTML](docs/portfolio/property_concierge.html) · [원본 수정·생성·검증 안내](docs/portfolio/README.md)
— 기존 발표 자료는 2026-09-08 검증 기준이다. 최신 제품 방향과 구현 상태는 아래 문서를 따른다.

사용자가 관심 있는 부동산을 가져오면 가격·자금·권리와 확인 가능한 적합성·위험 정보를 근거로 검토하고, 다음 행동과 선택 이유를 같은 매수 케이스에 남기는 **부동산 의사결정 플랫폼**이다.
현재 매수 케이스·후보 비교·사용자 매물 이력·**AI 시세추정(AVM)**·자금 시뮬레이션·권리 위험 점검과 다섯 판단 축의 통합 요약을 제공한다.
장기적으로 입지·수익성 분석과 임장·협상·계약·잔금·등기 기록을 연결하는 **Property Decision & Transaction OS**를 목표로 한다.
출시 범위와 단계별 완료 기준은 [상용화 방향과 구현 순서](docs/product-strategy.md), 현재 구현과 다음 작업은 [프로젝트 인수인계](docs/project-handoff.md)를 따른다.

> ⚖️ **법적 고지**: 본 서비스의 시세추정은 자동가치산정(AVM) 기반 **참고용 분석**이며,
> 「감정평가 및 감정평가사에 관한 법률」에 따른 감정평가가 아니다.
> 담보·소송·과세 등 법적 효력이 필요한 가치 판단은 감정평가사에게 의뢰해야 한다.

---

## 제품 방향과 현재 개발 단계

핵심 사용자 흐름은 **관심 매물 등록 → 후보 저장 → 가격·자금·권리 검토 → 다섯 판단 축 비교 → 사용자 선택·제외 → 다음 행동 → 정보 변경 시 재검토**다. ‘이 매물을 감당할 수 있는가’, ‘가격 차이의 근거는 무엇인가’, ‘무엇을 더 확인해야 하는가’를 설명하는 데 집중한다.

초기 매물 확보는 사용자의 URL·직접 입력·CSV 등록을 중심으로 한다. 네이버 부동산 지도 링크는 외부 탐색을 돕는 보조 기능이며, 비공식 수집 성공을 매수 검토의 필수 조건으로 두지 않는다. 호가·확인 시각은 사용자 제공 자료이고, 국토부 실거래와 AVM 추정값은 별도 자료다.

현재는 **1단계 아파트 매수 의사결정의 기반 강화**를 진행 중이다. 후보별 적합성·가격성·자금성·위험성·실행성의 API와 화면을 첫 구현 단위로 반영했다. 이 결과는 자동 매수 결론이나 거래 안전 인증이 아니다. 근거 부족·실패·만료·원본 변경을 구분하고 사용자가 보완할 행동을 안내한다.

| 구분 | 2026-10-01 기준 상태 |
|---|---|
| 현재 제공 | 사용자 매물 등록·변경 이력, 케이스·후보, AVM·자금·권리 결과 연결, 다섯 판단 축과 근거·다음 행동, 비교·선택 이유, 거래 준비 작업 |
| 다음 작업 | 주소·동일 부동산 객체 식별, 비교 실거래와 문서의 항목별 근거, 실제 아파트 사례의 전체 흐름·실패 처리 검증 |
| 후속 계획 | Listing Time Machine, 명시적 선호·임장·협상 기록, 주거 유형 확대, 유형별 상업·산업·토지 분석, 공급자 등록과 거래 지원 |
| 모바일 앱 | 이후 단계로 유보. 현재 제공하는 반응형 웹 화면은 별도 모바일 앱이 아님 |

첫 출시 범위는 아파트 매매와 자료·검증이 확보된 지역이다. 다른 유형의 기존 계산 기능과 전국 행정구역 조회 구조는 유지하지만 전국 모든 자산의 동일한 데이터 완성도를 뜻하지 않는다. 1단계 전체 완료는 실제 사례의 근거·변경 재검토·전체 흐름을 검증한 뒤 판단한다.

## 문서와 인수인계

| 문서 | 목적 |
|---|---|
| [프로젝트 인수인계](docs/project-handoff.md) | 현재 완료 범위, 핵심 코드, 다음 작업과 최근 검증 경계 |
| [제품 전략](docs/product-strategy.md) | 사용자 기획안에 따른 포지셔닝·데이터 전략·단계별 완료 기준 |
| [에이전트 작업 지침](AGENTS.md) | 코드를 수정할 때 지켜야 할 구조·보안·데이터·검증 제약 |
| [백엔드 안내](services/intelligence/backend/README.md) · [프론트엔드 안내](web/README.md) | 도메인 서비스와 화면의 연결 위치·개발 방법 |
| [의사결정 검토 기준](docs/decision-assessment.md) · [자금 입력 기준](docs/funding-consistency.md) | 다섯 축의 계약·미확인 처리·후보 입력 의미 |
| [매물 등록](docs/imported-listings.md) · [수집 시점 관리](docs/listing-collection.md) · [화면 이동](docs/ui-navigation.md) | 사용자 자료와 원본 변경·탐색 연결의 경계 |
| [운영 안내](docs/operations.md) · [작업 복구](docs/job-recovery.md) · [평가 안내](services/intelligence/evaluation/README.md) | 배포 준비·운영·테스트와 실제 품질 평가의 구분 |

`CLAUDE.md`는 `AGENTS.md`를 임포트한다. 인수인계 시 두 파일에 지침을 중복 작성하지 않는다.

## 주요 기능

동네 탐색은 동일 면적·준공연도·기간으로 비교하며, 매수 케이스의 공통 조건을 함께 적용한다.
단지 추천 카드에서 실거래 기준 예상 필요 현금·월 상환액을 확인할 수 있다.
케이스의 단계별 안내와 화면 하단 문제 신고, 운영 관리의 처리 시간·실패 집계·정기 백업을
추가했다. 자세한 설정과 검증 경계는 [운영 안내](docs/operations.md), 실제 법령 검색과
주거용 에이전트 가격 평가 실행은 [평가 안내](services/intelligence/evaluation/README.md)를 따른다.

| 기능 | 설명 |
|------|------|
| **매수 검토 케이스** | 매수 목표·예산·관심 지역·후보를 묶고 시세·자금·권리 분석과 체크리스트를 관리하며, 후보 2~4개를 비교해 최종 후보와 선택 근거를 저장. 시세 30일·자금 14일·권리 7일이 지나면 갱신 필요로 표시 |
| **후보별 의사결정 요약** | 케이스의 ‘매수 검토 요약’에서 적합성·가격성·자금성·위험성·실행성과 출처·기준 시각·미확인 정보를 확인. 만료·변경·근거 부족은 현재 비교 금액에 사용하지 않고 입력·재분석·거래 준비의 다음 행동으로 연결. [검토 기준과 검증 범위](docs/decision-assessment.md) |
| **주소 기반 매물 등록** | 주소 검색·선택으로 단지·건물명과 도로명·지번·법정동·좌표를 연결하고 출처·조회 시각을 저장. 사용자 별칭은 선택 입력으로 별도 관리하며 후보·요약에도 표시. 이름이 없거나 여러 이름이면 미확인, 검색 실패 시 직접 입력 가능. [사용·검증 안내](docs/address-based-listing.md) |
| **후보별 다음 행동** | 예산·권리 위험, 희망가 누락, 분석 누락·실패·만료, 미완료 체크리스트를 규칙으로 안내하고 해당 분석·검토 화면으로 연결. 희망가를 수정할 수 있으며 기존 자금분석의 매수가와 다르면 재확인을 안내. 제외 후보는 안내에서 제외하며 검토 항목 완료가 매수 안전성을 의미하지 않음 |
| **거래 실행 계획** | 최종 후보 선택 후 계약 전·잔금 전·잔금일·거래 후의 기본 작업 18개를 자동 생성. 계약·잔금 예정일 기준 권장일, 기한 경과·문제·외부 대기와 준비도를 표시하고 실제 확인자·결과·근거·후속 조치를 같은 케이스에 기록 |
| **동네 탐색** | 시·도 → 시·군·구 → 법정동의 계층에서 수집된 실거래를 중앙값·분위수·예산 적합률·표본 수준으로 비교하고, 관심 지역과 아파트 단지를 케이스에 저장. 단지는 실제 광고 매물과 구분 |
| 🏡 **컨시어지 홈** | 사용자 여정(매물 탐색 → 가치 분석 → 안전 점검 → 법률·세금 상담) 기반 홈 화면. 주소 검색 히어로에서 바로 시세추정으로 연결, 시세추정·권리점검·상담을 합친 최근 활동 피드 |
| 🏠 **AI 시세추정** | 자연어/단계별 입력 → 유형별 실거래 비교·수익환원·원가법 기반 추정 시세와 참고용 리포트 산출 |
| 📊 **리포트 영속화** | 결과가 이력 DB에 저장되어 `/report/{id}` URL로 본인 기록을 재열람·인쇄(PDF). URL만으로 타인에게 공개되는 공유 기능은 아님 |
| ⏱ **비동기 작업 큐** | 30초~2분 걸리는 파이프라인을 job으로 실행, 단계별 진행 상황 실시간 표시. 상태는 Redis에 저장돼 멀티 워커에서도 어느 워커가 폴링을 받든 동일한 진행 상황을 본다 |
| ✨ **단지 추천·샘플 도구** | 수집된 실거래를 예산·면적 조건으로 집계해 아파트 단지를 추천. 실제 광고 매물의 존재·호가를 확인한 목록은 아니며 샘플 추천은 별도 개발용 도구 |
| 📈 **투자 시뮬레이션** | 취득세·대출 상환·현금흐름·3개 시나리오(기준/강세/약세) 수익률 계산 |
| ⚖️ **후보 비교·샘플 비교** | 케이스 후보는 근거·가격·자금·위험·검토 상태를 비교하고 사용자가 선택. `/comparison`의 샘플 점수 비교와 구분 |
| 🔍 **권리관계 위험 점검** | 등기부등본·건축물대장 **PDF 업로드** → 가압류·신탁·근저당 검출, 깡통전세 위험도(경매 배당 시뮬레이션), 소액임차인 최우선변제 판정 |
| 💬 **법률·세금 AI 안내** | RAG(법령·분쟁사례) + 세금 계산기 도구 호출(증여·상속·양도·보유세) 챗봇 — 수치 가드레일로 계산기 값만 인용, `tools/build_law_corpus.py`로 법령·판례 코퍼스 확장 |
| 📋 **이력 대시보드** | 사용자별 시세추정 이력 검색·통계 차트·리포트 재열람 |
| 🔐 **인증·보안** | 이메일/비밀번호 + Google OAuth, JWT 쿠키 세션, 사용자별 이력 분리, 회원 탈퇴(전체 삭제), 로그인 잠금(5회 실패), 엔드포인트별 레이트 리밋, 챗봇 일일 상한, 비밀번호 재설정(계정 열거 방지) + 재설정 시 기존 세션 전부 무효화, 배포 형태별 쿠키 `SameSite` 설정 |
| 🔒 **개인정보 보호** | 업로드 PDF는 메모리에서만 분석 후 즉시 파기(무저장), 활동 기록은 주소 마스킹·질문 축약 저장, 개인정보처리방침·이용약관 페이지(`/privacy`·`/terms`) |
| 🗄 **실거래가 로컬 스토어** | MOLIT API 응답을 PostgreSQL에 적재 — 반복 조회 시 API 호출 없이 즉시 응답, 배치 수집 CLI 제공 |

---

## 아키텍처 개요

백엔드는 **Kotlin + Spring Boot의 저장·권한·거래 상태·고정 수식 계산**과 **Python + FastAPI의 모델 추정·AI 분석**으로 분리한다.
`services/platform/`에 기존 JWT와 호환되는 인증, 사용자 매물·케이스·후보·거래 준비 저장, 분석 이력과 Redis 작업 계약을 추가했다.
필수 값과 미확인 값을 Kotlin 타입으로 구분하고 외부 JSON의 null·금액·필드를 별도로 검사한다.
기본 실행은 웹 **3002** → Caddy → Next.js / Kotlin Spring이며 공개 API **8002**도 Spring이다.
OAuth·비밀번호 재설정·메일·탈퇴·주소 검색·이력·운영 API·작업 접수까지 Spring이 제공한다.
Python은 서비스 인증이 필요한 `/internal/v1/ai/*`·`/internal/v1/data/*`와 순수 분석 계약만 제공한다.
대체된 Python 일반 API·인증·주소·레이트 리밋 파일 16개와 중복 구현을 삭제했다.
챗봇 자금 분석도 Spring의 실행·소유자 확인·결과 저장을 사용한다. 중복 재도입은 `scripts/audit_python_routes.py`로 검사한다.
서비스 책임·설정·검증 결과는 [백엔드 전환 안내](docs/backend-migration.md)를 따른다.
대출·취득비용·세금·LTV/DSR·현금흐름·수익 시나리오는 Kotlin의 같은 계산기를 화면·챗봇·비교에서 호출한다.
모델이 제시한 상승률은 입력 가정이며 복리·수익률 계산 자체는 Kotlin이 수행한다. 자세한 경계는 [계산 책임](docs/calculation-architecture.md)을 따른다.

```
[Caddy — 웹 호스트 :3002]
   ├── 화면 → Next.js 16 내부 :3000
   └── /api → Kotlin Spring 내부 :8080 — API 호스트 :8002
                 ├── 인증·소유자·매물·케이스·선택·거래 준비
                 ├── 분석 이력·관측 기록·Redis 작업 저장
                 ├── 대출·세금·자금·수익 고정 수식 계산
                 └── 내부 REST → Python FastAPI 내부 :8000
                                    ├── AVM·권리·추천·LLM·RAG
                                    ├── 자금 입력 해석·리포트 표현 → Spring 계산 계약
                                    └── 별도 실행기 → Spring에 결과 저장

[LangGraph 파이프라인 (services/intelligence/backend/)]
   ├── 캐시·지역코드 (services/intelligence/backend/cache_db.py)         │  PostgreSQL
   ├── 실거래가 로컬 스토어 (services/intelligence/backend/transaction_store.py)  │  (real_estate_db,
   ├── 법률·세금 상담 코퍼스 (services/intelligence/backend/chat_corpus.py)       │   pgvector 공유)
   │        ↑ 미스 시 폴백           ↑ 배치 수집
   ├── 국토부 MOLIT API      services/intelligence/backend/tools/ingest_transactions.py
   ├── 결정론적 지오코딩 (카카오 주소·좌표 → 건축물대장 주용도 → 검증된 장소 규칙)
   ├── Vworld 용도지역·공시지가 보강 (선택, 조회 결과가 없을 수 있음)
   └── LLM (OpenRouter / Ollama / OpenAI / Anthropic / Google — 역할별 환경변수 선택)
```

- **프론트엔드**: Next.js 16 (App Router, TypeScript, Tailwind v4) — 딥 그린 브랜드 디자인 토큰,
  Pretendard 가변 폰트(`next/font/local` 셀프호스팅), lucide-react 아이콘, 모바일 반응형 내비게이션
- **업무 API**: Kotlin + Spring Boot (`services/platform/`) — 인증·권한·저장·트랜잭션·작업 상태·자금/세금 계산
- **AI 서비스**: FastAPI (`services/intelligence/api/`, `services/intelligence/backend/`) — 분석·LLM·RAG와 별도 Python 실행기
- **파이프라인**: LangGraph (`services/intelligence/backend/`) — 시세추정·추천·시뮬레이션·비교·종합 컨시어지 그래프
- **의사결정 서비스**: 기존 케이스 스냅샷에서 근거·최신성·부족 정보를 결정론적으로 정리한다. 요약 조회는 LLM·외부 수집·분석 작업을 새로 실행하지 않는다.
- **저장소**: PostgreSQL 단일 인스턴스(`real_estate_db`) — 앱 테이블(사용자·이력·활동·캐시·
  지역코드·실거래가·상담 코퍼스, `services/intelligence/db/models.py`)과 RAG 벡터스토어(pgvector, `real_estate_docs`)가
  같은 컨테이너를 공유 + Redis(작업 큐 상태·레이트 리밋·로그인 잠금 카운터)
  — 둘 다 로컬 개발 포함 필수 (SQLite/인프로세스 메모리 폴백 없음, `sh scripts/compose.sh dev up pgvector redis`)

### 시세추정 실행 흐름 (비동기 job)

```
POST /api/appraisal/jobs               → { job_id } 즉시 반환
  └─ 백그라운드: LangGraph 파이프라인 실행
GET  /api/appraisal/jobs/{job_id}      → { status, step, ... }  (프론트 2초 폴링)
  └─ 완료 시: history DB 저장 → { status: done, history_id, result }
프론트 → /report/{history_id}          → 소유자 전용 영속 리포트 (새로고침·인쇄)
```

---

## 빠른 시작 (Docker Compose)

```bash
# 1. 최초 환경변수 설정 (.env가 이미 있으면 덮어쓰지 않는다)
cp .env.example .env
# .env 파일을 열어 API 키 + POSTGRES_PASSWORD + JWT_SECRET_KEY + INTERNAL_SERVICE_SECRET 입력
# 내부 서비스 키는 32자 이상의 무작위 값이며 JWT 키와 다른 값으로 설정한다.

# 2. 전체 서비스 실행 (Spring + Python + 실행기 + Next + Caddy + PostgreSQL + Redis)
sh scripts/compose.sh dev up --build

# 서비스 주소
# 프론트엔드: http://localhost:3002
# 백엔드 API: http://localhost:8002
# 실행·계약 안내: docs/backend-migration.md (Spring 공개 Swagger는 아직 없음)
```

`scripts/compose.sh dev`는 개발 오버레이를 명시적으로 병합한다. `local`은 베이스만, `production`은 HTTPS 운영 오버레이를 사용한다. 프로젝트 경로·이름을 고정하므로 루트 `.env`와 기존 DB·Redis 볼륨을 유지한다. PowerShell에서는 `./scripts/compose.ps1 dev up --build`를 사용한다.

**운영 기준 이미지 실행**은 override를 명시적으로 배제한다. 공개 HTTPS 배포에는
[운영 안내](docs/operations.md)의 별도 배포 파일과 서버·도메인 확인이 필요하다:

```bash
sh scripts/compose.sh local up -d --build
```

베이스 파일만 쓰면 소스는 이미지에 구운 것만 실행되고(볼륨 마운트 없음),
PostgreSQL·Redis 포트는 호스트에 노출되지 않는다(도커 내부 네트워크로만 통신).
`scripts/backup_db.sh`·`restore_db.sh`는 호스트 포트가 아니라 `docker exec`로
컨테이너 내부에 접속하므로 이 차이와 무관하게 그대로 동작한다.

### 로컬 개발

Python 의존성 설치 후 `./venv-wsl/bin/python -m pip install --no-deps -e services/intelligence`로 분석 패키지를 등록한다.

기본 Compose에서 Spring·Python·별도 실행기를 함께 실행한다. 전환된 회원·매물·케이스·작업 저장 및
고정 금융·세금 수식의 중복 Python 구현은 제거했다. Python 모듈은 내부 계약 클라이언트이며
`CORE_STORAGE_URL`과 32자 이상 내부 인증키가 필수다. Python만 띄우는 이전 실행법은 지원하지 않는다.

```bash
sh scripts/compose.sh dev up -d --build
./venv-wsl/bin/python scripts/run_isolated_tests.py tests/ -q
./venv-wsl/bin/python scripts/run_spring_tests.py --browser
```

테스트 실행기는 임시 Spring·Python 서비스를 만들어 `real_estate_test`·Redis 15를 실제로 확인한 뒤
검증하고 종료한다. 두 실행기를 동시에 돌리지 않는다. 서비스 DB·Redis에는 테스트를 연결하지 않는다.
원본 데이터·벡터스토어·Alembic·AI 분석은 Python에 남아 있다.

### 실거래가 배치 수집 (선택 — 응답 속도 대폭 개선)

시세추정은 로컬 스토어를 우선 조회하고, 미스 시에만 MOLIT API를 호출한 뒤 자동 적재한다(write-through).
자주 조회하는 지역을 미리 수집해두면 API 호출 없이 즉시 응답한다.

```bash
# 서초구·강남구 주거용 최근 12개월
python services/intelligence/backend/tools/ingest_transactions.py --regions 서초구,강남구 --months 12

# 서울특별시의 모든 자치구, 현재월 포함 최근 12개월 매매 원천 전체
python services/intelligence/backend/tools/ingest_transactions.py --sido 서울특별시 --months 12 --yes

# 기존 범위보다 이전·이후 월을 증분 수집 (완료된 월은 자동으로 건너뜀)
python services/intelligence/backend/tools/ingest_transactions.py --sido 서울특별시 --from 202401 --to 202508 --yes

# 등록된 전체 지역(수도권+광역시 약 60개), 주거용+상업용 6개월
python services/intelligence/backend/tools/ingest_transactions.py --all --categories 주거용,상업용

# 강제 재수집 / 스토어 현황 확인
python services/intelligence/backend/tools/ingest_transactions.py --regions 서초구 --force
python services/intelligence/backend/transaction_store.py
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
python services/intelligence/backend/tools/sync_legal_regions.py --dry-run

# legal_regions 테이블에 업서트
python services/intelligence/backend/tools/sync_legal_regions.py
```

`MOIS_REGION_API_KEY`가 있으면 우선 사용하고, 없으면 data.go.kr 공용 키인
`MOLIT_API_KEY`를 사용한다. 목록 API는 공식 폐지일을 제공하지 않으므로 이전
동기화에 있던 코드가 새 전체 목록에서 사라지면 비활성화만 하고 폐지일을 추정해
채우지 않는다.

---

## 폴더 구조

서비스 책임을 기준으로 구성한다. 상세 경계와 이동 후 검증은 [구조 안내](docs/repository-layout.md), 내부 명세는 [contracts](contracts/README.md)를 따른다.

```text
property_concierge/
├── services/
│   ├── platform/                인증·매물·케이스·거래·고정 계산·운영 API
│   │   ├── pom.xml              Kotlin/Spring Boot 빌드
│   │   └── src/                 도메인 구현·단위 테스트
│   └── intelligence/            AI·RAG·AVM·추천·데이터 분석
│       ├── api/                 내부 분석 API·작업 실행기·플랫폼 클라이언트
│       ├── backend/             분석 그래프·모델·검색·수집
│       ├── db/                  데이터 계층·공유 스키마 Alembic
│       ├── schemas/             분석 계약
│       ├── evaluation/          분석 품질 평가·정답셋
│       ├── requirements.txt
│       └── pyproject.toml
├── web/                         Next.js 사용자 화면
├── contracts/v1/                내부 API 명세·클라이언트 계약
├── infrastructure/
│   ├── compose/                 베이스·개발·HTTPS 운영 설정
│   ├── docker/                  서비스 이미지 정의
│   ├── proxy/                   Caddy 설정
│   └── database/                PostgreSQL 초기화
├── scripts/                     통합 검증·운영·Compose 실행 도구
├── tests/                       서비스 연결·보안·분석 회귀 테스트
├── docs/                        기획·인수인계·포트폴리오
├── data/                        샘플·보정 자료·수집 원문
├── backups/                     로컬 DB 백업 (Git 제외)
├── evaluation-results/          검증 산출물 (Git 제외)
└── .env                         로컬 설정 (Git 제외)
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
| `GET` / `POST` | `/api/cases` | 본인 매수 케이스 조회·생성 |
| `GET` | `/api/cases/{id}` | 공통 조건·후보·분석·체크리스트 |
| `GET` | `/api/cases/{id}/summary` | `case`·`comparison`·`decision`의 다섯 판단 축과 근거 |
| `GET` | `/api/cases/{id}/comparison` | 같은 평가 기준을 사용하는 후보 비교 |
| `POST` | `/api/cases/{id}/funding-scenarios` | 공통 조건을 적용한 후보별 자금 시나리오. 기존 분석·선택은 변경하지 않음 |
| `POST` / `DELETE` | `/api/cases/{id}/decision` | 사용자 선택 이유 저장·선택 해제 |
| `GET` | `/api/cases/{id}/execution` | 선택한 후보의 거래 준비 작업·일정 |
| `POST` | `/api/listings/import` | 본인 확인 매물 등록·변경 이력 |
| `GET` | `/api/listings/{id}/history` | 매물의 관측·변경 기록 |
| `POST` | `/api/listings/{id}/candidate` | 본인 매물을 케이스 후보로 저장 |
| `POST` | `/api/recommendation` | 샘플 매물 추천 실행 |
| `POST` | `/api/recommendation/complexes` | 실거래 기반 단지 추천 (행정구역 코드 조회 구조, 실제 저장·수집된 거래 범위에서 제공) |
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

> 위 경로는 Spring API와 호환된다. 내부 FastAPI의 Swagger는 내부 서비스 인증이 필요한 개발 환경에서 확인한다.
> Spring과 AI·데이터 서비스의 책임은 [백엔드 전환 안내](docs/backend-migration.md)를 참고한다.

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
| `DATABASE_URL` | 앱 테이블(사용자·이력·활동·캐시·실거래가·상담 코퍼스) — **필수, 폴백 없음** | `sh scripts/compose.sh dev up pgvector` |
| `REDIS_URL` | 작업 큐 상태·레이트 리밋·로그인 잠금 카운터 — **필수, 폴백 없음** | `sh scripts/compose.sh dev up redis` |
| `SENTRY_DSN` | 에러 추적 (선택, 비워두면 완전히 비활성 — 로컬·CI에 영향 없음) | [sentry.io](https://sentry.io) |

> 전체 환경변수 목록과 설명은 `.env.example` 참고.

LLM 프로바이더 (`services/intelligence/backend/model_factory.py`). 아래는 `.env.example`의 기본 양식이며
실행 환경의 현재 설정을 뜻하지 않는다. 생성 LLM과 임베딩 제공자는 별도로 설정한다:

| 환경변수 | 기본값 |
|---------|--------|
| `LLM_PROVIDER` | `ollama` (`openrouter` / `openai` / `anthropic` / `google` 지원) |
| `CHAT_LLM_PROVIDER` | 빈 값. 챗봇·종합 컨시어지만 전환하려면 `openrouter` |
| `APPRAISAL_INTENT_LLM_PROVIDER` | 빈 값. 시세추정의 주소·유형 자연어 추출을 전환하려면 `openrouter` |
| `EMBED_PROVIDER` | `ollama` 유지 권장: 기존 pgvector 임베딩과 같은 모델을 사용해야 함 |
| `OLLAMA_MODEL` | `qwen3.5:9b` |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | OpenRouter 선택 시 필수. 양식의 모델 ID는 `openai/gpt-6-luna`. 코드가 이 ID·`openrouter/free`·`:free`로 끝나는 ID만 허용 |
| `OPENAI_MODEL` / `ANTHROPIC_MODEL` | 프로바이더 전환 시 |

챗봇만 전환할 때는 `.env`에 `CHAT_LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY`와
`OPENROUTER_MODEL`을 설정한 뒤 백엔드와 작업 실행기를 재시작한다. 기존 법령 RAG 검색은
`EMBED_PROVIDER=ollama`와 원래 임베딩 모델을 유지한다. 검색으로 찾은 문서 조각과 질문은
답변 생성을 위해 선택한 OpenRouter 모델에 전송된다. 키나 모델이 비어 있으면 OpenRouter
호출을 시작하지 않고 설정 오류를 반환한다. OpenRouter 모델은 JSON 응답 형식을 지원하는지
확인해야 챗봇의 도구 선택이 안정적으로 동작한다.
시세추정에서도 주소·유형 검색 힌트를 추출하는 의도분석만 OpenRouter로 전환할 수 있다.
좌표·법정동코드·지번은 LLM 출력으로 확정하지 않고 카카오 주소 검색과 검증 규칙을 따른다.
모델 ID 허용 정책은 사용자가 지정한 설정을 반영한 코드의 제한이며 모델 제공 여부·가격·쿼터를
보증하지 않는다. 실제 사용 전 공급자의 모델 목록과 계정 상태를 확인한다.

> **카카오 403 오류** 발생 시: 개발자 콘솔 → 플랫폼 → Web → `http://localhost` 등록

---

## 스키마

모든 스키마는 `services/intelligence/schemas/` 디렉터리의 Pydantic 모델. **금액 단위: 원(int), 면적 단위: ㎡(float).**
(단, `services/intelligence/backend/models.py`의 `ValuationResult`는 만원 단위 — 리포트 생성 시 변환)

| 스키마 | 핵심 필드 |
|--------|----------|
| `PropertyQuery` | `intent`, `region`, `property_type`, `area_m2`, `budget_min/max`, `purpose` |
| `PropertyListing` | `listing_id`, `address`, `property_type`, `area_m2`, `asking_price`, `deposit_price`, `station_distance_m`, `built_year` |
| `AppraisalResult` | `estimated_price`, `low/high_price`, `confidence`, `appraisal_date`, `land_use_zone`, `official_land_price`, `exclusive_area_m2`, `valuation_breakdown`, `comparables`, `legal_restrictions`, `warnings` |
| `ComparableTransaction` | 시점수정(`time_adj_factor`)·지역/개별요인 보정 포함 비교사례 |
| `RecommendationResult` | `listing`, `total_score`, 4축 점수, `recommendation_label`, `reasons`, `risks` |
| `SimulationResult` | `acquisition_cost`, `loan`, `cash_flow`, `scenario_base/bull/bear` |
| `ComparisonResult` | `rows`, `decision_report` |
| `CaseDecisionAssessment` | `version`, `case_id`, `evaluated_at`, 후보별 다섯 판단 축·현재 비교 금액·다음 행동 |
| `DecisionAxis` | `key`, `status`, `headline`, `explanation`, `evidence`, `missing`, `limitations`, 검토 화면 연결. [공통 검토 기준](docs/decision-assessment.md) |

---

## 공개 API (Kotlin Spring Boot)

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
# state["result"].rows[0] — 샘플 점수 비교의 첫 행. 실제 케이스 후보 선택과는 별개
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

`services/intelligence/backend/reb_index.py` — R-ONE OpenAPI `SttsApiTblData` 사용, 통계표 `A_2024_00045` (월간 아파트 매매가격지수, 시군구 단위).

```
시점수정 계수 = 기준시점 월 지수 / 거래 월 지수
```

- **지역 매칭**: 시군구 정확 매칭 (동명이구는 시도로 판별) → 시도 → 전국 순 폴백
- **공표 시차 처리**: 지수는 익월 중순 공표 — 기준시점 월이 미공표면 최근 공표월까지 지수로 보정하고, 잔여 월수는 근사 변동률로 이어서 보정
- **캐싱**: 월별 전 지역 지수를 `cache.db`에 캐시 (완결 월 30일 / 최근 월 24시간)
- **동작 확인**: `python services/intelligence/backend/reb_index.py 서초구` — 키 상태·지수 조회·계수 산출 진단
- 통계표 교체: env `REB_STATBL_RESIDENTIAL` (주거용), `REB_STATBL_LAND` (토지)

### 비교사례 매칭 전략 (단계적 확장)

```
1) 단지명 정확/공백제거/부분 매칭 (3 → 6 → 12개월)
2) 동 필터링 (3 → 6개월)
3) 구 전체 (3 → 6개월)
4) 공시가격 역산 폴백 (주거용 한정)
```

### 백테스트 (AVM 정확도 실측)

`services/intelligence/backend/tools/backtest_avm.py` — 대상 월 거래를 이전 데이터만으로 추정(홀드아웃)해
실거래가와 비교하고, 버킷(매칭수준×표본수)별 적중률을 신뢰도 보정테이블로 저장한다.

```bash
python services/intelligence/backend/tools/ingest_transactions.py --regions 서초구 --months 12 --yes
python services/intelligence/backend/tools/backtest_avm.py --regions 서초구 --target-months 3
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

## 샘플 매물 추천 점수 모델

아래 점수는 개발용 샘플 추천 도구의 기존 모델이다. 사용자 매수 케이스는 다섯 판단 축과
근거·미확인 사항을 사용하며 이 점수로 자동 매수 결론을 내리지 않는다.

```
total = 가격적정성×0.35 + 입지×0.30 + 투자가치×0.20 + (10 − 위험도)×0.15
```

| 총점 | 8.0+ | 6.5+ | 5.0+ | 5.0 미만 |
|------|------|------|------|---------|
| 레이블 | 적극 추천 | 추천 | 검토 필요 | 비추천 |

### ⚠️ 샘플 매물 데이터 고지

샘플 추천·비교 도구의 매물 데이터(`data/sample_listings.csv`)는 **개발·테스트 전용 가상 데이터**
(서울 8개 구 43건)다. 가격·좌표·단지명은 임의 생성 값이며 실제 거래 판단에 사용할 수 없다.
반면 **시세추정은 국토부 실거래가 실데이터**를 사용한다. 매물 보관함과 매수 케이스는
사용자가 확인해 등록한 호가·조건을 사용하며 샘플 자료와 구분한다.

---

## 백업 · 복구

사용자 계정·시세추정 이력·활동 기록·실거래가 캐시·RAG 벡터스토어가 전부
`pgvector` 컨테이너 하나(`pgvector_data` 볼륨)에 있다. `sh scripts/compose.sh dev down -v`
또는 볼륨 손상 시 별도 백업이 없으면 전체 데이터가 복구 불가능하게 사라진다.

```bash
# 백업 — backups/ 에 타임스탬프 덤프 생성, 14일 초과분 자동 정리
./scripts/backup_db.sh
./scripts/backup_db.sh --out /mnt/backup --retention-days 30   # 저장 위치·보존기간 지정

# 운영 환경: cron으로 매일 새벽 실행
# 0 3 * * * cd /path/to/property_concierge && ./scripts/backup_db.sh --out /mnt/backup >> /var/log/pc_backup.log 2>&1

# 복구 — 대상 DB를 DROP 후 덤프로 재생성 (되돌릴 수 없음, 확인 프롬프트 있음)
./scripts/restore_db.sh backups/property_concierge_20260725_030000.dump
sh scripts/compose.sh dev restart api   # 커넥션 풀 재연결
```

두 스크립트 모두 `.env`의 `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`를 읽고,
`property_concierge_pgvector` 컨테이너([infrastructure/compose/compose.yml](infrastructure/compose/compose.yml)의
`container_name`)에 대해 `pg_dump`/`pg_restore`를 실행한다. 컨테이너 이름을 바꿨다면
스크립트 안의 이름도 함께 바꿔야 한다.

> 백업 파일(`backups/`, `*.dump`)은 `.gitignore`에 등록돼 있다 — 사용자 개인정보가
> 담긴 덤프를 저장소에 커밋하지 않도록 주의할 것.

---

## 스키마 마이그레이션 (Alembic)

앱 테이블(`services/intelligence/db/models.py`)의 스키마 변경 이력은 `services/intelligence/db/migrations/`가 관리한다.
운영 배포는 `alembic -c services/intelligence/alembic.ini upgrade head`가 uvicorn 워커보다 먼저, 단일 프로세스로
실행된다([infrastructure/docker/Dockerfile.intelligence](infrastructure/docker/Dockerfile.intelligence)) — 여러 워커가 동시에 스키마를
바꾸려는 경합 자체를 원천 차단하기 위해서다.

```bash
# 모델(services/intelligence/db/models.py) 변경 후 마이그레이션 생성
alembic -c services/intelligence/alembic.ini revision --autogenerate -m "설명"
# 생성된 services/intelligence/db/migrations/versions/*.py 파일을 반드시 검토할 것 —
# autogenerate는 인덱스명·서버 기본값 등을 놓치거나 과도하게 잡아낼 수 있다.

# 로컬 DB에 적용
alembic -c services/intelligence/alembic.ini upgrade head

# 현재 DB가 어느 리비전인지 확인
alembic -c services/intelligence/alembic.ini current
```

`create_all()`(`services/intelligence/db/base.py`)은 alembic 없이 `uvicorn`을 직접 띄우는 로컬 개발·
테스트 경로를 위한 안전망으로 남겨뒀다 — 정상 배포 경로에서는 alembic이 먼저
스키마를 확정하므로 `create_all()`은 아무 일도 하지 않는다(이미 존재하는
테이블은 건드리지 않음). 다만 `create_all()`은 컬럼 삭제·타입 변경처럼
alembic이 다루는 변경은 반영하지 못하므로, 그런 변경은 반드시 마이그레이션을
거쳐야 한다.

---

## 테스트

```bash
# 테스트는 테이블을 비우므로 실행 중인 서비스 DB가 아닌 격리 DB를 사용한다.
sh scripts/compose.sh dev up -d pgvector redis

./venv-wsl/bin/python scripts/run_isolated_tests.py tests/ -q  # 격리 DB 생성·마이그레이션·전체 테스트

# 주요 파일
./venv-wsl/bin/python scripts/run_isolated_tests.py tests/test_price_engine_calc.py
./venv-wsl/bin/python scripts/run_isolated_tests.py tests/test_transaction_store.py
./venv-wsl/bin/python scripts/run_isolated_tests.py tests/test_rights_and_chat.py
```

`tests/conftest.py`는 `real_estate_test`와 Redis DB 15가 아니면 실행을 거부한다.
실행기가 만든 Spring 주소는 `TEST_CORE_URL`과 일치해야 하고, 내부 점검에서 실제 연결된 DB 이름과
Redis 번호를 대조한다. `TEST_DATABASE_URL`·`TEST_REDIS_URL`만 바꿔 운영 Spring을 호출할 수 없다.

GitHub Actions(`.github/workflows/ci.yml`)에서 push·PR마다 postgres·redis 서비스 컨테이너와
함께 전체 스위트를 실행한다.

### 별도 평가·검증 도구

`services/intelligence/evaluation/`에서 핵심 매수 의사결정 상태·AVM 백테스트·종합 컨시어지 의도 추출과 계산기·RAG·법률 챗봇을 공통 JSON·HTML 보고서로 평가한다.
기존 회귀 테스트와 함께 사용하며, 자동 검사와 사람 채점을 구분한다. [실행·데이터셋·결과 해석 안내](services/intelligence/evaluation/README.md)를 참고한다.

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
CI에는 외부 호출 없는 의사결정·가상 AVM·의도·계산·검색 평가와 격리 API의 브라우저 흐름을 포함한다. 실제 모델·현재 매물 원문·실거래 AVM 정확도와 사람 검토는 별도 평가다.

최근 구현 검증 기록은 [후보별 의사결정 검토 기준](docs/decision-assessment.md#검증-범위)에 남긴다. 통합 요약은 `scripts/verify_decision_assessment_browser.cjs`, 자금 입력 전달은 `scripts/verify_candidate_funding_browser.cjs`로 확인한다. `evaluation-results/`의 로컬 성공 기록과 원격 GitHub Actions 성공을 구분한다.

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
- **시세추정·단지 추천의 행정구역 조회 구조는 전국 시군구 기준** — 지역코드 시드와 지오코딩을 사용하되 결과는 실제 저장·수집된 거래 범위에 한정된다. 현재 정기 수집은 서울 25개 구 매매 거래에 적용했으며 전국 데이터·동일 정확도 확보를 뜻하지 않는다.
- **Vworld 토지 보강은 선택 데이터** — 키와 HTTP 호출이 정상이더라도 좌표에 따라 `NOT_FOUND`가 반환될 수 있으며, 이때 용도지역·공시지가는 빈 값으로 유지
- **사용자 선택 유형이 공식 주용도보다 우선** — LLM 오분류 방지를 위한 현재 정책. 건축물대장과 충돌할 때 UI 경고를 표시하는 기능은 아직 없음
- **단지 추천**은 실거래 기반 후보 탐색이며 실제 광고 매물의 존재·호가를 포함하지 않는다. 사용자가 확인한 호가 매물은 보관함에 직접 등록해 검토할 수 있으며, 자체 광고 매물 DB 확대는 공급자 등록·공식 제휴의 후속 계획이다. 샘플 모드는 개발용 가상 데이터다.
- **근거가 없는 조건은 미확인** — 통근·학군·소음·주차, 후보 준공연도, 문서 발급일·페이지별 근거, 동일 개별 호 식별은 현재 통합 화면이 완전히 검증하지 않는다. 자료 부족을 높은 적합성이나 권리 안전성으로 채우지 않는다.
- **장기 기획은 구현 완료와 구분** — Listing Time Machine 전용 집계 화면, Buyer Decision Graph의 선호 학습, 범용 Property 객체와 공급자 Marketplace·직거래는 후속 계획이다. 기본 거래 준비 체크리스트는 실제 계약·대출·등기 업무의 완료를 뜻하지 않는다.
- **로컬 개발도 Docker(PostgreSQL·Redis) 필수** — SQLite·인프로세스 메모리 폴백을 두지 않는다. 테스트는 보호된 격리 DB·Redis에서 수행한다.
- **비밀번호 재설정 메일은 아직 실제로 발송되지 않는다** — `RESEND_API_KEY` 미설정 시 서버 로그에 재설정 링크를 출력하는 폴백만 동작. 실발송하려면 Resend 도메인 인증(SPF/DKIM)이 필요
- **공개 HTTPS 운영은 미적용** — Caddy·운영 배포 설정은 준비했지만 공개 서버·도메인의 인증서·외부 접속·프록시 신뢰 IP를 확인해야 한다. 설정 준비와 실제 운영 적용을 구분한다. [운영 안내](docs/operations.md) 참조.
