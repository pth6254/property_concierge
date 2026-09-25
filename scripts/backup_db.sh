#!/usr/bin/env bash
#
# backup_db.sh — PostgreSQL 논리 백업 (pg_dump, custom format)
#
# 사용자·이력·활동·실거래가·상담 코퍼스·RAG 벡터스토어가 전부 이 인스턴스
# 하나에 있다. docker-compose 볼륨은 `docker compose down -v` 한 번이면
# 사라지므로, 별도 백업 없이는 복구 수단이 전혀 없다.
#
# 사용법:
#   ./scripts/backup_db.sh                    # backups/ 에 타임스탬프 파일 생성
#   ./scripts/backup_db.sh --out /path/to/dir  # 저장 위치 지정
#
# 주기 실행 예 (cron, 매일 03:00):
#   0 3 * * * cd /path/to/property_concierge && ./scripts/backup_db.sh --out /mnt/backup >> /var/log/pc_backup.log 2>&1
#
# 복구는 restore_db.sh 참고.

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PROJECT_ROOT="$(dirname "$_SCRIPT_DIR")"

OUT_DIR="$_PROJECT_ROOT/backups"
RETENTION_DAYS=14

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT_DIR="$2"; shift 2 ;;
    --retention-days) RETENTION_DAYS="$2"; shift 2 ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 1 ;;
  esac
done

# .env 에서 접속 정보를 읽는다 (docker compose 와 동일한 소스).
if [[ -f "$_PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  # Windows에서 편집한 CRLF도 WSL의 bash가 같은 값으로 읽도록 한다.
  source <(sed 's/\r$//' "$_PROJECT_ROOT/.env")
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-real_estate_db}"

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "오류: POSTGRES_PASSWORD 가 설정되지 않았습니다 (.env 확인)." >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_FILE="$OUT_DIR/property_concierge_${TIMESTAMP}.dump"

echo "[backup] $POSTGRES_DB → $DUMP_FILE"

# custom format(-Fc): pg_restore 로만 복원 가능하지만 압축 + 선택적 복원(테이블 단위)이 된다.
# 컨테이너 이름은 docker-compose.yml 의 container_name 과 일치해야 한다.
PGPASSWORD="$POSTGRES_PASSWORD" docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" \
  property_concierge_pgvector \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  > "$DUMP_FILE"

DUMP_SIZE="$(du -h "$DUMP_FILE" | cut -f1)"
echo "[backup] 완료 ($DUMP_SIZE)"

# 보존 기간 초과 백업 정리
if [[ "$RETENTION_DAYS" -gt 0 ]]; then
  DELETED=$(find "$OUT_DIR" -name 'property_concierge_*.dump' -mtime "+$RETENTION_DAYS" -print -delete | wc -l)
  [[ "$DELETED" -gt 0 ]] && echo "[backup] ${RETENTION_DAYS}일 초과 백업 ${DELETED}개 삭제"
fi

# 삭제 대상이 0개인 정상 백업도 성공 코드로 종료한다.
exit 0
