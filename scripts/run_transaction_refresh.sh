#!/bin/sh
# 별도 유지보수 컨테이너에서만 주기 수집을 실행한다. API 워커 기동과 분리한다.
set -eu

interval_hours="${TRANSACTION_REFRESH_INTERVAL_HOURS:-168}"
months="${TRANSACTION_REFRESH_MONTHS:-12}"
workers="${TRANSACTION_REFRESH_WORKERS:-2}"
sido="${TRANSACTION_REFRESH_SIDO:-서울특별시}"

case "$interval_hours:$months:$workers" in
  *[!0-9:]*|:*|*::*|*:|0:*|*:0:*|*:0) echo "수집 주기·개월 수·워커 수는 양의 정수여야 합니다" >&2; exit 2 ;;
esac

# 호스트 재시작 직후 DB가 기동 중이면 첫 수집이 실패하고 다음 주기(기본 7일)까지 기다리게 된다.
# 정기 백업·AVM 재학습에서 실제로 겪은 문제라 같은 방식으로 DB 접속을 기다린다.
wait_for_database() {
  for _ in $(seq 1 60); do
    python -c "from db.base import get_engine; get_engine().connect().close()" >/dev/null 2>&1 && return 0
    sleep 10
  done
  return 1
}

while true; do
  if ! wait_for_database; then
    echo "DB 접속 대기 시간 초과: 10분 뒤 다시 시도합니다" >&2
    sleep 600
    continue
  fi
  python -m backend.tools.ingest_transactions --sido "$sido" --months "$months" --workers "$workers" --yes || \
    echo "실거래 재수집 실패: 다음 주기에 다시 시도합니다" >&2
  sleep "$((interval_hours * 3600))"
done
