"""
cache_db.py — API 응답 캐시 · 지역코드 룩업 · 임베딩 캐시 (PostgreSQL, SQLAlchemy)

이전에는 SQLite 파일(./cache.db)이었다. db/base.py 의 공용 세션으로 옮기되,
호출부(geocoding.py, price_engine.py, reb_index.py 등 다수)가 기대하는
함수 시그니처는 그대로 유지한다.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.base import init_db, session_scope
from db.models import ApiCache, EmbedCache, LegalRegion, RegionCode

DEFAULT_TTL = 60 * 60 * 24   # 24시간 (초)

_INITIALIZED = False   # 모듈 레벨 초기화 플래그 (지역코드 시드 중복 삽입 방지)


# ─────────────────────────────────────────
#  1. DB 초기화 + 기본 지역코드 시드
# ─────────────────────────────────────────

_SEED_REGIONS = [
    # 서울
    ("강남구",    "11680", "서울특별시", "강남구"),
    ("서초구",    "11650", "서울특별시", "서초구"),
    ("송파구",    "11710", "서울특별시", "송파구"),
    ("강동구",    "11740", "서울특별시", "강동구"),
    ("마포구",    "11440", "서울특별시", "마포구"),
    ("용산구",    "11170", "서울특별시", "용산구"),
    ("성동구",    "11200", "서울특별시", "성동구"),
    ("광진구",    "11215", "서울특별시", "광진구"),
    ("영등포구",  "11560", "서울특별시", "영등포구"),
    ("강서구",    "11500", "서울특별시", "강서구"),
    ("노원구",    "11350", "서울특별시", "노원구"),
    ("은평구",    "11380", "서울특별시", "은평구"),
    ("서대문구",  "11410", "서울특별시", "서대문구"),
    ("종로구",    "11110", "서울특별시", "종로구"),
    ("중구",      "11140", "서울특별시", "중구"),
    ("동작구",    "11590", "서울특별시", "동작구"),
    ("관악구",    "11620", "서울특별시", "관악구"),
    ("강북구",    "11305", "서울특별시", "강북구"),
    ("도봉구",    "11320", "서울특별시", "도봉구"),
    ("중랑구",    "11260", "서울특별시", "중랑구"),
    ("동대문구",  "11230", "서울특별시", "동대문구"),
    ("성북구",    "11290", "서울특별시", "성북구"),
    ("양천구",    "11470", "서울특별시", "양천구"),
    ("구로구",    "11530", "서울특별시", "구로구"),
    ("금천구",    "11545", "서울특별시", "금천구"),
    # 경기
    ("수원시",    "41110", "경기도",     "수원시"),
    ("성남시",    "41130", "경기도",     "성남시"),
    ("고양시",    "41280", "경기도",     "고양시"),
    ("용인시",    "41460", "경기도",     "용인시"),
    ("부천시",    "41190", "경기도",     "부천시"),
    ("안양시",    "41170", "경기도",     "안양시"),
    ("화성시",    "41590", "경기도",     "화성시"),
    ("평택시",    "41220", "경기도",     "평택시"),
    ("시흥시",    "41390", "경기도",     "시흥시"),
    ("김포시",    "41570", "경기도",     "김포시"),
    ("하남시",    "41450", "경기도",     "하남시"),
    ("양평군",    "41830", "경기도",     "양평군"),
    ("과천시",    "41290", "경기도",     "과천시"),
    ("안성시",    "41550", "경기도",     "안성시"),
    ("오산시",    "41370", "경기도",     "오산시"),
    ("의왕시",    "41430", "경기도",     "의왕시"),
    ("군포시",    "41410", "경기도",     "군포시"),
    ("광명시",    "41210", "경기도",     "광명시"),
    ("광주시",    "41610", "경기도",     "광주시"),
    ("남양주시",  "41360", "경기도",     "남양주시"),
    ("구리시",    "41310", "경기도",     "구리시"),
    ("의정부시",  "41150", "경기도",     "의정부시"),
    ("파주시",    "41480", "경기도",     "파주시"),
    # 인천
    ("남동구",    "28200", "인천광역시", "남동구"),
    ("연수구",    "28185", "인천광역시", "연수구"),
    ("서구",      "28260", "인천광역시", "서구"),
    ("부평구",    "28237", "인천광역시", "부평구"),
    ("미추홀구",  "28177", "인천광역시", "미추홀구"),
    ("계양구",    "28245", "인천광역시", "계양구"),
    # 부산
    ("해운대구",  "26350", "부산광역시", "해운대구"),
    ("부산진구",  "26230", "부산광역시", "부산진구"),
    ("동래구",    "26260", "부산광역시", "동래구"),
    ("남구",      "26290", "부산광역시", "남구"),
    ("사상구",    "26530", "부산광역시", "사상구"),
    ("강서구",    "26440", "부산광역시", "강서구"),
    # 대구·대전·광주·울산
    ("수성구",    "27290", "대구광역시", "수성구"),
    ("달서구",    "27290", "대구광역시", "달서구"),
    ("유성구",    "30230", "대전광역시", "유성구"),
    ("서구",      "29140", "광주광역시", "서구"),
    ("울주군",    "31710", "울산광역시", "울주군"),
]


def init_cache_db():
    """캐시 테이블 초기화 및 기본 지역코드 삽입 (중복 호출 안전)"""
    global _INITIALIZED
    if _INITIALIZED:
        return
    init_db()
    with session_scope() as session:
        for region_name, lawd_code, sido, sigungu in _SEED_REGIONS:
            stmt = pg_insert(RegionCode).values(
                region_name=region_name, lawd_code=lawd_code, sido=sido, sigungu=sigungu,
            ).on_conflict_do_nothing(index_elements=["region_name"])
            session.execute(stmt)
    _INITIALIZED = True
    print("[cache_db] 초기화 완료 (PostgreSQL)")


# ─────────────────────────────────────────
#  2. API 응답 캐시
# ─────────────────────────────────────────

def _make_cache_key(namespace: str, **params) -> str:
    payload = json.dumps(params, sort_keys=True, ensure_ascii=False)
    h = hashlib.md5(payload.encode()).hexdigest()[:12]
    return f"{namespace}:{h}"


def cache_get(namespace: str, **params) -> Optional[Any]:
    """캐시 조회. 만료 시 자동 삭제 후 None 반환."""
    key = _make_cache_key(namespace, **params)
    try:
        with session_scope() as session:
            row = session.get(ApiCache, key)
            if not row:
                return None
            if time.time() - row.created_at > row.ttl:
                session.delete(row)
                return None
            row.hit_count += 1
            print(f"[cache] HIT: {key}")
            return row.response
    except Exception as e:
        print(f"[cache] 조회 오류: {e}")
        return None


def cache_set(value: Any, ttl: float = DEFAULT_TTL, namespace: str = "", **params):
    """캐시 저장."""
    key = _make_cache_key(namespace, **params)
    try:
        with session_scope() as session:
            stmt = pg_insert(ApiCache).values(
                cache_key=key, response=value, created_at=time.time(), ttl=ttl, hit_count=0,
            ).on_conflict_do_update(
                index_elements=["cache_key"],
                set_={"response": value, "created_at": time.time(), "ttl": ttl},
            )
            session.execute(stmt)
    except Exception as e:
        print(f"[cache] 저장 오류: {e}")


def cached_api_call(func, namespace: str, ttl: float = DEFAULT_TTL, **params) -> Any:
    """
    API 함수를 캐시로 감싸는 범용 래퍼.

    매개변수명 `func`는 호출부(deep_analysis.py 등)가 키워드 인자로 넘기므로
    하위 호환을 위해 유지한다 — sqlalchemy.func(모듈 상단 임포트)를 이 함수
    본문에서는 쓰지 않으므로 지역 변수 그림자(shadowing)는 안전하다.
    """
    cached = cache_get(namespace, **params)
    if cached is not None:
        return cached
    print(f"[cache] MISS: {namespace} {params}")
    result = func(**params)
    if result:
        cache_set(result, ttl=ttl, namespace=namespace, **params)
    return result


# ─────────────────────────────────────────
#  3. 지역코드 룩업
# ─────────────────────────────────────────

def get_lawd_code(region_name: str) -> str:
    """행정구역명 → 국토부 법정동코드 5자리. 부분 매칭 지원."""
    init_cache_db()
    try:
        with session_scope() as session:
            # 신규 탐색 화면은 동명이 있는 시군구를 구분할 수 있도록 법정동 계층의
            # 전체 이름을 우선 사용한다. 기존 region_codes는 과거 호출 경로 호환용이다.
            legal = session.scalar(
                select(LegalRegion).where(
                    LegalRegion.is_active.is_(True),
                    LegalRegion.level == "sigungu",
                    LegalRegion.full_name == region_name,
                )
            )
            if legal and legal.lawd_code:
                return legal.lawd_code
            row = session.get(RegionCode, region_name)
            if row:
                return row.lawd_code
            row = session.scalar(
                select(RegionCode).where(RegionCode.region_name.ilike(f"%{region_name}%"))
            )
            return row.lawd_code if row else ""
    except Exception as e:
        print(f"[cache_db] 지역코드 조회 오류: {e}")
        return ""


def list_region_codes() -> list[dict]:
    """등록된 전체 지역코드 목록. [{region_name, lawd_code, sido, sigungu}, ...]"""
    init_cache_db()
    try:
        with session_scope() as session:
            rows = session.scalars(select(RegionCode).order_by(RegionCode.lawd_code))
            return [
                {"region_name": r.region_name, "lawd_code": r.lawd_code,
                 "sido": r.sido, "sigungu": r.sigungu}
                for r in rows
            ]
    except Exception as e:
        print(f"[cache_db] 지역코드 목록 조회 오류: {e}")
        return []


def add_region_code(region_name: str, lawd_code: str, sido: str = "", sigungu: str = "",
                    overwrite: bool = True):
    """
    지역코드 추가.
    overwrite=False: 동명이구(예: 서울 중구 vs 부산 중구)가 기존 등록을
    덮어쓰지 않도록 이미 있는 지역명은 유지 (지오코딩 자동 등록용).
    """
    init_cache_db()
    try:
        with session_scope() as session:
            stmt = pg_insert(RegionCode).values(
                region_name=region_name, lawd_code=lawd_code, sido=sido, sigungu=sigungu,
            )
            if overwrite:
                stmt = stmt.on_conflict_do_update(
                    index_elements=["region_name"],
                    set_={"lawd_code": lawd_code, "sido": sido, "sigungu": sigungu},
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=["region_name"])
            session.execute(stmt)
    except Exception as e:
        print(f"[cache_db] 지역코드 추가 오류: {e}")


# ─────────────────────────────────────────
#  4. 임베딩 캐시
# ─────────────────────────────────────────

def embed_cache_get(text: str) -> Optional[list[float]]:
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    try:
        with session_scope() as session:
            row = session.get(EmbedCache, text_hash)
            return row.vector_json if row else None
    except Exception as e:
        print(f"[cache_db] 임베딩 조회 오류: {e}")
        return None


def embed_cache_set(text: str, vector: list[float]):
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    try:
        with session_scope() as session:
            stmt = pg_insert(EmbedCache).values(
                text_hash=text_hash, text_preview=text[:100],
                vector_json=vector, created_at=time.time(),
            ).on_conflict_do_update(
                index_elements=["text_hash"],
                set_={"text_preview": text[:100], "vector_json": vector, "created_at": time.time()},
            )
            session.execute(stmt)
    except Exception as e:
        print(f"[cache_db] 임베딩 저장 오류: {e}")


# ─────────────────────────────────────────
#  5. 캐시 통계
# ─────────────────────────────────────────

def cache_stats() -> dict:
    try:
        with session_scope() as session:
            api_count    = session.scalar(select(func.count()).select_from(ApiCache))
            total_hits   = session.scalar(select(func.coalesce(func.sum(ApiCache.hit_count), 0)))
            region_count = session.scalar(select(func.count()).select_from(RegionCode))
            embed_count  = session.scalar(select(func.count()).select_from(EmbedCache))
        return {
            "api_cache_entries": api_count,
            "total_cache_hits":  total_hits,
            "region_codes":      region_count,
            "embed_cache":       embed_count,
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    init_cache_db()
    stats = cache_stats()
    print("\n캐시 DB 현황:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
