# 서비스 간 계약

`platform`이 사용자 인증·권한·업무 저장·고정 계산을 담당하고 `intelligence`가 모델·분석을 담당한다.
브라우저는 platform의 `/api/*`만 사용한다. 내부 API는 `/internal/v1/*`이며 서비스 키가 필요하다.

| 명세 | 범위 |
|---|---|
| [intelligence.openapi.json](v1/intelligence.openapi.json) | FastAPI 내부 AI·데이터·분석 요청과 응답 스키마 |
| [platform-client-contracts.json](v1/platform-client-contracts.json) | Python이 호출하는 Spring 저장·계산 함수의 경로·입력 시그니처·반환 타입 |

저장·계산 명세는 현재 클라이언트 계약의 목록이며 Spring 전체 API의 OpenAPI 명세가 아니다.
스키마·DTO 구현은 각 서비스에 둔다. 서비스 사이에서 구현 코드를 직접 import하지 않는다.

- 인증: `X-Internal-Service-Key`. Spring이 인증한 사용자는 AI 요청의 `X-AI-User-Id`로 전달한다.
- 브라우저 JWT 쿠키는 intelligence에 전달하지 않는다. 저장 계약은 사용자 ID와 소유자 검증을 유지한다.
- 단위: 원·㎡. AVM 내부 만원 표현은 외부 응답 전에 기존 변환 경계를 따른다.
- 미확인 값은 null로 표현한다. 0이나 AI 추정으로 사실을 채우지 않는다.
- 호환되지 않는 경로·필드·단위 변경은 양쪽 호출부·테스트와 함께 수정한다. 버전 헤더 검사는 구현돼 있지 않다.

저장소 루트에서 재생성·검증한다. DB에 연결하거나 LLM을 호출하지 않는다.

```bash
./venv-wsl/bin/python scripts/export_service_contracts.py
./venv-wsl/bin/python scripts/export_service_contracts.py --check
```
