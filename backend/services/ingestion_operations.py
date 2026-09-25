"""관리자가 선택한 지역·원천의 누락/실패 월만 재수집한다."""
import time
from sqlalchemy import select
from db.base import session_scope
from db.models import IngestLog, LegalRegion
from backend.tools.ingest_transactions import _endpoints_for, _recent_months, _ingest_one
from backend.price_engine import _endpoint_name, MOLIT_API_KEY
from backend.transaction_store import _is_fresh


def coverage(lawd_code: str, months: int) -> dict:
    periods = _recent_months(months)
    with session_scope() as session:
        name = session.scalar(select(LegalRegion.full_name).where(LegalRegion.lawd_code == lawd_code,
                                                                 LegalRegion.level == "sigungu"))
        if not name:
            raise ValueError("등록된 시군구가 없습니다")
        logs = {(r.endpoint, r.category, r.deal_ym): r for r in session.scalars(select(IngestLog).where(
            IngestLog.lawd_cd == lawd_code, IngestLog.deal_ym.in_(periods)))}
        items = []
        for category, url in _endpoints_for(["주거용", "상업용", "업무용", "산업용", "토지"]):
            endpoint = _endpoint_name(url)
            for month in periods:
                row = logs.get((endpoint, category, month))
                status = "missing" if not row else row.status
                if row and status == "completed" and not _is_fresh(row.fetched_at, month):
                    status = "stale"
                if row and status == "running" and time.time() - (row.started_at or 0) > 3600:
                    status = "interrupted"
                items.append({"endpoint": endpoint, "category": category, "month": month, "status": status,
                              "count": row.row_count if row else 0,
                              "fetched_at": row.fetched_at if row else None})
    return {"region": name, "lawd_code": lawd_code, "items": items,
            "counts": {s: sum(r["status"] == s for r in items) for s in ["completed", "missing", "failed", "stale", "running", "interrupted"]}}


def retry_one(payload: dict) -> dict:
    current = coverage(payload["lawd_code"], 24)
    item = next((r for r in current["items"] if r["endpoint"] == payload["endpoint"] and r["month"] == payload["month"]), None)
    if not item or item["status"] not in {"missing", "failed", "interrupted", "stale"}:
        return {"status": "skipped"}
    if not MOLIT_API_KEY:
        return {"error": "국토부 API 키가 설정되지 않았습니다"}
    url = next(url for category, url in _endpoints_for([item["category"]]) if _endpoint_name(url) == item["endpoint"])
    outcome, _ = _ingest_one((current["region"], payload["lawd_code"], item["category"], url, item["month"]),
                             MOLIT_API_KEY.replace("+", "%2B").replace("=", "%3D"), False)
    return {"status": outcome, **({"error": "수집에 실패했습니다. 운영 현황을 확인하세요."} if outcome == "failed" else {})}
