# 인터넷에서 발견한 개별 매물 링크 확인 — 2026-09-25

## 목적과 정답 기준

사용자가 링크를 제공하는 대신 인터넷 검색으로 예시를 직접 찾았다. 검색 결과의 가격·면적은 발견용 단서이며, 현재 원문 화면에서 확인하기 전에는 실매물 정답셋에 넣지 않는다. 제3자의 수집 예제 역시 실제 매물인지부터 확인해야 한다.

## 발견한 링크

| 개별 매물 | 발견 경로 | Windows Chrome에서 직접 조회 |
|---|---|---|
| [2530102807](https://fin.land.naver.com/articles/2530102807) | 네이버 상세 검색 결과: 상계주공7단지 710동, 확인일 2025-06-05 | 페이지를 찾을 수 없습니다 |
| [2526726740](https://fin.land.naver.com/articles/2526726740) | 네이버 상세 검색 결과: 상계주공11단지 1102동, 확인일 2025-05-19 | 페이지를 찾을 수 없습니다 |
| [2531931382](https://fin.land.naver.com/articles/2531931382) | 네이버 상세 검색 결과: 상계주공14단지 1408동, 확인일 2025-06-13 | 페이지를 찾을 수 없습니다 |
| [2648400245](https://fin.land.naver.com/articles/2648400245) | [제3자 수집기 설명](https://apify.com/sian.agency/naver-property-scraper)에 나온 예제 ID. 실제 유효성 미확인 | 페이지를 찾을 수 없습니다 |
| [2607694040](https://fin.land.naver.com/articles/2607694040) | [구미 진평동 매물 소개 게시글](https://rainbo.tistory.com/entry/%EA%B5%AC%EB%AF%B8-%EC%A7%84%ED%8F%89%EB%8F%99-%EC%9B%90%EB%A3%B8-%EB%8B%A4%EA%B0%80%EA%B5%AC-%EB%A7%A4%EB%AC%BC-%ED%98%84%ED%99%A9)의 링크 | 페이지를 찾을 수 없습니다 |

5개 모두 `financial.pstatic.net/404.html`로 이동했다. 최종 HTTP 상태는 200이지만 본문은 오류 화면이다. 따라서 HTTP 200만으로 수집 성공을 판단하면 안 된다.

추가 확인한 `https://new.land.naver.com/complexes/109208`도 `/404`로 이동했다. 네이버 지도의 상계주공7단지 검색은 열렸지만 그 자체로 매물 상세의 가격·전용면적·주소를 확인한 것은 아니다. 이번 관찰만으로 개별 매물 삭제, 사이트 변경, 실행 환경의 접근 문제 중 원인을 확정하지 않는다.

## 검증 범위와 증거

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

## 후속 원인 진단 — 같은 날 13:38 KST

`2648400245`를 일반 Windows Chrome에서 네트워크 응답까지 기록해 다음 경로를 확인했다.

1. `/articles/2648400245` → HTTP 307 → `/map?layer=…`.
2. 지도 페이지 HTML과 JavaScript는 HTTP 200으로 로드된다. 잠시 ‘매물 상세 / 로딩중’이 보인다.
3. 내부 `/front-api/v1/data-service/transport?itemType=article&itemId=2648400245` 및 매물 관련 API들이 HTTP 429를 반환한다. 응답 본문은 `{"detailCode":"TOO_MANY_REQUESTS","message":""}`다.
4. 이후 `/404` → HTTP 302 → `financial.pstatic.net/404.html`로 이동한다. 최종 오류 페이지 자체는 HTTP 200이다.

따라서 이 재현의 직접 원인은 상세 데이터 요청에 대한 네이버의 요청 제한이다. IP 기준 제한인지, 자동화 탐지인지, 일시적 정책인지까지 응답만으로 확정할 수 없다. 다른 4개 링크도 같은 내부 API 원인이라고 확대 해석하지 않는다. 실제 매물의 현재 유효성은 여전히 알 수 없다.

우리 코드의 진단 누락도 확인했다. `collect_page()`는 `page.goto()`의 문서 응답과 최종 본문만 `parse_page()`에 넘긴다. 내부 XHR의 429는 관찰하지 않으므로 접근 제한이 뒤따르는 오류 페이지를 `unavailable`로 분류한다. `parse_page()` 자체에는 429 → `blocked` 처리가 있지만 이번 429는 그 함수에 전달되지 않는다.

처음 의심한 `/map` 허용 목록 누락은 이번 실패의 직접 원인이 아니었다. 컨테이너 Chromium에서 요청 가드를 켠 경우와 끈 경우 모두 `/map` HTTP 200을 거쳐 같은 오류 화면에 도달했고, 차단된 문서 요청은 없었다. 실제 리디렉션에서 가드가 새 경로를 막는다는 추정은 대조 실험으로 철회했다.

추가 증거:

- `evaluation-results/naver-access-diagnosis.json`: 초기 HTTP 응답과 리디렉션.
- `evaluation-results/naver-detail-diagnosis.json`: 내부 API 429와 이후 오류 화면 이동.
- `evaluation-results/naver-container-diagnosis.json`: 요청 가드 활성/비활성 대조.

권장 수정은 핵심 매물 API의 401/403/429 관찰, 접근 제한을 `blocked`로 우선 분류, 원인 코드 보존, 서비스 전체 단위의 수집 대기·재시도 제한이다. 현재 계정당 60초 제한은 존재하지만 모든 계정과 진단 도구의 외부 요청량을 함께 제한하지는 않는다. 이번 작업은 원인 분석으로, 운영 수집기 코드는 변경하지 않았다.

## 후속 수정과 회귀 검증

위 원인 분석 이후 `naver-dom-v2`에 내부 API 제한 감지와 Redis 공통 대기를 구현했다. 상세 정책은 [수집 문서](listing-collection.md#접근-제한-분류와-서비스-공통-대기-2026-09-25)를 참고한다.

- 격리 PostgreSQL·Redis에서 전체 백엔드 테스트 963개 통과.
- 프론트 타입 검사·린트·프로덕션 빌드 통과.
- 실제 Chromium과 가상 원문으로 내부 API 401/403/429 → 오류 화면 이동을 재현하고 `blocked` 분류와 Retry-After 보존 확인.
- 브라우저에서 접근 제한 결과와 API의 공통 대기 HTTP 429 두 경로의 안내·버튼 비활성화·수동 등록을 확인. 매물 등록 → 후보 → 변경 재검토 → 재선택 → 새로고침 흐름도 통과.
- 브라우저 검증의 새로고침 단계에서 접힌 등록 폼을 다시 여는 동작이 테스트에 빠져 한 차례 실패했으며, 실제 사용자 동작을 추가한 후 전체 흐름이 통과했다.

증거: `evaluation-results/listing-fix-junit.xml`, `evaluation-results/decision-flow-browser.json`.

Docker API·실행기·프론트·운영 모니터를 재빌드한 이미지로 교체했다. 웹페이지와 `/ready`는 HTTP 200이다. 반영된 백엔드에서 실제 링크 `2648400245`를 1회 조회한 결과 `blocked`, `reason_code=naver_http_429`, `restriction_source=article_api`, 대기 900초로 기록됐다. 즉시 이어 호출한 수집은 브라우저 없이 `reason_code=collection_cooldown`, `request_sent=false`로 종료됐다. `evaluation-results/naver-restriction-live.json`에 보존했다. 네이버의 제한이 해제되거나 실제 매물의 값 추출이 성공한 것은 아니다.
