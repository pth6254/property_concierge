#!/bin/sh
# Kotlin 단위·통합 검증은 서비스 Compose 네트워크나 .env를 상속하지 않는다.
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$task_root"
task_reports="$task_root/evaluation-results/platform"
mkdir -p "$task_reports"
docker image inspect property_concierge_backend:latest >/dev/null 2>&1 || {
  echo '마이그레이션 이미지가 필요합니다: sh scripts/compose.sh local build api' >&2
  exit 1
}
docker build -f infrastructure/docker/Dockerfile.platform --target build -t property_concierge_platform_tests:latest .
# 호스트 네트워크는 테스트가 무작위로 공개한 저장소 포트에 접근하기 위한 것이다.
# DB URL은 Testcontainers가 생성하며 외부 DB 환경변수를 전달하지 않는다.
task_status=0
docker run --rm --network host \
  --mount type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock \
  --mount "type=bind,source=$task_reports,target=/reports" \
  -e PLATFORM_MIGRATION_IMAGE=property_concierge_backend:latest \
  property_concierge_platform_tests:latest \
  sh -eu -c '
    mkdir -p /reports/unit
    cp /build/target/surefire-reports/TEST-*.xml /reports/unit/
    exec mvn -B -ntp -Pplatform-integration -Dplatform.test.reports=/reports failsafe:integration-test failsafe:verify
  ' \
  > "$task_reports/integration.log" 2>&1 || task_status=$?
tail -n 20 "$task_reports/integration.log"
exit "$task_status"
