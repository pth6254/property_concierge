"""후보 분석 유형별 유효기간을 결정한다.

권리관계는 등기 변동 가능성이 커 가장 짧게, 자금분석은 금리 변화를 고려해 그다음으로,
실거래 기반 시세분석은 월 단위 갱신 주기에 맞춰 관리한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

VALID_DAYS = {"appraisal": 30, "simulation": 14, "rights": 7}
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def expiry_for(analysis_type: str, analyzed_at: str) -> str:
    analyzed = datetime.fromisoformat(analyzed_at)
    return (analyzed + timedelta(days=VALID_DAYS[analysis_type])).strftime(DATETIME_FORMAT)


def analysis_freshness(
    analysis_type: str, analyzed_at: str | None, expires_at: str | None,
    status: str = "completed", now: datetime | None = None,
) -> dict:
    if status != "completed":
        return {"status": status, "expires_at": expires_at, "days_remaining": None}
    if analysis_type not in VALID_DAYS or not analyzed_at:
        return {"status": "stale", "expires_at": expires_at, "days_remaining": None}
    try:
        expiry_text = expires_at or expiry_for(analysis_type, analyzed_at)
        expiry = datetime.fromisoformat(expiry_text)
    except (TypeError, ValueError):
        return {"status": "stale", "expires_at": expires_at, "days_remaining": None}
    current = now or datetime.now()
    remaining_seconds = (expiry - current).total_seconds()
    return {
        "status": "completed" if remaining_seconds >= 0 else "stale",
        "expires_at": expiry_text,
        "days_remaining": max(0, int(remaining_seconds // 86400)),
    }
