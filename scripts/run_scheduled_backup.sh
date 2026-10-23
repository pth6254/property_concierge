#!/bin/sh
# 자동 백업은 DB 포트가 공개되지 않은 같은 Docker 네트워크에서 수행한다.
# 호스트 재시작 직후에는 DB가 아직 기동 중이라 첫 백업이 실패하고 하루를 기다렸다(2026-10-23 실제 발생,
# 빈 .partial 3개). DB 응답을 기다린 뒤 백업하고, 실패하면 짧은 간격으로 다시 시도한다.
set -eu
mkdir -p /backups
retry_seconds="${BACKUP_RETRY_SECONDS:-600}"
while true; do
  success=0
  for _ in $(seq 1 60); do
    pg_isready -h pgvector -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1 && break
    sleep 10
  done
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
    # 실패한 부분 파일은 복원에 쓸 수 없고 보관 정리 대상에서도 빠지므로 바로 지운다.
    rm -f "${target}.partial"
    printf '{"status":"failed","checked_at":%s,"bytes":0}\n' "$(date +%s)" > /backups/backup-status.json.tmp
    mv /backups/backup-status.json.tmp /backups/backup-status.json
    sleep "$retry_seconds"
    continue
  fi
  sleep "${BACKUP_INTERVAL_SECONDS:-86400}"
done
