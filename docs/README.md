# 문서 안내

기능별 설명은 `features/`의 네 문서로 읽는다. 구조·운영·과거 검증은 각각 한 문서로 관리한다.
현재 구현은 인수인계를 기준으로 확인하고, 과거 측정치를 현재 성능으로 해석하지 않는다.

| 분야 | 문서 |
|---|---|
| 매물 | [등록·주소·수집](features/listings.md): 주소·별칭, 직접·URL·CSV 등록, 출처·시점·변경 재검토 |
| 의사결정 | [매수 검토·자금·화면 흐름](features/decision.md): 판단 축, 입력·계산 기준, 비교·선택·다음 행동, [유형별 AVM 기준](features/decision.md#valuation-standards) |
| 챗봇 | [AI 컨시어지·법률 챗봇](features/chat.md): 단지 추천·자금·비교 도구, 대화 기억·복원 |
| 탐색 | [동네 탐색·실거래 비교](features/exploration.md): 행정구역 계층, 집계 조건·한계 |
| 구조 | [아키텍처](architecture.md): 폴더 구조, 서비스·저장·권한·계산 책임, 내부 계약과 [최신 파이프라인](architecture.md#pipelines) |
| 운영 | [운영 안내](operations.md): 관리자·감시·백업·배포·WSL·작업 복구·데이터 갱신 |
| 검증 근거 | [실측·장애 기록](verification-history.md): 과거 데이터·대화·조회 성능·매물 접근 제한 |
| 현재 상태 | [인수인계](project-handoff.md): 완료 범위·남은 작업·검증 경계 |
| 제품 방향 | [제품 전략](product-strategy.md): 목표·출시 범위·고도화 순서 |
| 발표 자료 | [포트폴리오](portfolio/README.md): 원본·이미지·HTML 생성·검증 |

AI 평가 도구는 [Intelligence 평가 안내](../services/intelligence/evaluation/README.md),
서비스 간 명세는 [contracts](../contracts/README.md)를 따른다.

```text
docs/
├── README.md
├── features/
│   ├── listings.md
│   ├── decision.md
│   ├── chat.md
│   └── exploration.md
├── architecture.md
├── operations.md
├── verification-history.md
├── project-handoff.md
├── product-strategy.md
└── portfolio/
```

기능의 사용법·API 계약·제약·검증은 같은 기능 문서에 추가한다. 작은 변경마다 새 문서를 만들지 않는다.
각 통합 문서는 목차와 절별 고유 앵커를 제공한다. README·AGENTS의 링크는 해당 절로 연결한다.
포트폴리오의 원본·이미지·생성기는 별도 산출물이므로 현재 위치를 유지한다.
