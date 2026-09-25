# 실거래 데이터 주기 갱신

국토부 매매 실거래 배치는 완료된 월이라도 마지막 조회 후 일정 시간이 지나면 다시 조회한다. 당월·전월은 12시간, 그 이전 월은 30일을 기준으로 한다. 정정·해제 신고를 반영하기 위한 정책이며 원천 API의 발표 지연까지 완전히 복원하는 것은 아니다.

운영 Compose의 `transaction-refresh` 서비스는 `maintenance` 프로필에서만 실행된다. API의 마이그레이션과 기동이 끝난 뒤 별도 컨테이너에서 서울특별시 최근 12개월을 기본 7일 주기로 검사한다. 완료 월의 TTL이 남았으면 API를 다시 호출하지 않는다.

```bash
docker compose -f docker-compose.yml --profile maintenance up -d --build
```

`TRANSACTION_REFRESH_INTERVAL_HOURS`, `TRANSACTION_REFRESH_MONTHS`, `TRANSACTION_REFRESH_WORKERS`, `TRANSACTION_REFRESH_SIDO`로 요청량을 조절한다. 처음 활성화할 때는 계획 작업 수와 국토부 API 할당량을 확인한다. 한 번의 배치가 실패하면 오류를 기록하고 다음 주기에 다시 시도하며, 수집 실패를 빈 거래월로 저장하지 않는다. 매물 원문 수집과 법령 코퍼스 갱신은 이 서비스에 포함되지 않는다.
