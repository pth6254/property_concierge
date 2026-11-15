#!/bin/sh
# 자동 백업은 DB 포트가 공개되지 않은 같은 Docker 네트워크에서 수행한다.
# 호스트 재시작 직후에는 DB가 아직 기동 중이라 첫 백업이 실패하고 하루를 기다렸다(2026-10-23 실제 발생,
# 빈 .partial 3개). DB 응답을 기다린 뒤 백업하고, 실패하면 짧은 간격으로 다시 시도한다.
set -eu
mkdir -p /backups
retry_seconds="${BACKUP_RETRY_SECONDS:-600}"
interval_seconds="${BACKUP_INTERVAL_SECONDS:-86400}"
case "$interval_seconds" in
  ''|*[!0-9]*|0) echo "BACKUP_INTERVAL_SECONDS는 양의 정수여야 합니다" >&2; exit 2 ;;
esac
# 보관 기간(일). 백업 1회가 약 120MB라 지우지 않으면 한 달에 3GB 이상 쌓인다. 0(기본)이면 지우지 않는다 —
# 기존 설치가 업데이트만으로 백업을 잃지 않게 하고, 새 운영 .env는 .env.example의 값으로 켠다.
retention_days="${BACKUP_RETENTION_DAYS:-0}"
case "$retention_days" in
  ''|*[!0-9]*) echo "BACKUP_RETENTION_DAYS는 0 이상의 정수여야 합니다" >&2; exit 2 ;;
esac

# 덤프 도중 컨테이너가 종료되면(Docker 재시작 등) 아래 실패 처리까지 가지 못해 부분 파일이 남는다(2026-11-14 14개·0.85GB).
# 부분 파일은 이 스크립트만 쓰고(backup_db.sh는 바로 .dump를 쓴다) 한 번에 하나만 실행되므로 시작 시점의 부분 파일은 모두 중단된 것이다.
rm -f /backups/property_concierge_*.dump.partial

# 시작할 때마다 바로 백업하면 Docker가 재시작될 때마다 전체 백업이 쌓인다(2026-11-14 40분 동안 24회 시도).
# 이 스크립트가 검증까지 마친 마지막 백업이 주기 안에 있으면 남은 시간만 기다린다. 기준은 운영 감시가 읽는 같은 기록 파일이라
# 수동 백업(backup_db.sh) 때문에 기록이 오래돼 무응답 알림이 나는 일이 없다. 직전 기록이 실패이면 바로 다시 시도한다.
last_ok=$(sed -n 's/^{"status":"ok","checked_at":\([0-9][0-9]*\),.*/\1/p' /backups/backup-status.json 2>/dev/null || true)
if [ -n "$last_ok" ] && ls /backups/property_concierge_*.dump >/dev/null 2>&1; then
  remaining=$((last_ok + interval_seconds - $(date +%s)))
  # 시계가 뒤로 간 경우에도 한 주기보다 오래 기다리지 않는다.
  if [ "$remaining" -gt "$interval_seconds" ]; then remaining=$interval_seconds; fi
  if [ "$remaining" -gt 0 ]; then
    echo "마지막 정기 백업이 주기 안에 있어 ${remaining}초 뒤에 백업합니다"
    sleep "$remaining"
  fi
fi

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
      # 새 백업이 복원 목록 검증까지 통과한 뒤에만 정리하므로 최신 백업은 항상 남는다.
      if [ "$retention_days" -gt 0 ]; then
        deleted=$(find /backups -maxdepth 1 -name 'property_concierge_*.dump' -mtime "+$retention_days" -print -delete | wc -l)
        if [ "$deleted" -gt 0 ]; then echo "보관 기간 ${retention_days}일 초과 백업 ${deleted}개 삭제"; fi
      fi
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
  sleep "$interval_seconds"
done
