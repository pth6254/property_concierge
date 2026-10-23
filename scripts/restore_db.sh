#!/usr/bin/env bash
#
# restore_db.sh — backup_db.sh 로 만든 덤프를 복원한다.
#
# 주의: 대상 DB를 DROP 후 재생성한다 — 되돌릴 수 없다.
#       운영 인스턴스에 실행하기 전 반드시 대상을 재확인할 것.
#
# 사용법:
#   ./scripts/restore_db.sh backups/property_concierge_20260725_030000.dump
#   ./scripts/restore_db.sh --check backups/property_concierge_20260725_030000.dump
#     → 서비스 DB를 건드리지 않고 점검용 DB(real_estate_restore_check)에 복원해 주요 테이블 건수를 비교하고 지운다(복구 리허설).

set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PROJECT_ROOT="$(dirname "$_SCRIPT_DIR")"

CHECK_ONLY=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=1
  shift
fi
DUMP_FILE="${1:-}"
if [[ -z "$DUMP_FILE" || ! -f "$DUMP_FILE" ]]; then
  echo "사용법: $0 <덤프파일.dump>" >&2
  echo "예:     $0 backups/property_concierge_20260725_030000.dump" >&2
  exit 1
fi

if [[ -f "$_PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  # Windows에서 편집한 CRLF도 WSL의 bash가 같은 값으로 읽도록 한다(backup_db.sh와 같음).
  source <(sed 's/\r$//' "$_PROJECT_ROOT/.env")
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-real_estate_db}"

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "오류: POSTGRES_PASSWORD 가 설정되지 않았습니다 (.env 확인)." >&2
  exit 1
fi

SOURCE_DB="$POSTGRES_DB"
if [[ "$CHECK_ONLY" -eq 1 ]]; then
  # 리허설은 서비스 DB 대신 점검용 DB에만 복원한다. 서비스 DB 이름과 같으면 중단한다.
  POSTGRES_DB="real_estate_restore_check"
  if [[ "$POSTGRES_DB" == "$SOURCE_DB" ]]; then echo "점검용 DB 이름이 서비스 DB와 같습니다" >&2; exit 1; fi
  echo "[check] '$DUMP_FILE' 를 점검용 DB '$POSTGRES_DB' 에 복원합니다 (서비스 DB '$SOURCE_DB' 는 변경하지 않음)"
else
  echo "!!! 대상 DB '$POSTGRES_DB' 의 기존 데이터를 전부 지우고 '$DUMP_FILE' 로 덮어씁니다 !!!"
  read -r -p "계속하려면 DB 이름을 그대로 입력하세요 ($POSTGRES_DB): " CONFIRM
  if [[ "$CONFIRM" != "$POSTGRES_DB" ]]; then
    echo "취소되었습니다."
    exit 1
  fi
fi

echo "[restore] 컨테이너로 덤프 파일 복사 중..."
docker cp "$DUMP_FILE" property_concierge_pgvector:/tmp/restore.dump

echo "[restore] 기존 연결 종료 + DB 재생성..."
PGPASSWORD="$POSTGRES_PASSWORD" docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" \
  property_concierge_pgvector \
  psql -U "$POSTGRES_USER" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();"

PGPASSWORD="$POSTGRES_PASSWORD" docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" \
  property_concierge_pgvector \
  dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB"

PGPASSWORD="$POSTGRES_PASSWORD" docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" \
  property_concierge_pgvector \
  createdb -U "$POSTGRES_USER" "$POSTGRES_DB"

# pgvector 익스텐션은 init.sql 이 아니라 여기서 다시 걸어줘야 한다
# (createdb 는 빈 DB만 만들고 init.sql은 컨테이너 최초 기동시에만 실행됨).
PGPASSWORD="$POSTGRES_PASSWORD" docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" \
  property_concierge_pgvector \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS vector;"

echo "[restore] 덤프 복원 중..."
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" \
  property_concierge_pgvector \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges /tmp/restore.dump

docker exec property_concierge_pgvector rm -f /tmp/restore.dump

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  # 덤프 시점 이후 서비스 DB가 바뀌었을 수 있으므로 건수는 참고로 나란히 보여주고, 복원 DB가 비어 있지 않은지만 판정한다.
  status=0
  for table in users purchase_cases case_properties history transactions legal_regions apartment_unit_prices; do
    restored=$(docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" property_concierge_pgvector psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM $table" 2>/dev/null || echo "없음")
    live=$(docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" property_concierge_pgvector psql -U "$POSTGRES_USER" -d "$SOURCE_DB" -Atc "SELECT count(*) FROM $table" 2>/dev/null || echo "없음")
    echo "[check] $table: 복원 $restored / 현재 서비스 $live"
    if [[ "$table" =~ ^(users|transactions|legal_regions)$ && ( "$restored" == "없음" || "$restored" == "0" ) ]]; then status=1; fi
  done
  docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" property_concierge_pgvector dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB"
  [[ "$status" -eq 0 ]] && echo "[check] 복구 리허설 통과 (점검용 DB 삭제)" || echo "[check] 복구 리허설 실패: 핵심 테이블이 비었습니다" >&2
  exit "$status"
fi

echo "[restore] 완료. API·작업 실행기를 다시 띄워 연결 풀을 새로 맺으세요:"
echo "  sh scripts/compose.sh local up -d --no-deps --force-recreate api job-worker"
