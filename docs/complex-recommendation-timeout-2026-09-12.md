# 단지 탐색 Internal Server Error 원인과 수정

## 재현 및 원인

프론트 로그에서 `/api/recommendation/complexes` 요청의 `socket hang up / ECONNRESET`을 확인했다. Next.js의 실제 프록시 구현(`node_modules/next/dist/server/lib/router-utils/proxy-request.js`)은 별도 설정이 없으면 30초 제한을 사용한다.

실행 서비스 DB의 서울 노원구 12개월 아파트 7,305건으로 단지 추천 서비스를 직접 실행하면서 SQLAlchemy 실행 횟수와 보정계수 함수 호출 횟수를 측정했다. 수정 전 51.141초, SQL 61,898회, 보정계수 조회 7,289회였다. 월별 데이터가 DB에 있어도 가격 시점수정이 거래 한 건마다 동일한 지역·거래월·기준월의 지수를 재조회하는 구조였다. 데이터 확장 후 이 반복 비용이 프록시 제한을 넘었다.

## 수정

`services/intelligence/backend/price_engine.py`의 `_apply_time_adjustment`에서 동일 요청 안의 거래월별 지수 보정계수를 한 번만 조회하고 재사용한다. 유형·지역·기준월은 함수 인자로 고정되어 있어 보정 식은 동일하다. 조회 실패 결과도 현재 요청 안에서만 재사용하고 다음 요청에서는 다시 조회한다. 영구 캐시나 작업 큐의 인프로세스 폴백을 추가하지 않았다.

## 수정 후 검증

동일 노원구 7,305건에서 0.261초, SQL 200회, 보정계수 조회 11회로 줄었다. 실제 Chrome `/explore`에서 노원구·마포구·송파구를 클릭해 모두 HTTP 200과 후보 10개 표시를 확인했다. 해당 실행의 클릭부터 표시까지 시간은 각각 0.422초·0.250초·0.258초였다. 이는 현재 DB와 지수 캐시 상태의 실측이며 외부 API 장애나 미수집 지역까지 같은 시간을 보장하지 않는다.

`tests/test_reb_index.py`에 3,000건 입력에서도 거래월 수만큼 조회하는 회귀 검증을 추가했다. 지수가 있는 경우·없는 경우 모두 가격 계산 결과를 확인하고, 다음 요청에서는 다시 조회하는 것도 검증한다. 백엔드 Docker 이미지를 재빌드해 실행 서비스에 반영했다.

로컬 측정 자료: `evaluation-results/probe_complex_performance.py`, `seoul-explore.json`, `seoul-explore.png`.
