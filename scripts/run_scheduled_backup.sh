#!/bin/sh
# 자동 백업은 DB 포트가 공개되지 않은 같은 Docker 네트워크에서 수행한다.
set -eu
mkdir -p /backups
while true; do
  success=0
  stamp=$(date -u +%Y%m%d_%H%M%S)
  target="/backups/property_concierge_${stamp}.dump"
  if pg_dump -h pgvector -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "${target}.partial"; then
    if pg_restore --list "${target}.partial" >/dev/null; then
      mv "${target}.partial" "$target"
      bytes=$(wc -c < "$target")
      epoch=$(date +%s)
      printf '{"status":"ok","checked_at":%s,"bytes":%s}\n' "$epoch" "$bytes" > /backups/backup-status.json.tmp
      mv /backups/backup-status.json.tmp /backups/backup-status.json
      echo "정기 DB 백업 완료: ${bytes} bytes"
      success=1
    else
      echo "정기 DB 백업 검증 실패" >&2
    fi
  else
    echo "정기 DB 백업 실패" >&2
  fi
  if [ "$success" -eq 0 ]; then
    printf '{"status":"failed","checked_at":%s,"bytes":0}\n' "$(date +%s)" > /backups/backup-status.json.tmp
    mv /backups/backup-status.json.tmp /backups/backup-status.json
  fi
  sleep "${BACKUP_INTERVAL_SECONDS:-86400}"
done
