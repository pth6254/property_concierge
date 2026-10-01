# 실행·배포 설정

`compose/`는 서비스 구성, `docker/`는 이미지 빌드, `proxy/`는 Caddy, `database/`는 초기 DB 설정이다.
빌드·볼륨의 상대 경로 기준은 저장소 루트로 고정한다. `.env`도 루트에서 읽는다.

```bash
sh scripts/compose.sh local up -d --build
sh scripts/compose.sh dev up -d pgvector redis
sh scripts/compose.sh production up -d --build
```

PowerShell에서는 `./scripts/compose.ps1 local up -d --build`로 WSL Docker를 호출한다.
`local`은 베이스 설정만, `dev`는 소스 마운트·DB 포트 개발 오버레이,
`production`은 도메인·TLS 오버레이를 적용한다. 공개 운영은 서버·도메인 설정이 추가로 필요하다.

기존 Compose 서비스 식별자 `core/api/frontend`, 이미지·컨테이너 이름과 프로젝트명
`property_concierge`는 유지한다. 따라서 DB·Redis 볼륨과 내부 주소는 폴더 이동으로 바뀌지 않는다.
`docker compose config`에는 실제 시크릿이 포함되므로 출력을 공유하지 않는다.
