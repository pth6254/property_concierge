# Kotlin Spring · Python 백엔드 분리

기준일: 2026-10-01. 백엔드 전환 언어는 **Kotlin**이다. Spring의 사용자·저장·권한·거래 상태와
Python의 LLM·RAG·AVM·의사결정 분석을 분리한다. 자금·세금의 고정 수식 계산은 Kotlin이다. 모바일 앱은 이후 단계다.

## 현재 실행과 전환 범위

기본 실행은 웹 3002 → Caddy → Kotlin Spring이며 공개 API 8002도 Spring이다.
Next.js는 내부 3000, Spring은 8080, Python은 8000에서 실행한다. Python에는 공개 포트가 없다.
`/api/*`는 Caddy가 Spring으로 직접 전달하고 Next 서버의 내부 API 대상도 Spring이다.
같은 PostgreSQL 스키마를 사용하며 이 단계에서 데이터를 다른 DB로 복사하지 않는다.

```text
Next.js / API 클라이언트
    ↓ 기존 경로와 호환되는 /api
Kotlin Spring
    ├ 사용자 인증·소유자 확인·매물 검색 조건
    ├ 사용자 매물·케이스·후보·선택·거래 준비 트랜잭션
    ├ 분석 이력·매물 관측 기록·Redis 작업 상태
    ├ 대출·세금·현금흐름·수익·자금 부족 계산
    └ 내부 REST → Python
                    ├ CSV 정규화 (주소 증명 확인은 Spring 호출)
                    ├ 소유자 확인된 스냅샷의 다섯 판단 축·비교·다음 행동
                    ├ 기존 AVM·권리·LLM·RAG 실행
                    └ 자금 조건 해석·리포트 표현 → Spring 계산 계약
Python 별도 실행기 → Spring 내부 저장 계약 → PostgreSQL / Redis
```

Spring이 직접 제공하는 공개 경로는 가입·로그인·내 정보·로그아웃, 매물 조회·CSV 저장,
매수 케이스·후보·비교·요약·선택·원본 변경 재검토·체크리스트·거래 준비 작업,
작업 상태 조회와 `/api/jobs/{job_id}/events`다.
`POST /api/simulation`도 Spring이 입력·소유자 확인·계산·결과 저장을 제공한다. Python은 계산된 결과의 기존 리포트 표현만 생성한다.
OAuth·비밀번호 재설정·메일·탈퇴·주소 조회·이력·활동·신고·운영·재수집·AI 작업 접수도 Spring이다.
추천·AVM·권리·챗봇 공개 요청은 Spring이 인증하고 명시적인 내부 분석 경로로 호출한다.
범용 `/api/**` 중계 컨트롤러와 Python 일반 API·인증·주소·레이트 리밋 파일 **16개**를 삭제했다.
Python은 `/api`를 제공하지 않는다. 서비스 키 검증은 개발 환경에서도 필수다.
경로 재도입은 `scripts/audit_python_routes.py`가 실패로 처리한다. 호환 모듈은 AI가 사용하는 내부 호출 계약만 유지한다.
`scripts/audit_backend_cleanup.py --containers property_concierge_backend property_concierge-job-worker-1`은
46개 저장·17개 계산 계약에 실행 구현이 남지 않았는지와 컨테이너의 관련 모듈이 원본과 일치하는지 확인한다.

## 저장 책임 설정

`CORE_STORAGE_URL`과 내부 인증키는 Python API·실행기에도 필수다. 아래 Python 모듈은 함수 계약만
보존한 Spring 클라이언트이며 중복 SQL 저장 구현을 제거했다. 미설정·연결 실패는 503이고 Python SQL로 대체하지 않는다.
케이스 스냅샷의 순수 표현·근거 분석은 `case_snapshot_presentation.py`에 분리했다.

| 영역 | Python 호환 모듈 | Spring 저장 구현 |
|---|---|---|
| 회원·비밀번호 버전 | 실행 Python 모듈 없음 | `AccountStore`·`SessionService`·`AccountLifecycleController` |
| 케이스·후보·관심 지역·선택 | `services/intelligence/api/case_db.py` | `CaseStore` |
| 거래 준비 일정·작업 | `services/intelligence/api/case_execution_db.py` | `ExecutionStore` |
| 매물·가격 변경 이력 | `services/intelligence/backend/services/listing_store.py` | `ListingService` |
| 수집 시도·관측 | `services/intelligence/backend/services/listing_observations.py` | `ListingObservationStore` |
| AVM·활동 이력 | `services/intelligence/api/history_db.py`·`services/intelligence/api/activity_db.py` | `AnalysisHistoryStore` |
| 작업 접수·진행·완료 | `services/intelligence/api/jobs.py` | `AiJobStore` |

API와 별도 Python 실행기에 같은 `CORE_STORAGE_URL`·`INTERNAL_SERVICE_SECRET`을 적용해야 한다.
한쪽만 전환해서 양쪽 프로세스가 같은 영역을 직접 저장하게 만들지 않는다.
기본 Docker 실행은 API와 실행기에 같은 저장 주소를 주입하고 Python에 `REQUIRE_INTERNAL_SERVICE_AUTH=1`을 설정한다.
`.env`의 수동 실행 설정을 바꿔도 Compose의 영역별 저장 책임은 바뀌지 않는다.
분석에 쓰는 국토부 거래·법령 벡터·임베딩·전용 분석 캐시는 Python 영역에 남긴다.
Alembic이 스키마를 먼저 적용하며 Spring은 자동 DDL을 하지 않는다.

## 내부 계약과 null 처리

내부 REST는 `X-Internal-Service-Key`로 인증한다. 32자 이상의 무작위 키가 필요하며
내부 인증키는 Spring·Python에 동일하게 설정한다. JWT 인증은 Spring만 수행한다.
Python은 브라우저 쿠키를 받지 않고 서비스 키와 `X-AI-User-Id`를 받는다. 브라우저에 내부 키를 전달하지 않는다.
주소 증명 검증은 `/internal/v1/addresses/verify`로 Spring을 호출한다. 기존 토큰의 서명·소유자·만료 계약을 유지한다.
Spring → Python은 `/internal/v1/listing-import/validate`, `/decision/decorate`, `/decision/assess`, `/appraisal/summary`를 사용한다.
이 경로는 전달받은 지역·소유자 확인된 스냅샷·결과를 처리하며 DB 조회·저장을 하지 않는다.
Python → Spring은 `/internal/v1/store/{영역}/{작업}`을 사용한다.
Python API 기동은 주소·키만 검증한다. 기동 중 Spring 응답까지 기다리면 Spring의 Python 준비 상태 의존과
순환 대기가 생기므로, 실제 호출 시 연결 실패를 처리한다. 테스트는 기동 후 `/internal/v1/testing/storage`에서
실제 `real_estate_test`·Redis 15인지 확인한다. 이 점검은 운영 저장소에서 403으로 거부한다.
계산은 `/internal/v1/calculations/{작업}`을 사용한다. [계산 책임](calculation-architecture.md)에서 수식·모델의 경계를 확인한다.
챗봇에서 후보 자금 분석을 실행할 때는 `/internal/v1/simulation`을 사용한다. 공개 실행과 같은
`SimulationController.execute`가 사용자·후보 소유권을 확인하고 변경 전 입력을 캡처한 뒤 계산·저장한다.
원격 리포트 처리 중 후보가 삭제되거나 입력이 변경되면 저장 성공으로 반환하지 않는다.

필수 문자열·숫자는 non-null이고 미확인 금액·대출 조건은 nullable다. 미확인을 0으로 채우지 않는다.
Jackson이 JSON null을 0·false로 바꾸거나 `List<String>` 안에 null을 넣는 것을 차단한다.
등록 요청은 Kotlin DTO와 Bean Validation으로 형식·범위를 확인하고, 변경 요청은 누락과 null을 구분한다.
알 수 없는 필드와 소수 금액을 거부한다. 기존 금액 단위 원·면적 단위 ㎡, AVM 만원 변환을 유지한다.
Python에서 넘어온 CSV 정수도 64비트 범위를 검사해 Kotlin 변환 중 금액이 바뀌는 것을 막는다.
내부 저장 계약의 일부는 아직 JSON 스냅샷을 사용하므로 전체 도메인이 Kotlin 타입으로 완전히 모델링된 상태는 아니다.

케이스 조회는 짧은 읽기 전용 REPEATABLE READ 트랜잭션에서 예산·후보·분석·원본 상태를 모은다.
DB 연결을 반환한 뒤 Python 분석을 호출한다. 동시에 가격·예산을 수정해도 서로 다른 시점의 값이 섞이지 않게 한다.

## 실행과 검증

`.env.example`의 내부 인증키를 설정한 뒤 기본 서비스를 실행한다. 아래 명령은 기존 개발 DB 포트와
마운트를 유지한다. `sh scripts/compose.sh dev config`의 전체 출력은 키를 노출할 수 있으므로 보관하지 않는다.

```bash
sh scripts/compose.sh dev up -d --build
./venv-wsl/bin/python scripts/check_compose_contract.py
./venv-wsl/bin/python scripts/run_isolated_tests.py tests/ -q
./venv-wsl/bin/python scripts/run_spring_tests.py --browser
```

Spring 검증은 PostgreSQL `real_estate_test`·Redis 15와 임시 API·Spring·실행기만 사용한다.
브라우저 검증은 임시 Next.js와 검사 중 생성한 계정을 사용하며 종료 시 계정과 컨테이너를 제거한다.
Python 테스트와 Spring 검증은 같은 격리 DB를 공유하므로 순서대로 실행한다.
실제 서비스 DB·Redis에서 pytest를 실행하지 않는다.

API 통합 검증 산출물은 `evaluation-results/spring-core-result.json`이다.
검증 내용은 JWT·bcrypt 양방향 호환, 소유자 404, CSV 미리보기·저장·전체 롤백·시점 관리,
후보·분석·선택·가격 변경 재검토·복원, 작업 큐·별도 실행기·SSE, 관측 실패의 가격 보존,
비밀번호 변경 후 일반·AI 공개 경로 JWT 무효화다. AVM은 고정 결과로 저장·단위 변환을 검증했고 자금 계산은 실제 계산기를 사용한다.
실제 AVM 정확도·LLM 대화 품질·외부 매물 추출 성공률을 검증한 결과는 아니다.
SSE는 작업 상태 전송이며 LLM 토큰 스트리밍은 아직 구현하지 않았다. 현재 프론트엔드는 기존 폴링을 유지한다.

기본 Caddy는 클라이언트가 전달한 IP 헤더를 신뢰하지 않는다. Spring은 고정 Caddy 주소만,
Python은 고정 Spring 주소만 신뢰한다. 사설망 전체나 `*`를 허용하지 않는다.
`spring-gateway-result.json`은 직접 접속과 Caddy 경유 각각의 위조 헤더 11회 요청에서
열한 번째가 429이며 동일 클라이언트 제한이 유지되는지 확인한다. 운영 감시기는 Spring의 생존도 확인한다.
HTTPS 배포 파일은 Spring 직접 포트를 없애고 80/443만 공개한다. 실제 서버·도메인 배포는 별도 작업이다.

### 2026-10-01 검증 기록

- Python 전체: **1,086개 통과·1개 건너뜀**. `real_estate_test`와 Redis 15만 사용했다.
- Kotlin 단위: **9개 통과**. JWT·비밀번호 버전·JSON null·금액·DB/Redis 설정을 검증했다.
- Spring/Python 통합: **18개 항목 통과**(동시 수정 중 조회 일관성 포함), 프록시 위조 방어 **2개 항목 통과**.
- 격리 브라우저: 매물 등록 **9개**, 이동 **7개**, 자금 **13개**, 의사결정 **13개**, 총 **42개 항목 통과**.
- 프론트엔드 타입·린트·Docker 프로덕션 빌드 통과. 로컬/HTTPS Compose의 포트·저장 책임 설정 검사 통과.
- 실제 웹 3002: 조건 저장·탐색 입력·계산 결과 표시·후보·의견·화면·복원 **7개 항목 통과**.
- 실행 서비스 연결 **4개 항목 통과**: 설정 일치·가입 쿠키·Python 직접 요청 차단·실제 실행기 결과 저장과 Caddy SSE.
  산출물은 `evaluation-results/spring-deployment-result.json`이다. 생성한 검증 계정은 삭제했다.

검증 전 서비스 DB 백업을 생성했다. 실제 서비스의 DB·Redis 볼륨을 교체하거나 다른 DB로 복사하지 않았다.
원격 GitHub Actions 실행 성공이나 실제 AVM·LLM·권리 판독 정확도 검증을 뜻하지 않는다.

같은 날 자금·세금 계산을 Kotlin으로 이전한 후 Python **1,092개 통과·1개 건너뜀**, Kotlin **18개 통과**로 갱신했다.
Spring 통합 18개·프록시 2개·격리 브라우저 42개도 다시 통과했고 계산 연결 6개 항목을 추가했다.
기존 수식 54개 조건의 전체 결과 대조는 금액 차이 0원이었다. 상세 범위는 [계산 검증 기록](calculation-architecture.md#2026-10-01-계산-이전-검증-기록)을 따른다.
Docker 재빌드 후 실제 웹 자금 흐름 13개·계산 연결 4개·실행 서비스 연결 4개를 확인했다.

### 2026-10-01 중복 Python 구현 제거 후 검증

회원·매물·관측·케이스·거래 준비·분석/활동 이력·작업 상태의 Python SQL 구현과
금융·세금 수식을 제거하고 내부 계약 클라이언트만 유지했다. 원본 데이터·벡터스토어·AI 분석·Alembic은 남겼다.
기존 수식 54건의 전체 결과는 고정 자료로 보존하며, Python 회귀 테스트도 격리 Spring을 호출한다.
HTTP 왕복에서 같은 숫자의 Jackson 노드 타입 차이를 후보 변경으로 오인하던 비교도 수정했다.

- Python **1,092개 통과·1개 건너뜀**, Kotlin 단위 **19개 통과**.
- Spring 통합 **18개**, 계산 연결 **6개**, 프록시 **2개** 통과. 고정 계산 54건의 금액 최대 차이 **0원**.
- 격리 브라우저 6종 **56개 항목** 통과: 매물 9·이동 7·품질 7·자금 13·판단 축 13·주소/별칭 7.
  주소 응답·단지·거래 자료는 가상이며 실제 주소 공급자 정확도의 검증이 아니다.
- 오프라인 평가 **34건 통과**. 실시간 LLM 답변·외부 법령/실매물 품질 검증을 뜻하지 않는다.
- 프론트엔드 타입·린트·프로덕션 빌드 및 Compose 계약 검사 통과.
- Docker 반영 후 실행 서비스 연결 **4개**, API/실행기 계산 연결 **4개** 통과. 검증 계정은 삭제했다.

### 2026-10-01 중복 HTTP 핸들러·요청 스키마 제거 후 검증

가입·로그인·내 정보·로그아웃, 케이스 CRUD·후보·선택·거래 준비, 매물 조회·CSV 등록,
자금 실행·작업 상태의 중복 **33개 Python HTTP 경로**를 삭제했다. 사용하지 않는 CRUD 요청
스키마·로그인 잠금 구현·Python 자금 저장 분기도 제거했다. 공유 자금 입력은 별도 스키마로 옮겼다.
OAuth·재설정·탈퇴·주소·직접 등록·관심 지역·AI 분석은 여전히 사용 중인 Python 경로다.

- Python **1,098개 통과·1개 건너뜀**, Kotlin **25개 통과**. 기존 소유자 격리·세션 무효화 검증은 유지했다.
- 기존 HTTP 회귀 테스트의 이전된 경로는 실제 격리 Spring을 호출한다. Python에 임시 핸들러를 다시 만들지 않았다.
- 삭제 중 발견한 매물 수집 작업의 비로그인 조회 차이를 수정해 기존 **401** 정책을 유지했다.
- 계산 중 후보 삭제·가격 변경을 Kotlin 단위에서 검증하고 내부 서비스 인증 실패·잘못된 결과를 Python에서 성공으로 처리하지 않게 했다.
- Spring 통합 **18개**·계산 연결 **6개**·프록시 **2개**, 브라우저 **56개**, 오프라인 평가 **34건** 통과.
- 프론트엔드 타입·린트·빌드 통과. Docker 반영 후 실행 서비스 **4개**·계산 연결 **4개** 통과.
- 원본 코드와 API·작업 실행기의 **26개 모듈** 일치, **52개 저장·17개 계산** 계약에 중복 구현 없음,
  **중복 HTTP 경로 0개**를 확인했다. `evaluation-results/cleanup-code-audit.json`에 기록했다.

검증 자료는 `backend-junit.xml`, `kotlin-route-tests/`, `spring-core-result.json`,
`core-calculations-result.json`, 브라우저 보고서, 실행 서비스 보고서에 보존한다.
외부 주소·법령·실매물·실시간 LLM 답변의 실제 품질과 원격 GitHub Actions 성공은 별도 검증 범위다.

### 2026-10-01 일반 백엔드 Kotlin 이전 완료

OAuth·비밀번호 재설정·메일·탈퇴·주소 검색/서명·이력·활동·신고·운영 화면·재수집·AI 접수를
Spring으로 옮겼다. Python 일반 API·인증·주소·레이트 리밋 파일 16개와 범용 중계 컨트롤러를 삭제했다.
기존 JWT·bcrypt·주소 증명은 `tests/legacy_*` 자료로 Spring 호환성을 검증하며 실행 서비스에서 임포트하지 않는다.
Python의 HTTP는 내부 AI·데이터·스냅샷 분석이고 서비스 키를 항상 검증한다.

- Python 회귀 **1,095개 통과·1개 건너뜀**, Kotlin 단위 **25개 통과**.
- Spring 통합 **18개**, 실제 계산 연결 **6개**, 프록시 위조 방어 **2개**, 브라우저 6종 **56개 항목** 통과.
- 오프라인 평가 **34건**, 프론트엔드 타입 검사·린트·빌드 통과.
- Docker 재빌드·재기동 후 실제 서비스 연결 **4개**와 실제 카카오 주소 공급자 연결 **1개** 통과.
- Spring 공개 경로 **81개**, Python 공개 업무 경로 **0개**, 대체된 파일 잔존 **0개**를 확인했다.
  API·실행기 관련 **29개 모듈**이 원본과 일치하며 저장 **46개**·계산 **17개** 내부 계약에 중복 구현이 없다.

산출물: `general-migration-backend-junit.xml`, `general-migration-kotlin-reports/`,
`spring-core-result.json`, `core-calculations-result.json`, 브라우저 보고서,
`spring-deployment-result.json`, `spring-address-deployment-result.json`, `cleanup-code-audit.json`.
OAuth의 실제 Google 계정 콜백과 Resend 실발송은 검증하지 않았다. 주소 공급자 연결은 확인했으나
개별 호·실매물 존재·호가 및 실제 LLM·AVM 정확도를 검증한 결과는 아니다.

## 후속 고도화

1. 입력·결과 스냅샷의 계약 버전과 DTO를 보강하고 케이스 저장 함수를 영역별 서비스로 나눈다.
2. 실제 AVM·권리 문서·실거래 사례와 공개 배포 환경의 장애·복구를 별도로 평가한다.
3. 장기적으로 스키마 관리와 AI 전용 데이터 접근 계정도 분리한다. 현재 Alembic은 공유 스키마의 단일 관리 도구다.

지역·권리·금액의 부족한 사실을 추정으로 메우거나 기존 수치 가드레일·작업 복구 규칙을 제거하지 않는다.
