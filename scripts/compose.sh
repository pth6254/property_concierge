#!/bin/sh
# 프로젝트 경로를 고정해야 기존 네트워크·볼륨과 루트 .env를 그대로 사용한다.
set -eu
workspace_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mode=${1:-local}
if [ "$#" -gt 0 ]; then shift; fi
case "$mode" in
  local) set -- -f "$workspace_root/infrastructure/compose/compose.yml" "$@" ;;
  dev) set -- -f "$workspace_root/infrastructure/compose/compose.yml" -f "$workspace_root/infrastructure/compose/compose.override.yml" "$@" ;;
  production) set -- -f "$workspace_root/infrastructure/compose/compose.yml" -f "$workspace_root/infrastructure/compose/compose.production.yml" "$@" ;;
  *) echo '사용법: sh scripts/compose.sh local|dev|production <compose 인수>' >&2; exit 2 ;;
esac
exec docker compose --project-directory "$workspace_root" -p property_concierge "$@"
