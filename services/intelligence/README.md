# Intelligence 서비스

LLM·LangGraph·RAG·임베딩·AVM·랭킹·문서 분석과 공식 데이터 수집·분석을 담당한다.
사용자 인증·업무 저장·고정 금융 수식은 [Platform](../platform/README.md)의 내부 API를 호출한다.

| 경로 | 역할 |
|---|---|
| `api/` | 내부 HTTP 계약, AI 실행기, 작업·저장 클라이언트 |
| `backend/` | 분석 그래프, 모델, 데이터 수집·검색·랭킹 |
| `db/` | 데이터·분석 저장과 공유 스키마의 Alembic 마이그레이션 |
| `schemas/` | 분석 요청·결과의 Pydantic 계약 |
| `evaluation/` | 검색·계산·대화·의사결정 평가 |

루트 [AGENTS.md](../../AGENTS.md)의 데이터·보안·검증 제약을 따른다.
공통 스키마의 DDL은 현재 이 서비스의 Alembic만 실행한다. Spring은 자동 DDL을 생성하지 않는다.
`data/`, `backups/`, `evaluation-results/`, `.env`는 저장소 루트의 상태·설정이며 소스와 구분한다.

설치·검증은 저장소 루트에서 실행한다.

```bash
./venv-wsl/bin/python -m pip install -r services/intelligence/requirements.txt
./venv-wsl/bin/python -m pip install --no-deps -e services/intelligence
./venv-wsl/bin/python scripts/run_isolated_tests.py tests/ -q
```

내부 계약: [contracts](../../contracts/README.md). 개발 실행: `sh scripts/compose.sh dev up -d`.
