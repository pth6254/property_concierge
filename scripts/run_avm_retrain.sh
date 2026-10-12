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

while true; do
  python -m backend.tools.retrain_apartment_avm --live-dir "$live_dir" --sido "$sido" || \
    echo "아파트 AVM 재학습 실패: 기존 모델을 유지하고 다음 주기에 다시 시도합니다" >&2
  sleep "$((interval_hours * 3600))"
done
