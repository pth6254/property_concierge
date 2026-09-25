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

while true; do
  python -m backend.tools.ingest_transactions --sido "$sido" --months "$months" --workers "$workers" --yes || \
    echo "실거래 재수집 실패: 다음 주기에 다시 시도합니다" >&2
  sleep "$((interval_hours * 3600))"
done
