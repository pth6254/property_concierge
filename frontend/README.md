# Property Concierge 프론트엔드 안내

Next.js 16 App Router·React 19·TypeScript로 작성한 웹 서비스다. 사용자의 매물 등록과 매수 케이스를 중심으로 분석·비교·선택·다음 행동을 연결한다. 제품 방향은 [제품 전략](../docs/product-strategy.md), 현재 작업은 [인수인계](../docs/project-handoff.md), 코드 수정 제약은 [루트 AGENTS](../AGENTS.md)와 [프론트엔드 AGENTS](AGENTS.md)를 따른다.

현재는 아파트 매수 의사결정의 기반을 강화한다. 반응형 웹을 제공하며 독립 모바일 앱은 이후 단계다. 네이버 부동산 링크는 외부 탐색 보조이고 사용자 매물의 등록·검토를 대신하지 않는다.

## 주요 화면

기본 웹 3002는 Caddy가 제공하며 `/api/*`는 Kotlin Spring으로 직접 전달한다.
Next 서버의 내부 대상과 Docker 빌드 시 rewrites도 `http://core:8080`으로 맞춘다.
Spring 공개 API는 8002, Python은 내부 전용이다. 인증 쿠키·화면 응답 계약은 유지한다.
작업 상태 SSE API는 추가했으며 현재 화면의 작업 대기는 기존 폴링을 사용한다.
실행·검증 범위는 [백엔드 전환 안내](../docs/backend-migration.md)를 따른다.

| 경로 | 역할 |
|---|---|
| `/listings` | 주소 검색·확인 이름 자동 채움·선택 별칭, URL·직접 입력·CSV 등록, 원문 관측·변경 이력, 후보 저장 |
| `/cases` · `/cases/{id}` | 매수 목적·예산·공통 조건·후보·분석·체크리스트 관리 |
| `/cases/{id}/summary` | 매수 검토 요약: 후보별 다섯 판단 축·근거·기준일·누락 정보·다음 행동 |
| `/cases/{id}/comparison` | 저장된 실제 사용자 후보 비교와 선택·제외 이유 기록 |
| `/cases/{id}/execution` | 선택 후보의 거래 준비 작업·일정·확인 결과·외부 대기 |
| `/appraisal` · `/report/{id}` | AVM 입력과 본인 참고용 리포트 재열람 |
| `/simulation` · `/rights` | 후보 조건에 연결한 자금 계산과 사용자 PDF 권리 위험 점검 |
| 전역 AI 컨시어지 위젯 · `/chat` | 선택한 케이스·후보에 연결한 도구 실행과 법률·세금 상담, 대화 맥락·복원 |
| `/explore` | 행정구역 계층의 실거래 비교와 단지 탐색. 개별 활성 매물 목록과 구분 |
| `/recommendation` · `/comparison` | 단지 추천과 개발용 가상 매물 도구. 샘플 비교는 실제 사용자 후보 비교와 구분 |
| `/operations` | 서버가 권한을 확인하는 운영 관리 |

핵심 흐름은 **등록 → 후보 → 분석 → 매수 검토 요약 → 비교·사용자 선택 → 다음 행동·변경 재검토**다. 동네 탐색을 먼저 거치지 않아도 등록한 매물로 진행할 수 있다. 상태·다음 행동의 의미는 [의사결정 검토 기준](../docs/decision-assessment.md), 탐색과 등록 연결은 [화면 이동 안내](../docs/ui-navigation.md)를 따른다.

## API와 상태 연결

브라우저의 API 요청은 `/api/*`를 사용한다. [next.config.ts](next.config.ts)의 rewrites가 FastAPI로 중계하므로 현재 구조는 같은 출처의 JWT 쿠키 인증이다. `NEXT_PUBLIC_API_URL`은 서버가 연결할 API 주소이며 클라이언트에 API 키를 두지 않는다. 쿠키·프록시 배포 조건은 루트 AGENTS에 있다.

| 코드 | 역할 |
|---|---|
| [api.ts](src/lib/api.ts) · [types.ts](src/lib/types.ts) | API 호출·폴링과 응답 타입. 요약 응답의 `case`·`comparison`·`decision` 계약 |
| [DecisionAxisCard.tsx](src/components/DecisionAxisCard.tsx) | 판단 축의 상태·근거·누락·다음 행동 표시 |
| [CandidateNextActions.tsx](src/components/CandidateNextActions.tsx) | 입력·분석·검토 화면으로 연결하는 후보별 보완 행동 |
| [CaseBuyerProfile.tsx](src/components/CaseBuyerProfile.tsx) | 예산·관심 지역·면적 등 공통 매수 조건 |
| [candidateSimulationSeed.ts](src/lib/candidateSimulationSeed.ts) | 후보 가격·유형과 저장된 자금 조건의 입력 전달 |
| [sessionStore.ts](src/lib/sessionStore.ts) | 세션 값 읽기·쓰기·구독과 프리필 상태 |
| [listingNavigation.ts](src/lib/listingNavigation.ts) | 탐색 정보·케이스·원본 매물의 화면 이동 |
| [ListingAddressFields.tsx](src/components/ListingAddressFields.tsx) · [ListingLinkForm.tsx](src/components/ListingLinkForm.tsx) | 주소 선택과 직접 입력 전환, 조회 이름과 선택 별칭의 분리 저장 |

요약과 비교의 검토 상태는 서버의 같은 판단 결과를 표시한다. 프론트엔드에서 별도 완료 기준을 계산하거나 미확인·만료 금액을 0으로 바꾸지 않는다. `등록 자료 확인`은 거래 안전 인증이 아니며, 미확인 상태에서도 사용자가 선택하면 보완 필요 표시를 유지한다.

자금 화면의 주택 수는 취득 후 기준이다. 후보별 저장 조건을 우선 복원하고 공통 조건 적용은 사용자 선택으로 제공한다. 비상자금을 재차 차감하지 않는다. 세부 기준은 [자금 입력 문서](../docs/funding-consistency.md)를 따른다.

## 로컬 실행

이 환경의 Node·npm은 Windows에 있다. 백엔드·작업 실행기·DB·Redis를 먼저 실행한 뒤 `frontend/`에서 PowerShell로 실행한다. 기본 Docker 포트는 프론트엔드 3002·API 8002이며 해당 포트의 기존 프론트엔드와 동시에 띄우지 않는다.

```powershell
npm ci
$env:NEXT_PUBLIC_API_URL = "http://localhost:8002"
npm run dev -- -p 3002
```

`NEXT_PUBLIC_API_URL` 미설정 시 rewrite의 기본 API는 8000이므로 로컬의 8002 사용 시 명시한다. Docker에서는 내부 서비스 주소를 사용한다. 전체 Docker 실행과 환경 변수 양식은 [루트 README](../README.md)를 따른다.

## 검증

`frontend/`에서 타입·린트·빌드를 실행한다.

```powershell
npx tsc --noEmit
npm run lint
npm run build
```

후보별 자금과 의사결정 화면 검증은 저장소 루트에서 실행한다.

```powershell
node scripts/verify_candidate_funding_browser.cjs
node scripts/verify_decision_assessment_browser.cjs
node scripts/verify_listing_address_browser.cjs
```

기본 모드는 실행 중인 Docker 서비스를 사용한다. API 주소를 인자로 주면 개발 프론트엔드를 별도로 띄우는 모드다. 연결한 API에 임시 계정을 만들고 종료 시 삭제하므로 pytest의 격리 DB 검사와 구분한다. CI에는 매물 등록·화면 이동·서비스 품질·자금·다섯 판단 축·주소 등록의 브라우저 검증과 아티팩트 보관이 있다. 주소 검사의 가상 응답과 실제 주소 조회의 확인 범위는 [주소 기반 등록](../docs/address-based-listing.md)을 따른다.

프론트엔드 단위 테스트는 아직 없다. 390px 화면 검증은 반응형 웹 검사이며 모바일 앱 검증이 아니다. 최신 통과 결과와 실제 AVM·법률·매물 정보의 미검증 범위는 [검증 기록](../docs/decision-assessment.md#검증-범위)을 확인한다.
