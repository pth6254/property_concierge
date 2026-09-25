# Windows 로컬 Docker 접속 유지

이 PC는 Docker Desktop 대신 Ubuntu WSL의 systemd Docker를 사용한다.
Windows에서 실행한 WSL 세션이 끝나면 배포판이 유휴 종료될 수 있다.
Docker의 `restart: unless-stopped`는 Docker 엔진 자체가 종료된 동안에는
서비스를 살리지 못한다. 따라서 재빌드 직후 HTTP 200 확인만으로는 충분하지 않다.

2026-09-25 접속 장애에서 Windows의 3001 연결 거부, 모든 컨테이너의 동시
재기동, 이전 부팅 로그의 `daemonShuttingDown=true`와 WSL의
`InitTerminateInstanceInternal` 종료 기록을 확인했다.

## 실행

PowerShell에서 다음 명령으로 숨김 WSL 세션을 유지한다.
이미 실행 중이면 중복 생성하지 않는다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/keep-docker-wsl-alive.ps1
```

현재 사용자 로그인 때도 시작하려면 `-Action InstallStartup`을 붙인다.
사용자의 시작프로그램 폴더에 `Property Concierge Docker.lnk`를 생성한다.
프로젝트를 이동하면 기존 바로가기를 제거하고 다시 등록한다.
해제는 `-Action RemoveStartup`, 실행 중인 유지 프로세스 종료는 `-Action Stop`이다.
다른 프로젝트 컨테이너를 명시적으로 재시작하거나 종료하지 않는다.
이 세션은 Ubuntu 전체의 유휴 종료를 막으므로 WSL 메모리는 계속 사용한다.
PC 종료·절전·로그아웃 중 서비스 제공을 보장하지 않으며, 상시 운영은 별도 서버가 필요하다.

## 서비스 재빌드와 확인

이 PC의 3000·8000 포트는 다른 프로젝트가 사용하므로 아래 포트를 유지한다.

```powershell
wsl -e env API_BIND_PORT=18001 FRONTEND_PORT=3001 docker compose -f docker-compose.yml up -d --build
curl.exe -f http://localhost:3001/login
curl.exe -f http://localhost:18001/health
```

브라우저 접속: http://localhost:3001

검증 시 일회성 WSL 명령을 추가 실행하지 않고 Windows HTTP 요청만 수 분간
반복해 접속이 유지되는지 확인한다. WSL 명령 자체가 종료된 배포판을 다시 깨워
장애를 숨길 수 있기 때문이다.

참고: [Microsoft WSL systemd 문서](https://learn.microsoft.com/en-us/windows/wsl/systemd)는
systemd 서비스가 WSL 인스턴스 수명을 유지하지 않는다고 설명한다.
