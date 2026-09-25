"""
transaction_store.py — 국토부 실거래가 로컬 스토어 (PostgreSQL, SQLAlchemy)

price_engine이 MOLIT API에서 받아온 월 단위 실거래 데이터를
(endpoint, category, lawd_cd, deal_ym) 키로 적재하고,
동일 키 재조회 시 API 호출 없이 로컬 DB에서 반환한다.

적재 경로 2가지:
  1) write-through — price_engine._fetch_one_month 가 API 호출 성공 시 자동 적재
  2) batch ingest  — backend/tools/ingest_transactions.py 로 사전 수집

신선도(TTL) 정책:
  - 완결 월 (기준 2개월 이전): 30일 — 정정·해제 거래 반영 주기
  - 최근 월 (당월·전월):      12시간 — 신고 기한(30일) 내 데이터 계속 유입

이전에는 SQLite 파일(data/transactions.db)이었다. db/base.py 의 공용 세션으로
옮기되, 호출부(price_engine.py, ingest_transactions.py 등)가 기대하는
함수 시그니처는 그대로 유지한다.
"""

from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import delete, distinct, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.base import init_db, session_scope
from db.models import IngestLog, Transaction

TTL_COMPLETE_MONTH = 60 * 60 * 24 * 30   # 30일 — 완결 월
TTL_RECENT_MONTH   = 60 * 60 * 12        # 12시간 — 당월·전월

_INITIALIZED = False

# 저장하는 샘플 필드 (price_engine._parse_items 출력과 1:1)
SAMPLE_FIELDS = [
    "price", "area_sqm", "area_pyeong", "per_sqm",
    "floor", "year_built", "dong", "apt_name",
    "deal_year", "deal_month",
    "deal_day", "bjdong_code", "property_detail",
    "building_area_sqm", "land_area_sqm", "building_use", "jimok",
    "transaction_type", "cancellation_date", "is_cancelled",
]


def is_month_completed(endpoint: str, category: str, lawd_cd: str, deal_ym: str) -> bool:
    """배치 수집에서는 TTL과 무관하게 완료된 월을 다시 받지 않는다."""
    init_store()
    with session_scope() as session:
        log = session.get(IngestLog, (endpoint, category, lawd_cd, deal_ym))
        return bool(log and log.status == "completed")


def should_skip_batch_month(endpoint: str, category: str, lawd_cd: str, deal_ym: str) -> bool:
    """완료 월도 TTL이 지나면 정정·해제 거래를 반영할 수 있게 재조회한다."""
    init_store()
    with session_scope() as session:
        log = session.get(IngestLog, (endpoint, category, lawd_cd, deal_ym))
        if not log or log.status != "completed":
            return False
        return _is_fresh(log.fetched_at, deal_ym)


def mark_month_started(endpoint: str, category: str, lawd_cd: str, deal_ym: str) -> None:
    init_store()
    now = time.time()
    with session_scope() as session:
        stmt = pg_insert(IngestLog).values(
            endpoint=endpoint, category=category, lawd_cd=lawd_cd, deal_ym=deal_ym,
            fetched_at=now, row_count=0, status="running", started_at=now,
            completed_at=None, page_count=0, error_message=None,
        ).on_conflict_do_update(
            index_elements=["endpoint", "category", "lawd_cd", "deal_ym"],
            set_={"status": "running", "started_at": now, "completed_at": None, "error_message": None},
        )
        session.execute(stmt)


def mark_month_failed(endpoint: str, category: str, lawd_cd: str, deal_ym: str, error: str) -> None:
    init_store()
    now = time.time()
    with session_scope() as session:
        stmt = pg_insert(IngestLog).values(
            endpoint=endpoint, category=category, lawd_cd=lawd_cd, deal_ym=deal_ym,
            fetched_at=now, row_count=0, status="failed", started_at=now,
            completed_at=None, page_count=0, error_message=error[:1000],
        ).on_conflict_do_update(
            index_elements=["endpoint", "category", "lawd_cd", "deal_ym"],
            set_={"status": "failed", "error_message": error[:1000]},
        )
        session.execute(stmt)


def init_store():
    """스토어 초기화 (중복 호출 안전)."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    init_db()
    _INITIALIZED = True


# ─────────────────────────────────────────
#  TTL 판정
# ─────────────────────────────────────────

def _ttl_for(deal_ym: str) -> int:
    """완결 월(기준 2개월 이전)이면 긴 TTL, 최근 월이면 짧은 TTL."""
    now = datetime.now()
    try:
        ym = datetime.strptime(deal_ym, "%Y%m")
    except ValueError:
        return TTL_RECENT_MONTH
    months_ago = (now.year - ym.year) * 12 + (now.month - ym.month)
    return TTL_COMPLETE_MONTH if months_ago >= 2 else TTL_RECENT_MONTH


def _is_fresh(fetched_at: float, deal_ym: str) -> bool:
    return (time.time() - fetched_at) <= _ttl_for(deal_ym)


# ─────────────────────────────────────────
#  조회 / 적재
# ─────────────────────────────────────────

def get_month(endpoint: str, category: str, lawd_cd: str, deal_ym: str,
              ignore_ttl: bool = False) -> list[dict] | None:
    """
    적재된 월 데이터 반환.
    미적재 또는 TTL 만료 시 None (→ 호출측이 API 폴백).
    적재됐지만 거래 0건인 월은 빈 리스트 [] 반환 (유효한 결과).
    ignore_ttl=True: 백테스트 등 과거 데이터 분석용 — 만료돼도 반환.
    """
    init_store()
    try:
        with session_scope() as session:
            log = session.get(IngestLog, (endpoint, category, lawd_cd, deal_ym))
            if not log or (not ignore_ttl and not _is_fresh(log.fetched_at, deal_ym)):
                return None

            rows = session.scalars(
                select(Transaction).where(
                    Transaction.endpoint == endpoint,
                    Transaction.category == category,
                    Transaction.lawd_cd == lawd_cd,
                    Transaction.deal_ym == deal_ym,
                )
            )
            return [{f: getattr(r, f) for f in SAMPLE_FIELDS} for r in rows]
    except Exception as e:
        print(f"[tx_store] 조회 오류: {e}")
        return None


def put_month(endpoint: str, category: str, lawd_cd: str, deal_ym: str, samples: list[dict]):
    """
    월 데이터 교체 적재 (기존 행 삭제 후 삽입 — 재수집 멱등).
    API 호출이 '성공'했을 때만 호출할 것 — 실패한 조회를 적재하면
    빈 결과가 TTL 동안 고착된다.
    """
    init_store()
    try:
        with session_scope() as session:
            session.execute(
                delete(Transaction).where(
                    Transaction.endpoint == endpoint,
                    Transaction.category == category,
                    Transaction.lawd_cd == lawd_cd,
                    Transaction.deal_ym == deal_ym,
                )
            )
            if samples:
                session.add_all([
                    Transaction(
                        endpoint=endpoint, category=category, lawd_cd=lawd_cd, deal_ym=deal_ym,
                        **{f: s.get(f) for f in SAMPLE_FIELDS},
                    )
                    for s in samples
                ])
            stmt = pg_insert(IngestLog).values(
                endpoint=endpoint, category=category, lawd_cd=lawd_cd, deal_ym=deal_ym,
                fetched_at=time.time(), row_count=len(samples), status="completed",
                completed_at=time.time(), page_count=1, error_message=None,
            ).on_conflict_do_update(
                index_elements=["endpoint", "category", "lawd_cd", "deal_ym"],
                set_={"fetched_at": time.time(), "row_count": len(samples),
                      "status": "completed", "completed_at": time.time(), "error_message": None},
            )
            session.execute(stmt)
    except Exception as e:
        print(f"[tx_store] 적재 오류: {e}")


def list_ingested_months(endpoint: str, category: str, lawd_cd: str) -> list[str]:
    """해당 지역·유형에 적재된 deal_ym 목록 (오름차순). backtest_avm.py 전용."""
    init_store()
    with session_scope() as session:
        stmt = (
            select(distinct(IngestLog.deal_ym))
            .where(
                IngestLog.endpoint == endpoint,
                IngestLog.category == category,
                IngestLog.lawd_cd == lawd_cd,
            )
            .order_by(IngestLog.deal_ym)
        )
        return list(session.scalars(stmt))


# ─────────────────────────────────────────
#  통계
# ─────────────────────────────────────────

def store_stats() -> dict:
    init_store()
    try:
        from sqlalchemy import func as sa_func
        with session_scope() as session:
            tx_count  = session.scalar(select(sa_func.count()).select_from(Transaction))
            log_count = session.scalar(select(sa_func.count()).select_from(IngestLog))
            regions   = session.scalar(select(sa_func.count(distinct(IngestLog.lawd_cd))))
            ym_min, ym_max = session.execute(
                select(sa_func.min(IngestLog.deal_ym), sa_func.max(IngestLog.deal_ym))
            ).one()
        return {
            "transactions":   tx_count,
            "ingested_keys":  log_count,
            "regions":        regions,
            "month_range":    f"{ym_min} ~ {ym_max}" if ym_min else "—",
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    init_store()
    print("실거래가 스토어 현황:")
    for k, v in store_stats().items():
        print(f"  {k}: {v}")
