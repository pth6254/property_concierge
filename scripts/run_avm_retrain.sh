#!/bin/sh
# 별도 유지보수 컨테이너에서 아파트 혼합 AVM을 매달 재학습한다. 하루마다 새 완결월이 생겼는지만 확인하고,
# 학습 기준월이 최신이면 바로 넘어간다. 평가·판정·교체는 backend.tools.retrain_apartment_avm이 맡는다.
set -eu

interval_hours="${AVM_RETRAIN_CHECK_HOURS:-24}"
live_dir="${AVM_APARTMENT_LIVE_DIR:?AVM_APARTMENT_LIVE_DIR가 필요합니다}"
sido="${AVM_RETRAIN_SIDO:-서울특별시}"

case "$interval_hours" in
  ''|*[!0-9]*|0) echo "확인 주기는 양의 정수(시간)여야 합니다" >&2; exit 2 ;;
esac

# 호스트 재시작 직후에는 DB가 아직 기동 중이라 첫 단계가 실패하고 하루를 통째로 잃었다(2026-10-15~23 실제 발생).
# 접속될 때까지 기다린 뒤 시작한다.
wait_for_database() {
  for _ in $(seq 1 60); do
    python -c "from db.base import get_engine; get_engine().connect().close()" >/dev/null 2>&1 && return 0
    sleep 10
  done
  echo "DB 접속 대기 시간 초과: 이번 주기를 건너뜁니다" >&2
  return 1
}

while true; do
  if ! wait_for_database; then sleep 600; continue; fi
  # 공동주택 공시가격(호별)을 하루 호출 상한 안에서 이어서 수집한다. 실패해도 재학습은 계속한다.
  python -m backend.tools.ingest_apartment_unit_prices --sido "$sido" --max-calls "${APT_UNIT_PRICE_MAX_CALLS:-8000}" || \
    echo "공동주택 공시가격 수집 실패: 다음 주기에 이어서 시도합니다" >&2
  python -m backend.tools.retrain_apartment_avm --live-dir "$live_dir" --sido "$sido" || \
    echo "아파트 AVM 재학습 실패: 기존 모델을 유지하고 다음 주기에 다시 시도합니다" >&2
  sleep "$((interval_hours * 3600))"
done
