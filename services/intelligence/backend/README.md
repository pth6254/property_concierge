# Property Concierge 백엔드 도메인 안내

`services/intelligence/backend/`는 부동산 분석과 의사결정의 도메인 로직을 담당한다. 공개 업무 API·인증·저장·트랜잭션은
Kotlin `services/platform/`, 분석 HTTP와 실행기는 Python `services/intelligence/api/`, Python 계약은 `services/intelligence/schemas/`에 있다.
고정 수식의 자금·세금 계산은 Kotlin이다. `core_calculations.py`가 같은 엔진으로 화면·대화·비교를 연결한다.
`services/intelligence/db/`의 모델·Alembic은 공통 스키마를 관리하며 실거래·RAG·분석 캐시는 Python이 관리한다.
이전된 사용자·매물·케이스·분석 이력 저장 함수는 `services/intelligence/api/core_bridge.py`를 통해 Spring을 호출한다.
개발 전에 [루트 작업 지침](../../../AGENTS.md)을 읽고, 제품 범위는 [제품 전략](../../../docs/product-strategy.md),
현재 전환 상태는 [백엔드 전환 안내](../../../docs/architecture.md#backend)를 확인한다.
Python 일반 API·인증·주소·레이트 리밋 파일 16개를 삭제했다. API는 내부 AI·데이터 분석만 제공한다.
OAuth·재설정·주소·운영·작업 접수는 Spring이다. 내부 저장 클라이언트를 업무 SQL로 되돌리지 않는다.

## 현재 제품의 중심 흐름

사용자가 URL·직접 입력·CSV로 등록한 관심 매물을 매수 케이스에 저장하고, 가격·자금·권리 분석을 근거로 적합성·가격성·자금성·위험성·실행성을 검토한다. 비교 후 사용자가 선택·제외 이유를 기록하고 다음 행동과 거래 준비 작업을 관리한다. 초기 대상은 아파트 매매이며 모바일 앱은 후속 단계다.

네이버 지도 연결과 원문 수집은 보조 입력 경로다. 추출이 실패해도 사용자 확인값으로 등록할 수 있어야 한다. 실거래·사용자 호가·AVM 추정값은 서로 다른 자료이며 동일 단지 확인이 개별 호의 동일성을 보증하지 않는다.

```text
웹 → Caddy → Kotlin Spring: 인증·소유자 확인·저장·확정 조건
                  ├ 고정 수식: 자금·대출·세금·수익 계산
                  ├ 스냅샷 → 내부 FastAPI → 도메인 분석
                  └ Redis Stream → 별도 Python job-worker
                                          → Spring 저장 계약 → PostgreSQL / Redis
```

## 핵심 코드와 연결 위치

| 코드 | 역할 |
|---|---|
| [case_decision_assessment.py](services/case_decision_assessment.py) | 같은 케이스 스냅샷에서 다섯 판단 축·근거·현재 비교 금액·다음 행동 산출 |
| [case_comparison_service.py](services/case_comparison_service.py) | 공통 평가 결과를 후보 비교에 적용하고 오래된 값·근거 부족을 구분 |
| [candidate_funding.py](services/candidate_funding.py) · [case_funding_scenarios.py](services/case_funding_scenarios.py) | 후보의 저장된 자금 입력과 공통 프로필을 연결하고 시나리오 계산 |
| [candidate_next_actions.py](services/candidate_next_actions.py) · [analysis_freshness.py](services/analysis_freshness.py) | 누락·실패·만료·원본 변경에 따른 보완 행동과 유효 시점 |
| [listing_store.py](services/listing_store.py) · [listing_observations.py](services/listing_observations.py) | 사용자별 등록 매물, 저장 변경 이력, 원문 관측과 재확인 상태 |
| [ListingAddressService.kt](../../platform/src/main/kotlin/kr/propertyconcierge/core/addresses/ListingAddressService.kt) | 주소·건물명 조회와 선택 정보 검증. 조회 이름과 사용자 선택 별칭은 별도 저장 |
| [naver_listing_collector.py](services/naver_listing_collector.py) | 개별 링크의 Playwright 수집. 실패·접근 제한·미노출을 거래 완료와 구분 |
| [appraisal_graph.py](graphs/appraisal_graph.py) | 자연어 분석·위치 해석·유형별 AVM·참고용 리포트 파이프라인 |
| [simulation_service.py](services/simulation_service.py) · [core_calculations.py](services/core_calculations.py) | 입력 정규화·Kotlin 계산 호출·리포트 표현 |
| [funding_execution_client.py](services/funding_execution_client.py) | 챗봇 후보 자금 분석을 Spring의 계산·소유자 확인·결과 저장 경로로 실행 |
| [rights_analysis_service.py](services/rights_analysis_service.py) | 사용자 문서의 판독 결과와 규칙 기반 위험 신호 점검 |
| [law_retrieval.py](services/law_retrieval.py) · [concierge_graph.py](graphs/concierge_graph.py) | 법령 근거 검색과 대화 맥락·조건부 도구 실행 |
| [model_factory.py](model_factory.py) | 역할별 LLM·임베딩 제공자 생성. OpenRouter 등 지원 제공자 선택 |
| [CaseController.kt](../../platform/src/main/kotlin/kr/propertyconcierge/core/store/CaseController.kt) · [케이스 저장 클라이언트](../api/case_db.py) | Spring이 소유자 확인·요약·비교·선택·후보 및 분석 결과 저장을 담당 |
| [작업 큐](../api/jobs.py) · [작업 실행기](../api/job_worker.py) | 긴 작업의 영속 접수·실행·복구 경계 |

## 의사결정 결과 계약

`GET /api/cases/{id}/summary`는 소유자 확인 후 `case`, `comparison`, `decision`을 반환한다. 다섯 축의 스키마는 [decision_assessment.py](../schemas/decision_assessment.py)에 있으며, 요약과 비교가 같은 평가 결과를 사용한다. 이 조회는 외부 API·LLM·새 작업·DB 변경 없이 저장된 자료로 계산한다.

자료 부족·판독 실패는 미확인이고, 만료·기준일 누락·원본 변경은 현재 비교 금액에서 제외한다. 유효한 주의 결과의 금액은 표시할 수 있으나 근거가 없는 값을 0이나 안전으로 대체하지 않는다. 사용자 선택과 `review_ready`는 구분하며 자동 매수 결론을 만들지 않는다. 자세한 확인 조건은 [의사결정 검토 기준](../../../docs/features/decision.md#decision-assessment)을 따른다.

자금 입력의 `owned_homes`는 취득 후 주택 수다. 첫 주택은 1이고 `home_count_basis="after_purchase"`를 기록한다. 공통 프로필의 비상자금은 한 번만 제외하며 저장된 후보별 가용 현금에서 재차 제외하지 않는다. 개별 조건과 공통 조건이 다르다는 이유만으로 저장 결과를 무효화하지 않는다. 공통 변환은 [simulation.py](../schemas/simulation.py), 입력·검증 기준은 [자금 문서](../../../docs/features/decision.md#funding-input)를 따른다.

권리 점검은 업로드 여부와 등기부·건축물대장 판독 성공을 별도로 기록한다. 빈 PDF·판독 실패·일부 문서만 있는 결과를 안전으로 승격하지 않는다. 원문 PDF는 현재 영구 저장하지 않는다.

## 기존 분석과 데이터의 범위

AVM은 국토부 실거래를 사용하고 `CATEGORY_TO_AGENT`에서 주거·상업·업무·산업·토지로 분기한다. 비교사례·유형·지역별 정확도에 차이가 있으므로 분기 존재를 모든 유형의 검증 완료로 설명하지 않는다. AVM은 법적 감정평가가 아닌 참고용 분석이다. `services/intelligence/backend/models.py`의 가치 결과는 만원 단위이며 API 금액 원 단위로 바꿀 때 변환을 유지한다.

법령 RAG는 수집 문서를 임베딩해 pgvector에 저장하고 질문과 관련된 근거를 검색하는 구조다. 모델을 해당 문서로 재학습한 것이 아니다. 생성 모델과 임베딩 모델의 설정은 별도이며 임베딩 설정을 바꾸면 기존 벡터와의 호환·재적재 여부를 확인해야 한다. 수집 범위·검색·인용 품질은 [평가 안내](../evaluation/README.md)에서 구분한다.

샘플 추천·비교는 `data/sample_listings.csv`의 가상 자료다. 매수 케이스의 사용자 등록 후보와 혼합하지 않는다. 기존 관측·변경 이력과 거래 준비 모델을 먼저 활용하고, 기획안의 새 `Property` 체계·개인화 그래프·Marketplace를 이미 구현한 모델처럼 취급하지 않는다.

## 실행과 검증

모든 명령은 저장소 루트에서 실행한다. 이 환경에서는 Python과 Docker가 WSL에 있다. PostgreSQL·Redis가 필수이며 SQLite·인프로세스 큐 폴백은 없다. 전체 서비스는 다음처럼 실행한다.

```bash
sh scripts/compose.sh dev up -d --build
```

기본 호스트 포트는 웹 3002, Spring API 8002이고 내부는 Next 3000·Spring 8080·Python 8000이다. Spring·Python API·별도 `job-worker`·PostgreSQL·Redis를 함께 실행한다. Python에는 중복 업무 저장·금융 수식 구현을 두지 않는다. 실행과 설정은 [루트 README](../README.md), 운영 적용과 복구는 [운영 안내](../../../docs/operations.md#administration)와 [작업 복구](../../../docs/operations.md#job-recovery)를 따른다.

테스트는 서비스 DB에 연결하지 않고 전용 DB `real_estate_test`·Redis DB 15로 실행한다.

```bash
./venv-wsl/bin/python scripts/run_isolated_tests.py tests/ -q
```

도메인 계약은 `tests/test_case_decision_assessment.py`, 자금 입력은 `tests/test_funding_consistency.py`, API 소유자 격리와 권리 판독 상태는 `tests/test_purchase_cases.py`에서 검증한다. 브라우저 명령·최신 결과·미검증 범위는 [의사결정 검토 문서](../../../docs/features/decision.md#decision-assessment-검증-범위)에 있다. 백엔드 변경 후 프론트엔드 타입·린트·빌드도 확인한다.

## 다음 구현 순서

주소와 부동산 객체의 식별 수준을 연결하고, 실거래 비교사례·문서 항목의 근거를 보강한 뒤 실제 아파트 전체 흐름을 검증한다. 기능을 추가할 때는 입력 출처·기준일·누락과 실패 상태·소유권·재검토 영향·검증 사례를 함께 정의한다. 모바일 앱과 자산 유형 확대는 그 이후다.
