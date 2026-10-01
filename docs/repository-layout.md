# 서비스 책임 중심 저장소 구조

2026-10-01에 사용자 요청에 따라 인증·거래 플랫폼, AI·데이터 분석, 웹 화면과 실행 인프라를 분리했다.
언어가 아니라 서비스의 책임을 폴더 기준으로 사용한다. 내부 패키지의 도메인 경계와 API 동작은 유지한다.

| 이전 경로 | 현재 경로 | 책임 |
|---|---|---|
| `core-service/` | `services/platform/` | 인증·권한·매물·케이스·거래 상태·고정 계산·업무 저장·운영 API |
| `api/`, `backend/`, `db/`, `schemas/`, `evaluation/` | `services/intelligence/` 아래 동일 이름 | 내부 AI 계약·LLM·RAG·AVM·랭킹·데이터 분석·평가 |
| `frontend/` | `web/` | Next.js 사용자 화면 |
| 루트 Dockerfiles | `infrastructure/docker/` | platform·intelligence·web 이미지 |
| 루트 Compose 파일 | `infrastructure/compose/` | 베이스·개발·HTTPS 운영 구성 |
| `docker/Caddyfile*`, `docker/init.sql` | `infrastructure/proxy/`, `infrastructure/database/` | 프록시·DB 초기화 |
| 내부 명세 분산 | `contracts/v1/` | 코드에서 생성한 OpenAPI와 플랫폼 호출 계약 |

`scripts/`, `tests/`, `docs/`는 통합 운영·검증·설명을 담당하므로 루트에 유지한다.
`data/`, `backups/`, `evaluation-results/`, `.env`, 로컬 가상환경은 상태·설정·산출물이다.
기존 데이터·계정·DB 스키마를 이동하거나 삭제하지 않았다.

## 실행 경로

Compose를 직접 호출할 때는 저장소 루트를 `--project-directory`로 지정해야 한다.
실수로 다른 프로젝트 이름의 새 DB 볼륨을 만들지 않도록 실행 도구가 `-p property_concierge`를 고정한다.

```bash
sh scripts/compose.sh local up -d --build
sh scripts/compose.sh dev up -d pgvector redis
sh scripts/compose.sh production up -d --build
```

PowerShell: `./scripts/compose.ps1 local up -d --build`.
루트에서 옵션 없이 `docker compose up`을 실행하는 이전 방식은 사용하지 않는다.
Compose 서비스 이름·이미지·컨테이너 이름은 유지해 네트워크와 볼륨 연결을 보존한다.
웹 3002, 공개 API 8002, 내부 AI 8000의 경계도 같다.

Python을 직접 실행할 때는 `services/intelligence`를 editable package로 설치한다.
`concierge_workspace.py`는 서비스 코드 경로와 루트 데이터 경로를 구분하며,
운영 스크립트는 같은 경로 설정을 사용한다. 루트에 이전 Python 구현이나 호환용 복제 폴더를 두지 않는다.

```bash
./venv-wsl/bin/python -m pip install -r services/intelligence/requirements.txt
./venv-wsl/bin/python -m pip install --no-deps -e services/intelligence
./venv-wsl/bin/python -m alembic -c services/intelligence/alembic.ini current
./venv-wsl/bin/python scripts/run_isolated_tests.py tests/ -q
./venv-wsl/bin/python scripts/run_spring_tests.py --browser
./venv-wsl/bin/python scripts/export_service_contracts.py --check
```

공유 스키마의 마이그레이션은 `services/intelligence/db/migrations/`에 유지한다.
Spring에 별도 DDL 책임을 추가하지 않는다. 순수 분석 모듈의 Python import 이름도 그대로다.

## 이번 이동 검증

- 격리 PostgreSQL·Redis를 사용하는 Python 회귀 테스트: 1,095 통과·1 건너뜀.
- Spring 실제 저장·권한·작업·변경 재검토 연결 18개, 계산 검증 6개, 프록시 2개 통과.
- 브라우저 6종: 등록·후보·선택·변경 재검토·복원, 이동, 공통 조건, 자금, 다섯 축, 주소·별칭 확인.
- `web/` 타입 검사·린트·프로덕션 빌드, 세 서비스 Docker 빌드 통과.
- 로컬·HTTPS 운영 Compose 계약과 코드에서 생성한 내부 계약 일치 확인.
- 고정·가상 입력 오프라인 평가 34건 통과.
- 새 경로로 로컬 Docker 재기동 후 웹 3002·API 8002, 실제 작업 실행·결과 저장·SSE,
  카카오 주소 조회 연결 확인. API·작업 실행기의 주요 Python 모듈 29개가 현재 소스와 일치한다.

브라우저 AVM 결과는 고정 검증 자료다. 이 이동 검증은 실제 LLM·AVM의 정확도나 전국 데이터 완성도를 뜻하지 않는다.
