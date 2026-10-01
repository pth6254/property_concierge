# 과거 실측·장애 분석 기록

측정 날짜별 근거를 보존한다. 과거 실행 수치와 현재 동작·품질을 혼동하지 않는다. 최신 상태는 프로젝트 인수인계를 따른다.

[문서 목록](README.md)

- [서비스 연결·서울 데이터·추천 검증](#historical-runs)
- [2026-09-12 단지 조회 성능 문제](#complex-performance)
- [2026-09-25 실매물 접근 제한](#listing-access)

<a id="historical-runs"></a>

## 서비스 연결·서울 데이터·추천 검증

아래는 해당 날짜의 구현·데이터·실행 환경에서 측정한 기록이다. 현재 서비스의 데이터 건수,
응답 시간·전체 테스트 수·정확도를 뜻하지 않는다. 현재 상태는 [인수인계](project-handoff.md)와
[구조 안내](architecture.md#repository), 수집 운영은 [주기 갱신](operations.md#transaction-refresh)을 따른다.
중복된 단계 보고서의 실측만 이 문서로 합쳤다. 없어진 임시 검증 스크립트의 실행 안내는 제외했다.

<a id="historical-runs-2026-09-10-서비스-연결모델-출력"></a>

### 2026-09-10 서비스 연결·모델 출력

- 실제 Chrome과 임시 계정으로 샘플 추천의 누락된 `PropertyQuery.intent`, 한글 목적 변환과
  `2.5억`이 25억으로 전달되던 오류를 재현·수정했다. 수정 후 요청 값 `250000000`원을 확인했다.
- 당시 지역 API는 시·도 1개, 서초구 추천 단지 5개였다. 주소·84.9㎡ 자동 입력 → 실제 AVM 실행 →
  작업 완료 → 원 단위 후보 저장 → 새로고침 유지와 자금 계산·저장·경고·가격 변경 재검토를 확인했다.
- 초기 회귀 816건·고정/가상 평가 33건, 프론트 타입·린트·빌드 및 금액 변환 2건이 통과했다.
- 모델이 `transaction_type: null`을 반환한 안내 질문의 오류를 재현했다. 추출 봉투와 실행 조건을
  분리한 뒤 같은 질문이 8.19초 후 HTTP 200·completed로 표시됐다. 추가 회귀 25건을 포함한
  전체 841건과 평가 33건이 통과했다. 프록시 제한·모든 자연어 표현·유효 숫자의 의미 정확도는 별도 범위였다.

<a id="historical-runs-2026-09-12-서울-실거래-확장"></a>

### 2026-09-12 서울 실거래 확장

서울 25개 자치구·2025년 10월~2026년 9월의 매매 원천을 수집했다. 당월은 진행 중이므로
이 수치는 확정 거래 총량이 아니다. 해제 거래는 원본에 보존하고 탐색 집계에서 제외했다.

| 아파트 수집 | 당시 결과 |
|---|---|
| 공식 법정동 마스터 | 서울 493개 레코드 업서트; 다른 지역을 비활성화하지 않음 |
| 원천 | RTMSDataSvcAptTrade |
| 지역·월 | 300개 완료: 신규 288개·기존 완료 12개·실패 0개 |
| 저장 거래 | 2,187 → 67,752건; 증가 65,565건 |
| 해제·탐색 집계 | 해제 2,118건; 해제 제외 65,634건·25개 구 |
| 성공 후 0건 | 종로구·중구 2026년 9월. 조회 실패와 구분 |

아파트 외 6개 원천 × 25개 구 × 12개월의 1,800개 작업도 실패 없이 완료했다.
신규 78,093건, 당시 아파트 포함 저장 거래는 145,845건이었다.

| 유형 | 저장(해제 포함) | 탐색(해제 제외) | 거래 표시 지역 |
|---|---:|---:|---:|
| 연립·다세대 | 37,894 | 36,315 | 25 |
| 단독·다가구 | 3,977 | 3,718 | 25 |
| 오피스텔 | 12,215 | 11,663 | 25 |
| 상업·업무 | 12,000 | 11,257 | 25 |
| 공장·창고 | 1,284 | 1,219 | 22 |
| 토지 | 10,723 | 10,293 | 25 |

공장·창고도 25개 구를 조회했지만 유효 거래가 없는 구는 집계에서 제외됐다.
Chrome에서 마포구 2,077건·186개 집계 단지, 송파구 4,322건·251개 집계 단지와 각 후보 10개를 확인했다.
아파트 외 여섯 유형의 API 200·지역 통계와 토지 관심 지역의 케이스 저장도 확인했다.
단지 sample_count와 지역 거래 건수는 다른 지표다. 당시 초기 조회의 ECONNRESET은
[후속 성능 진단](#complex-performance)에서 별도로 분석했다.
로컬 증거는 `evaluation-results/seoul-explore.json`, `seoul-explore.png`,
`other-properties-ui.json`, `other-properties-ui.png`다. 서울 외·전월세·활성 매물·전국 AVM 정확도는 미검증이다.

<a id="historical-runs-2026-09-1213-컨시어지-단지-추천"></a>

### 2026-09-12~13 컨시어지 단지 추천

- `select_properties`를 실거래 추천에 연결한 단계의 회귀는 893건·고정 입력 평가 33건이었다.
  대화 조건·법률 맥락 연결의 후속 회귀는 894건이었다. 두 실행을 현재 테스트 수로 사용하지 않는다.
- 실제 모델로 역삼동 8억 이하 동네 질문 → 구체적인 단지 요청을 실행해 예산 유지와 단지 5개 표시를 확인했다.
  해당 단일 실행은 첫 답변 약 9초·후속 답변 약 7초였다. 일반적인 속도 보장은 아니다.
- 추천 → 후보 저장·선택 → 재저장 시 기존 후보 선택 → 금융 조건 보완 안내 → 후보 AVM 완료,
  성인 자녀 5억 증여 → 같은 금액 배우자 후속 답변을 확인했다. 자금은 입력 안내까지의 검증이었다.
- `tests/test_concierge_complexes.py`·`test_concierge_legal_context.py`의 고정 모델 회귀와
  실제 모델 실행은 구분한다. 로컬 화면 증거는 `evaluation-results/chat-complexes.png`다.

매물 원문 접근 제한의 실측은 [2026-09-25 조회 기록](#listing-access)에,
최신 일반 서비스 연결·브라우저 흐름 검증은 [구조 안내](architecture.md#repository)에 유지한다.


<a id="complex-performance"></a>

## 2026-09-12 단지 조회 성능 문제

<a id="complex-performance-재현-및-원인"></a>

### 재현 및 원인

프론트 로그에서 `/api/recommendation/complexes` 요청의 `socket hang up / ECONNRESET`을 확인했다. Next.js의 실제 프록시 구현(`node_modules/next/dist/server/lib/router-utils/proxy-request.js`)은 별도 설정이 없으면 30초 제한을 사용한다.

실행 서비스 DB의 서울 노원구 12개월 아파트 7,305건으로 단지 추천 서비스를 직접 실행하면서 SQLAlchemy 실행 횟수와 보정계수 함수 호출 횟수를 측정했다. 수정 전 51.141초, SQL 61,898회, 보정계수 조회 7,289회였다. 월별 데이터가 DB에 있어도 가격 시점수정이 거래 한 건마다 동일한 지역·거래월·기준월의 지수를 재조회하는 구조였다. 데이터 확장 후 이 반복 비용이 프록시 제한을 넘었다.

<a id="complex-performance-수정"></a>

### 수정

`services/intelligence/backend/price_engine.py`의 `_apply_time_adjustment`에서 동일 요청 안의 거래월별 지수 보정계수를 한 번만 조회하고 재사용한다. 유형·지역·기준월은 함수 인자로 고정되어 있어 보정 식은 동일하다. 조회 실패 결과도 현재 요청 안에서만 재사용하고 다음 요청에서는 다시 조회한다. 영구 캐시나 작업 큐의 인프로세스 폴백을 추가하지 않았다.

<a id="complex-performance-수정-후-검증"></a>

### 수정 후 검증

동일 노원구 7,305건에서 0.261초, SQL 200회, 보정계수 조회 11회로 줄었다. 실제 Chrome `/explore`에서 노원구·마포구·송파구를 클릭해 모두 HTTP 200과 후보 10개 표시를 확인했다. 해당 실행의 클릭부터 표시까지 시간은 각각 0.422초·0.250초·0.258초였다. 이는 현재 DB와 지수 캐시 상태의 실측이며 외부 API 장애나 미수집 지역까지 같은 시간을 보장하지 않는다.

`tests/test_reb_index.py`에 3,000건 입력에서도 거래월 수만큼 조회하는 회귀 검증을 추가했다. 지수가 있는 경우·없는 경우 모두 가격 계산 결과를 확인하고, 다음 요청에서는 다시 조회하는 것도 검증한다. 백엔드 Docker 이미지를 재빌드해 실행 서비스에 반영했다.

로컬 측정 자료: `evaluation-results/probe_complex_performance.py`, `seoul-explore.json`, `seoul-explore.png`.


<a id="listing-access"></a>

## 2026-09-25 실매물 접근 제한

<a id="listing-access-목적과-정답-기준"></a>

### 목적과 정답 기준

사용자가 링크를 제공하는 대신 인터넷 검색으로 예시를 직접 찾았다. 검색 결과의 가격·면적은 발견용 단서이며, 현재 원문 화면에서 확인하기 전에는 실매물 정답셋에 넣지 않는다. 제3자의 수집 예제 역시 실제 매물인지부터 확인해야 한다.

<a id="listing-access-발견한-링크"></a>

### 발견한 링크

| 개별 매물 | 발견 경로 | Windows Chrome에서 직접 조회 |
|---|---|---|
| [2530102807](https://fin.land.naver.com/articles/2530102807) | 네이버 상세 검색 결과: 상계주공7단지 710동, 확인일 2025-06-05 | 페이지를 찾을 수 없습니다 |
| [2526726740](https://fin.land.naver.com/articles/2526726740) | 네이버 상세 검색 결과: 상계주공11단지 1102동, 확인일 2025-05-19 | 페이지를 찾을 수 없습니다 |
| [2531931382](https://fin.land.naver.com/articles/2531931382) | 네이버 상세 검색 결과: 상계주공14단지 1408동, 확인일 2025-06-13 | 페이지를 찾을 수 없습니다 |
| [2648400245](https://fin.land.naver.com/articles/2648400245) | [제3자 수집기 설명](https://apify.com/sian.agency/naver-property-scraper)에 나온 예제 ID. 실제 유효성 미확인 | 페이지를 찾을 수 없습니다 |
| [2607694040](https://fin.land.naver.com/articles/2607694040) | [구미 진평동 매물 소개 게시글](https://rainbo.tistory.com/entry/%EA%B5%AC%EB%AF%B8-%EC%A7%84%ED%8F%89%EB%8F%99-%EC%9B%90%EB%A3%B8-%EB%8B%A4%EA%B0%80%EA%B5%AC-%EB%A7%A4%EB%AC%BC-%ED%98%84%ED%99%A9)의 링크 | 페이지를 찾을 수 없습니다 |

5개 모두 `financial.pstatic.net/404.html`로 이동했다. 최종 HTTP 상태는 200이지만 본문은 오류 화면이다. 따라서 HTTP 200만으로 수집 성공을 판단하면 안 된다.

추가 확인한 `https://new.land.naver.com/complexes/109208`도 `/404`로 이동했다. 네이버 지도의 상계주공7단지 검색은 열렸지만 그 자체로 매물 상세의 가격·전용면적·주소를 확인한 것은 아니다. 이번 관찰만으로 개별 매물 삭제, 사이트 변경, 실행 환경의 접근 문제 중 원인을 확정하지 않는다.

<a id="listing-access-검증-범위와-증거"></a>

### 검증 범위와 증거

- 일반 Chrome 페이지 조회: 개별 링크 5개, 원문 확인 성공 0개.
- 같은 링크를 실행 중인 백엔드의 `collect_page()`로 별도 조회했고, 5개 모두 `unavailable`, 추출 필드 없음으로 기록됐다. 결과는 아래 JSON에 보존한다.
- 현재 원문에서 독립적으로 확인한 정답이 없어 `listing-check --live`의 가격·전용면적·주소 정확도 평가는 실행하지 않았다. 정확도는 **미측정**이다.
- 링크 발견·오류 분류 검증과 실제 매물 추출 성공을 구분한다. 실패를 거래 완료로 해석하거나 과거 가격을 현재 가격으로 저장하지 않는다.

로컬 증거는 Git에서 제외된 `evaluation-results/`에 보관한다.

- `listing-discovery.json`, `listing-discovery-recent.json`: 브라우저 조회 시각, 최종 URL, 화면 본문.
- `listing-discovery-0.png` 등: 실제 오류 화면과 지도 검색 화면.
- `listing-access-audit.json`: 백엔드 실제 수집 결과. `price_area_address_accuracy: null`.
- `discover-live-listings.cjs`, `check-discovered-listings.py`: 이번 검증 실행 코드.

현재 자동 추출을 운영의 필수 경로로 삼을 근거는 부족하다. 기존 링크 보관·사용자 수동 입력 경로를 유지하고, 현재 원문이 열리는 링크를 확보하면 같은 시점의 값으로 정답을 작성해 기존 평가기에 넣는다.

<a id="listing-access-후속-원인-진단--같은-날-1338-kst"></a>

### 후속 원인 진단 — 같은 날 13:38 KST

`2648400245`를 일반 Windows Chrome에서 네트워크 응답까지 기록해 다음 경로를 확인했다.

1. `/articles/2648400245` → HTTP 307 → `/map?layer=…`.
2. 지도 페이지 HTML과 JavaScript는 HTTP 200으로 로드된다. 잠시 ‘매물 상세 / 로딩중’이 보인다.
3. 내부 `/front-services/intelligence/api/v1/data-service/transport?itemType=article&itemId=2648400245` 및 매물 관련 API들이 HTTP 429를 반환한다. 응답 본문은 `{"detailCode":"TOO_MANY_REQUESTS","message":""}`다.
4. 이후 `/404` → HTTP 302 → `financial.pstatic.net/404.html`로 이동한다. 최종 오류 페이지 자체는 HTTP 200이다.

따라서 이 재현의 직접 원인은 상세 데이터 요청에 대한 네이버의 요청 제한이다. IP 기준 제한인지, 자동화 탐지인지, 일시적 정책인지까지 응답만으로 확정할 수 없다. 다른 4개 링크도 같은 내부 API 원인이라고 확대 해석하지 않는다. 실제 매물의 현재 유효성은 여전히 알 수 없다.

우리 코드의 진단 누락도 확인했다. `collect_page()`는 `page.goto()`의 문서 응답과 최종 본문만 `parse_page()`에 넘긴다. 내부 XHR의 429는 관찰하지 않으므로 접근 제한이 뒤따르는 오류 페이지를 `unavailable`로 분류한다. `parse_page()` 자체에는 429 → `blocked` 처리가 있지만 이번 429는 그 함수에 전달되지 않는다.

처음 의심한 `/map` 허용 목록 누락은 이번 실패의 직접 원인이 아니었다. 컨테이너 Chromium에서 요청 가드를 켠 경우와 끈 경우 모두 `/map` HTTP 200을 거쳐 같은 오류 화면에 도달했고, 차단된 문서 요청은 없었다. 실제 리디렉션에서 가드가 새 경로를 막는다는 추정은 대조 실험으로 철회했다.

추가 증거:

- `evaluation-results/naver-access-diagnosis.json`: 초기 HTTP 응답과 리디렉션.
- `evaluation-results/naver-detail-diagnosis.json`: 내부 API 429와 이후 오류 화면 이동.
- `evaluation-results/naver-container-diagnosis.json`: 요청 가드 활성/비활성 대조.

권장 수정은 핵심 매물 API의 401/403/429 관찰, 접근 제한을 `blocked`로 우선 분류, 원인 코드 보존, 서비스 전체 단위의 수집 대기·재시도 제한이다. 현재 계정당 60초 제한은 존재하지만 모든 계정과 진단 도구의 외부 요청량을 함께 제한하지는 않는다. 이번 작업은 원인 분석으로, 운영 수집기 코드는 변경하지 않았다.

<a id="listing-access-후속-수정과-회귀-검증"></a>

### 후속 수정과 회귀 검증

위 원인 분석 이후 `naver-dom-v2`에 내부 API 제한 감지와 Redis 공통 대기를 구현했다. 상세 정책은 [수집 문서](features/listings.md#listing-collection-접근-제한-분류와-서비스-공통-대기-2026-09-25)를 참고한다.

- 격리 PostgreSQL·Redis에서 전체 백엔드 테스트 963개 통과.
- 프론트 타입 검사·린트·프로덕션 빌드 통과.
- 실제 Chromium과 가상 원문으로 내부 API 401/403/429 → 오류 화면 이동을 재현하고 `blocked` 분류와 Retry-After 보존 확인.
- 브라우저에서 접근 제한 결과와 API의 공통 대기 HTTP 429 두 경로의 안내·버튼 비활성화·수동 등록을 확인. 매물 등록 → 후보 → 변경 재검토 → 재선택 → 새로고침 흐름도 통과.
- 브라우저 검증의 새로고침 단계에서 접힌 등록 폼을 다시 여는 동작이 테스트에 빠져 한 차례 실패했으며, 실제 사용자 동작을 추가한 후 전체 흐름이 통과했다.

증거: `evaluation-results/listing-fix-junit.xml`, `evaluation-results/decision-flow-browser.json`.

Docker API·실행기·프론트·운영 모니터를 재빌드한 이미지로 교체했다. 웹페이지와 `/ready`는 HTTP 200이다. 반영된 백엔드에서 실제 링크 `2648400245`를 1회 조회한 결과 `blocked`, `reason_code=naver_http_429`, `restriction_source=article_api`, 대기 900초로 기록됐다. 즉시 이어 호출한 수집은 브라우저 없이 `reason_code=collection_cooldown`, `request_sent=false`로 종료됐다. `evaluation-results/naver-restriction-live.json`에 보존했다. 네이버의 제한이 해제되거나 실제 매물의 값 추출이 성공한 것은 아니다.
