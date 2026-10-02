"""공식 거래의 관측 시점과 재현용 지문. 서비스 지문은 국토부 거래 고유번호가 아니다."""
import hashlib
import json
from datetime import datetime, timezone


def attach_transaction_evidence(rows, endpoint, sigungu_code, deal_month, observed_at):
    for sample in rows:
        source = {key: sample.get(key) for key in (
            "apt_name", "dong", "jibun", "area_sqm", "floor", "price", "deal_year", "deal_month", "deal_day")}
        fingerprint = hashlib.sha256(json.dumps([endpoint, sigungu_code, deal_month, source],
                                                 ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        sample["transaction_ref"] = "molit-sha256:" + fingerprint
        sample["source_endpoint"] = endpoint
        sample["source_sigungu_code"] = sigungu_code
        sample["source_deal_month"] = deal_month
        sample["observed_at"] = datetime.fromtimestamp(observed_at, timezone.utc).isoformat()
        sample["source_url"] = "https://rt.molit.go.kr/"
    return rows
