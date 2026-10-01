# 문서 안내

현재 서비스·운영에 사용하는 문서와 재현에 필요한 실측 근거를 관리한다.
현재 구현 상태는 인수인계를 기준으로 읽고, 과거 측정치를 현재 성능으로 해석하지 않는다.

| 분야 | 문서 |
|---|---|
| 시작·방향 | [인수인계](project-handoff.md), [제품 전략](product-strategy.md), [저장소 구조](repository-layout.md) |
| 서비스 책임 | [백엔드 분리](backend-migration.md), [계산 책임](calculation-architecture.md) |
| 사용자 매물 | [주소·별칭](address-based-listing.md), [등록 계약](imported-listings.md), [화면 이동](ui-navigation.md) |
| 의사결정 | [판단 축](decision-assessment.md), [자금 입력](funding-consistency.md) |
| 대화·탐색 | [컨시어지 도구](concierge-decision-tools.md), [챗봇 복원](chat-conversation-restore.md), [동별 비교](dong-market-comparison.md) |
| 운영·데이터 | [운영](operations.md), [WSL 접속 유지](local-docker-wsl.md), [작업 복구](job-recovery.md), [실거래 갱신](transaction-refresh.md), [매물 수집](listing-collection.md) |
| 실측 근거 | [이전 검증 기록](verification-history.md), [단지 조회 성능 문제](complex-recommendation-timeout-2026-09-12.md), [실매물 접근 제한](listing-live-audit-2026-09-25.md) |
| 발표 자료 | [포트폴리오 생성·검증](portfolio/README.md) |

AI 평가 도구는 [Intelligence 평가 안내](../services/intelligence/evaluation/README.md),
서비스 간 명세는 [contracts](../contracts/README.md)를 따른다.

## 2026-10-02 정리

`service-integration-check-2026-09-10.md`, `seoul-apartment-data-2026-09-12.md`,
`seoul-property-data-2026-09-12.md`의 실측은 `verification-history.md`로 합치고 별도 파일은 삭제했다.
`concierge-complex-recommendation.md`의 사용·계약은 컨시어지 도구 문서에, 당시 검증은 실측 기록에 통합했다.
포트폴리오는 원본에서 생성한 `portfolio/index.html` 하나로 제공하며 이전 보관 HTML을 삭제했다.
`portfolio/verification/`은 생성기로 재현할 수 있는 로컬 검사 출력이므로 저장할 필요가 없다.
