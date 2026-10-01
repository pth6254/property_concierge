# Platform 서비스

사용자 인증·사용자 매물·매수 케이스·후보 선택·거래 준비·분석 이력·Redis 작업 저장을 담당한다.
대출·취득비용·세금·현금흐름·LTV/DSR·수익 계산도 담당한다. LLM·RAG·AVM 등 모델 추정은 Python에 두며,
자연어 조건과 계산 결과를 내부 계약으로 주고받는다. [계산 책임과 검증](../../docs/calculation-architecture.md)을 따른다.
공개 업무 API·OAuth·비밀번호 재설정·메일·탈퇴·주소·운영·AI 접수는 이 서비스가 담당한다. 설정과 검증 범위는 [백엔드 전환 안내](../../docs/backend-migration.md)를 따른다.

기본 Compose의 공개 API 8002는 이 서비스다. 웹 3002의 Caddy도 이 서비스에 `/api/*`를 전달한다.
Python API와 실행기는 같은 내부 저장 계약을 사용하며 연결 실패를 Python SQL로 대체하지 않는다.
이전된 영역의 Python SQL·고정 금융 수식은 제거했다. Python 함수는 기존 호출 계약을 보존하는
내부 클라이언트이며, 테스트도 같은 Kotlin 구현을 호출한다. 기존 계산 54건의 결과는 고정 회귀 자료다.
Python의 일반 API·인증·주소·레이트 리밋 파일 16개와 미사용 요청 스키마를 제거했다.
AI 호출 시 서비스 키와 Spring이 확인한 사용자 ID를 전달하며 브라우저 쿠키는 Python에 전달하지 않는다.
OAuth는 Redis의 1회성 state·PKCE, 재설정은 1회성 토큰·비밀번호 버전 검증을 사용한다.

Kotlin 2.2.21 / Spring Boot 3.5.16 / JVM 21 / Maven을 사용한다. Java 소스로 전환한다는 의미가 아니다.
로컬 JDK·Maven 없이 Docker로 빌드·단위 테스트할 수 있다.

```bash
docker build -f infrastructure/docker/Dockerfile.platform -t property_concierge_core:latest .
```

JDK 21·Maven이 설치된 환경은 `mvn -f services/platform/pom.xml verify`로 단위 테스트한다.
실제 DB·Redis·별도 Python 실행기를 지나는 검증은 루트의 `scripts/run_spring_tests.py`를 사용한다.

필수 입력은 non-null, 미확인 예산·대출·주소·분석 정보는 nullable로 정의한다.
JSON에서 null이 0·false로 바뀌거나 문자열 목록에 null이 들어오는 것을 허용하지 않는다.
DB 변경은 기존 Alembic으로 관리하며 이 서비스는 DDL을 자동 생성하지 않는다.
