# 운영·배포·복구·데이터 갱신

관리자 권한, 준비 상태·알림, 백업·배포, 로컬 접속 유지, 작업 복구와 실거래 갱신 절차를 관리한다. 설정 준비와 실제 운영 적용을 구분한다.

[문서 목록](README.md)

- [관리자 화면·감시·백업·검증](#administration)
- [Windows·WSL 접속 유지](#local-runtime)
- [작업 복구와 실행기](#job-recovery)
- [실거래 주기 갱신](#transaction-refresh)

<a id="administration"></a>

## 관리자 화면·감시·백업·검증

`OPERATOR_USER_IDS`에 기존 계정의 ID를 지정하고 API를 재시작한다. 미설정이면 운영 API에 접근할 수 없다.
관리자 승격은 이메일 문자열이나 신규 가입 순서로 결정하지 않는다. `admin@admin.com`의 기존 계정에 권한을 지정했으며
ID는 로컬 `.env`에만 저장한다. 로그인 후 메뉴 하단의 **운영 관리**(`/operations`)에서 확인한다.
모든 운영 API는 서버에서 권한을 검사하며 재처리 작업은 생성한 운영자 본인만 조회한다.

<a id="administration-비교-조건추천-자금사용-안내"></a>

### 비교 조건·추천 자금·사용 안내

동네 탐색에서 면적·준공연도 범위·조회 기간을 선택하면 같은 조건의 거래로 통계를 계산한다.
연식이 미상인 거래는 연식 필터를 적용한 집계에서 제외된다. 표본 수준은 거래 건수 기준이며
예측 정확도가 아니다. 5건 미만 지역은 순위 판단 보류로 표시한다. 가격 범위는 25~75% 분포다.
케이스를 연결하면 저장된 예산·면적·연식·기간을 동네와 단지 추천에 함께 사용한다.
조건을 변경하려면 케이스의 공통 매수 조건에서 저장한 뒤 탐색의 조건 적용을 누른다.

단지 추천은 공통 금융 조건과 기존 계산기로 실거래 평균가 기준 필요 현금·월 상환액을 계산한다.
비상자금을 제외하며 자금 부족·월 상환 한도·계산기의 대출 기준 초과를 경고한다.
현금 또는 월 상환 우선순위에서는 해당 부담을 순위에 적용한다. 이 값은 실제 매물 호가나
대출 승인 결과가 아니며 실제 후보 등록에는 사용자가 확인한 면적과 희망가가 계속 필요하다.
케이스 화면의 6단계 안내는 다음 입력·탐색·분석 화면으로 연결되며 거래 안전 판정이 아니다.
관심 지역을 저장할 때도 케이스의 면적·연식 필터를 적용하며, 저장 당시 조건을 통계 스냅샷에 보관한다.

<a id="administration-운영-품질-지표와-사용자-의견"></a>

### 운영 품질 지표와 사용자 의견

운영 관리에 최근 7일 HTTP·작업 실패, 평균 처리 시간, p95 히스토그램 상한과
단계별 고유 사용자 수를 표시한다. HTTP 실패는 5xx, 작업 실패는 완료 상태의 오류 기준이다.
작업 시간은 접수부터 완료까지이며 큐 대기도 포함한다. 요청 본문·IP·주소·실제 URL ID를
지표 키에 넣지 않고 사용자 식별은 해시로 집계한다. Redis 집계는 35일 뒤 만료된다.
단계 집계는 같은 코호트의 전환율이 아니며 지표 기록 실패가 사용자 작업을 실패시키지 않는다.

로그인 사용자는 화면 아래에서 문제·개선 의견을 보낼 수 있다. 개인정보 입력을 피하도록
안내하며 자기 의견만 조회할 수 있다. 운영자는 최근 100건을 접수·검토 중·처리 완료로 관리한다.
의견은 PostgreSQL에 저장하고 계정 탈퇴 시 함께 삭제한다. 외부 메시지를 자동 발송하지 않는다.

<a id="administration-정기-백업https외부-감시"></a>

### 정기 백업·HTTPS·외부 감시

`maintenance` 프로필에 `database-backup`을 추가했다. 첫 실행 및 기본 하루 간격으로
DB custom-format 백업을 생성하고 `pg_restore --list`로 파일을 확인한다. 저장 성공 후에만
완성 파일로 교체하며 운영 화면에 마지막 시각·용량·실패·26시간 경과를 표시한다.
목록 읽기 성공은 실제 복원 성공과 다르다. 기존 격리 복원 절차를 주기적으로 수행하고,
백업을 다른 호스트에도 보관해야 한다. 자동 삭제는 하지 않는다.

```bash
sh scripts/compose.sh dev --profile maintenance up -d database-backup
# 도메인 DNS와 공개 서버가 준비된 후 development override 없이 실행
sh scripts/compose.sh production --profile maintenance up -d --build
```

운영 파일은 Caddy HTTPS와 같은 출처 API를 제공하고 API 직접 노출을 제거한다.
`SERVICE_DOMAIN`이 필요하다. Spring은 고정 gateway IP만 신뢰하고 Python의 `FORWARDED_ALLOW_IPS`는 고정 Spring IP만 신뢰한다.
로컬 웹 3002도 Caddy를 통과하며 `/api/*`를 Spring으로 전달한다. Next 서버의 내부 요청 대상도 Spring이다.
이 파일 작성만으로 공개 서버·DNS·인증서 발급이 완료되는 것은 아니다.

호스트 밖에서 `python scripts/check_external_readiness.py --url https://실제도메인/ready`를 실행한다.
웹훅을 설정한 경우에만 상태 전환 알림을 보내며 URL과 토큰은 로그에 출력하지 않는다.
GitHub의 별도 readiness workflow는 `EXTERNAL_READINESS_URL` 저장소 secret을 설정한 경우
15분마다 검사한다. URL 미설정은 비활성이며 외부 감시 성공으로 해석하지 않는다.

<a id="administration-2026-09-30-적용-검증"></a>

### 2026-09-30 적용 검증

- 격리 DB·Redis에서 백엔드 전체 984개 통과, 1개 건너뜀. 이후 관심 지역 저장 조건을 추가하고 관련 35개 검사를 다시 통과했다.
- 실제 Docker 서비스에서 브라우저 7개 항목 통과: 조건 저장·동네 집계 입력·추천 10개 자금 계산·후보 저장·의견 저장·모바일 표시·새로고침 복원.
- 실제 법령 검색은 30개 사례 통과. 공식 코퍼스 기반 정답 조문을 검색하는 평가이며 독립 전문가의 답변 정확도 평가가 아니다.
- 실제 주거 AVM 계산 경로 재생은 서초·강남·노원 30개 표본, MAPE 8.8%, ±10% 적중률 60%, 추정 범위 적중률 66.7%.
  현재 외부 시설·웹·LLM은 제외했고 시점수정은 근사율이다. 작은 표본의 수치를 전체 서비스 정확도로 일반화하지 않는다.
- 자동 백업 첫 생성과 파일 목록 읽기 성공. Caddy 설정 문법 검증 통과. 공개 DNS·인증서 발급·다른 호스트에서의 감시는 미실행.
- CI와 같은 격리 환경에서도 기존 이동 7개·새 품질 7개 항목 통과. 이 과정에서 조건 저장 후 폼 재생성으로 완료 안내가 사라지는 문제를 수정했다.

```powershell
# 실행 중인 로컬 서비스: 검증용 계정·가상 후보만 만들고 종료 시 삭제한다.
$env:E2E_BASE_URL='http://localhost:3002'
node scripts/verify_service_quality_browser.cjs
```

CI는 보호된 `real_estate_test`에 가상 거래를 준비한 뒤 동일 브라우저 검증을 수행한다.
실제 서비스 데이터로 돌린 결과와 CI 가상 거래 결과는 검증 범위가 다르다.
브라우저 증거는 `evaluation-results/service-quality-browser.json`과 화면 이미지에 저장한다.

<a id="administration-준비-상태와-알림"></a>

### 준비 상태와 알림

- `/health`: API 기동 확인. Docker 시작 순서에 사용한다.
- `/ready`: Spring·Python의 DB·서울 법정동 기준정보·Redis·실행기·큐가 정상일 때 200, 그 외 503. 공개 응답에는 상태만 반환한다.
- 실행기는 5초마다 Redis에 생존 신호를 기록한다. 30초 이상 없으면 중단으로 판단한다.
- 미전달 대기 100건 초과 또는 가장 오래된 대기 작업이 120초 초과이면 지연으로 표시한다.
- 별도 `operations-monitor` 컨테이너가 15초마다 확인하고 상태 전환을 Redis 알림함(최근 200개)과 로그에 남긴다.
  외부 메일·메신저는 발송하지 않는다. Redis 장애는 로그에만 기록할 수 있다.
- 호스트 전체 종료는 자체 모니터로 감지할 수 없다. 외부 `/ready` 감시와 HTTPS 배포는 별도 운영 설정이 필요하다.
  `/ready`를 API 기동 의존성으로 바꾸면 실행기 시작과 순환 대기가 생기므로 `/health`를 유지한다.

법정동 기준정보가 누락되면 주소가 있는 매물도 등록·후보 저장에 실패한다. 새 DB나 백업을
적용한 뒤 아래 순서로 전체 목록을 검증하고 동기화한다. 서비스 DB를 쓰는 pytest는
데이터를 지울 수 있으므로 `scripts/run_isolated_tests.py`로만 실행한다.

```bash
docker exec property_concierge_backend python -m backend.tools.sync_legal_regions --dry-run
./scripts/backup_db.sh
docker exec property_concierge_backend python -m backend.tools.sync_legal_regions
```

<a id="administration-단지-기준정보"></a>

### 단지 기준정보

추천된 단지를 `complex_catalog` 고유 ID로 보관한다. 시군구·법정동·정규화한 단지명을 식별 키로 사용하고
별칭·도로명·지번·좌표·주소 출처·외부 장소 ID·확인 시점을 보관한다. 이 ID는 네이버 단지번호가 아니다.
조회 실패 시 이전 근거를 남기되 최신 일치로 표시하지 않는다. 운영 화면에서 단건 재확인을 요청할 수 있다.
기존 캐시 전체를 마이그레이션하지 않고 다음 추천부터 기준정보가 생성된다.

<a id="administration-실거래-수집"></a>

### 실거래 수집

선택한 시군구의 최근 12개월을 원천별로 표시한다. 누락은 로그가 없는 조합까지 계산한다.
최근 24개월의 실패·누락·중단 의심·TTL 만료 항목만 한 월씩 Redis Stream 작업으로 재수집한다.
1시간 넘은 실행 중 기록은 중단 의심으로 표시하며 동일 재수집 요청은 10분 동안 차단한다.
전체 지역 주기 수집은 [transaction-refresh.md](#transaction-refresh)의 maintenance 프로필로 별도 활성화한다.
매물 수집 현황은 사용자 주소·URL 없이 상태별 건수만 제공하며 사람의 정답 대조 성공률과 구분한다.

로컬 Docker 환경에서는 2026-09-27에 `maintenance` 프로필을 활성화했다. 첫 실행은
서울 25개 구·7개 원천·12개월 2,100개 조합 중 348개를 재수집하고 1,752개를
TTL 내 자료로 건너뛰었으며 실패는 0건이었다. 저장된 실거래는 149,746건이다.
이는 해당 실행의 기록이며 다른 배포 환경은 프로필을 별도로 활성화해야 한다.

<a id="administration-실제-매물-대조"></a>

### 실제 매물 대조

동네 탐색의 단지 후보는 국토부 실거래 원문의 지번을 저장하고 카카오 주소 검색의
시군구 법정동코드·동·본번·부번을 대조해 도로명 주소를 확인한다. 두 주소가 모두 확인된
단지만 표시하며 미확인·복수 필지·조회 실패는 별도 확인 대기로 안내한다.
이는 단지 대표 주소 확인이며 개별 매물의 재고·호가·동호수 확인은 아니다.

기존 적재의 지번 누락은 아래 명령으로 보완한다. 거래 행·금액·해제 상태를 바꾸지 않고
확인된 지번 컬럼과 단지 기준정보만 갱신한다. 먼저 `alembic -c services/intelligence/alembic.ini upgrade head`를 적용한다.

```bash
python scripts/backfill_complex_addresses.py
python scripts/verify_complex_addresses.py --api-url http://127.0.0.1:8002
```

```powershell
node scripts/verify_complex_addresses_browser.cjs
```

API 검증은 서울 25개 구의 상위 후보를 대상으로 주소 완전성을 확인한다.
브라우저 검증은 실제 동별 추천·케이스 연결·지도 링크를 대조하며 미확인 주소 두 시나리오는
응답을 대체해 검증한다. 결과는 `evaluation-results/complex-address-*.json`에 저장한다.

사람이 최근 24시간 이내 확인한 정답 목록을 `evaluation-results/` 등에 작성한다. 다음 값은 형식 설명이다.

```json
[{"id":"검증-1","url":"https://fin.land.naver.com/articles/실제번호",
  "reviewed_at":"확인시각 ISO8601 (시간대 포함)",
  "expected":{"asking_price":700000000,"area_sqm":84.9,"address":"실제 원문 주소"}}]
```

```bash
python -m evaluation listing-check --live --dataset evaluation-results/listing-gold.json --max-cases 3
```

한 번에 최대 10건, 조회별 45초 제한. 실패·차단·종료도 분모에 포함한다. 필드별 차이를 JSON에 기록한다.
주소를 자동 유사 판정하거나 페이지가 보인다는 이유로 거래 가능을 판정하지 않는다.
정답 목록이 없으면 성공률을 만들어내지 않는다. 수집 실패 카드의 **이 링크로 수동 등록**은 추측한 값 없이 링크만 전달한다.

<a id="administration-매수-검토-요약과-전체-흐름"></a>

### 매수 검토 요약과 전체 흐름

`/cases/{id}/summary`에서 희망가·필요 현금·첫 달 상환액·시세 차이·위험·다음 행동을 함께 본다.
자금 입력값과 분석일·유효기한을 확인하고 브라우저 인쇄로 저장할 수 있다.
만료되거나 매수가가 달라진 자금 결과는 현재 수치로 표시하지 않는다.

```powershell
node scripts/verify_candidate_avm_browser.cjs --form --decision-flow
```

실행 중 서비스에서 임시 계정을 만들고 실제 AVM·계산기로 분석·비교·선택·요약·새로고침을 검증한 뒤 삭제한다.
실제 모델/API가 필요하므로 기본 CI의 고정 입력 검증과 분리한다. 결과는
`evaluation-results/avm-browser-result-decision.json`과 `decision-live-summary.png`에 기록한다.
실제 매수 성과나 AVM 정확도를 검증하는 것은 아니다.

<a id="administration-2026-09-25-확인-결과"></a>

### 2026-09-25 확인 결과

- 격리 PostgreSQL·Redis에서 전체 회귀 테스트 954개, 고정 입력 평가 33개 통과.
- 프론트 타입 검사·린트·프로덕션 빌드 통과.
- 실제 AVM(모델 대체 없음) → 후보 저장 → 실제 자금 계산 → 두 후보 비교 → 선택 → 새로고침 → 요약 값 대조 통과.
- 운영자 로그인·단지 기준정보·주소 재확인 작업·새로고침 복원·모바일 가로 넘침 검증 통과.
- 서비스 `/ready` HTTP 200, 별도 운영 모니터 기동 확인.
- PostgreSQL custom-format 백업을 격리 DB에 `pg_restore --exit-on-error`로 복원 완료.
- 인터넷 검색으로 발견한 개별 링크 5개를 Chrome과 실제 백엔드 수집기로 확인했으나 모두 원문 없음(`unavailable`)이었다. 현재 가격·면적·주소 정확도는 미측정이다. [조회 기록과 검증 범위](verification-history.md#listing-access)를 참고한다.
- 상시 서버·TLS·외부 장애 알림과 전체 지역 정기 수집 프로필 활성화는 별도 운영 설정이다.


<a id="local-runtime"></a>

## Windows·WSL 접속 유지

이 PC는 Docker Desktop 대신 Ubuntu WSL의 systemd Docker를 사용한다.
Windows에서 실행한 WSL 세션이 끝나면 배포판이 유휴 종료될 수 있다.
Docker의 `restart: unless-stopped`는 Docker 엔진 자체가 종료된 동안에는
서비스를 살리지 못한다. 따라서 재빌드 직후 HTTP 200 확인만으로는 충분하지 않다.

2026-09-25 접속 장애에서 Windows의 3001 연결 거부, 모든 컨테이너의 동시
재기동, 이전 부팅 로그의 `daemonShuttingDown=true`와 WSL의
`InitTerminateInstanceInternal` 종료 기록을 확인했다.

<a id="local-runtime-실행"></a>

### 실행

PowerShell에서 다음 명령으로 숨김 WSL 세션을 유지한다.
이미 실행 중이면 중복 생성하지 않는다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/keep-docker-wsl-alive.ps1
```

현재 사용자 로그인 때도 시작하려면 `-Action InstallStartup`을 붙인다.
사용자의 시작프로그램 폴더에 `Property Concierge Docker.lnk`를 생성한다.
프로젝트를 이동하면 기존 바로가기를 제거하고 다시 등록한다.
해제는 `-Action RemoveStartup`, 실행 중인 유지 프로세스 종료는 `-Action Stop`이다.
다른 프로젝트 컨테이너를 명시적으로 재시작하거나 종료하지 않는다.
이 세션은 Ubuntu 전체의 유휴 종료를 막으므로 WSL 메모리는 계속 사용한다.
PC 종료·절전·로그아웃 중 서비스 제공을 보장하지 않으며, 상시 운영은 별도 서버가 필요하다.

<a id="local-runtime-서비스-재빌드와-확인"></a>

### 서비스 재빌드와 확인

이 PC의 3000·8000 포트는 다른 프로젝트가 사용하므로 아래 포트를 유지한다.

```powershell
./scripts/compose.ps1 local up -d --build
curl.exe -f http://localhost:3002/login
curl.exe -f http://localhost:8002/health
```

브라우저 접속: http://localhost:3002

검증 시 일회성 WSL 명령을 추가 실행하지 않고 Windows HTTP 요청만 수 분간
반복해 접속이 유지되는지 확인한다. WSL 명령 자체가 종료된 배포판을 다시 깨워
장애를 숨길 수 있기 때문이다.

참고: [Microsoft WSL systemd 문서](https://learn.microsoft.com/en-us/windows/wsl/systemd)는
systemd 서비스가 WSL 인스턴스 수명을 유지하지 않는다고 설명한다.


<a id="job-recovery"></a>

## 작업 복구와 실행기

API는 AVM·챗봇·종합 컨시어지·원문 수집 작업의 JSON 입력과 상태를 Redis Stream에 함께 기록한다. 기본 `job-worker` 한 개가 최대 4개를 실행한다. 실행기가 종료되어 ACK하지 못한 작업은 3분 뒤 다른 실행기가 가져간다. Redis는 AOF를 사용한다. API는 상태 조회 시 기존 소유자 검사를 유지한다. 실행기를 여러 개로 늘리면 상한도 실행기 수만큼 늘어나므로 별도 전역 제한을 두기 전에는 한 개로 운영한다.

AVM 이력과 매물 수집 기록은 `job_id`를 고유 키로 저장한다. 작업을 다시 실행해도 같은 이력 또는 수집 기록을 중복 생성하지 않는다. 후보 연결은 작업 시작 시 후보 버전을 확인하므로, 그 사이 후보가 바뀌었다면 오래된 결과를 연결하지 않고 오류로 돌린다.

법률·종합 챗봇은 답변 저장과 작업 ACK를 하나의 트랜잭션으로 묶을 수 없다. 실행 중 종료된 채팅 작업은 자동 재질문으로 대화를 중복시키지 않고 오류로 끝내며 사용자가 다시 질문할 수 있게 안내한다. 아직 시작되지 않은 채팅 작업은 실행기가 다시 시작되면 처리한다.

시세추정 폼과 원문 수집 화면은 진행 중인 작업 ID를 같은 탭의 `sessionStorage`에 보관한다. 새로고침하면 기존 작업을 조회한다. 작업 결과는 Redis에서 완료 후 1시간 보관한다. 장기 보관이 필요한 AVM 리포트는 PostgreSQL 이력 ID로 조회한다.

격리 DB·Redis에서 `tests/test_durable_job_worker.py`는 pending 작업을 다른 소비자가 가져오는 동작과 저장 중복 방지를 확인한다. 실제 운영에서는 API와 `job-worker`가 모두 기동되어야 한다.


<a id="transaction-refresh"></a>

## 실거래 주기 갱신

국토부 매매 실거래 배치는 완료된 월이라도 마지막 조회 후 일정 시간이 지나면 다시 조회한다. 당월·전월은 12시간, 그 이전 월은 30일을 기준으로 한다. 정정·해제 신고를 반영하기 위한 정책이며 원천 API의 발표 지연까지 완전히 복원하는 것은 아니다.

운영 Compose의 `transaction-refresh` 서비스는 `maintenance` 프로필에서만 실행된다. API의 마이그레이션과 기동이 끝난 뒤 별도 컨테이너에서 서울특별시 최근 12개월을 기본 7일 주기로 검사한다. 완료 월의 TTL이 남았으면 API를 다시 호출하지 않는다.

```bash
sh scripts/compose.sh local --profile maintenance up -d --build
```

`TRANSACTION_REFRESH_INTERVAL_HOURS`, `TRANSACTION_REFRESH_MONTHS`, `TRANSACTION_REFRESH_WORKERS`, `TRANSACTION_REFRESH_SIDO`로 요청량을 조절한다. 처음 활성화할 때는 계획 작업 수와 국토부 API 할당량을 확인한다. 한 번의 배치가 실패하면 오류를 기록하고 다음 주기에 다시 시도하며, 수집 실패를 빈 거래월로 저장하지 않는다. 매물 원문 수집과 법령 코퍼스 갱신은 이 서비스에 포함되지 않는다.
