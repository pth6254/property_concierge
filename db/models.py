"""
db/models.py — SQLAlchemy ORM 모델

기존 6개 SQLite 모듈의 테이블을 그대로 옮겼다 (컬럼 이름·의미 동일).
JSON 컬럼(result/meta/response/vector_json/embedding)은 이전에는 텍스트로
저장해 각 모듈이 직접 json.dumps/loads 했지만, Postgres의 JSON 타입을 써서
그 왕복 변환을 SQLAlchemy에 맡긴다.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, JSON, BigInteger, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from db.base import Base


class ComplexCatalog(Base):
    """추천 표기와 검증된 단지 주소의 지속적인 대응 관계."""
    __tablename__ = "complex_catalog"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lawd_code: Mapped[str] = mapped_column(String(5), nullable=False)
    dong: Mapped[str] = mapped_column(String(50), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    region: Mapped[str] = mapped_column(String(150), nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    address: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unresolved")
    checked_at: Mapped[float] = mapped_column(Float, nullable=False)
    __table_args__ = (Index("uq_complex_catalog_identity", "lawd_code", "dong", "canonical_name", unique=True),)


class LawCorpusDocument(Base):
    __tablename__ = "law_corpus_documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    law_id: Mapped[str] = mapped_column(String(30), index=True)
    model: Mapped[str] = mapped_column(String(100))
    model_digest: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="loading")
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    chunk_count: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON)


class LawCorpusChunk(Base):
    __tablename__ = "law_corpus_chunks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("law_corpus_documents.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    # qwen3-embedding:4b의 실측 차원. 기존 실거래 벡터(768차원)와 혼합하지 않는다.
    embedding: Mapped[list] = mapped_column(Vector(2560))


def _now_str() -> str:
    """
    'created' 컬럼 기본값.

    이전 SQLite 스키마는 `datetime('now','localtime')` 로 서버 로컬시각 문자열을
    저장했고, 프론트(page.tsx/dashboard/page.tsx)는 그 문자열을 그대로
    slice(0,10)/slice(0,16) 해서 날짜만 잘라 쓴다. Postgres의 서버 시각(UTC 기준
    TIMESTAMP)으로 바꾸면 표시 시각이 그만큼 밀리므로, 동일한 포맷의 문자열을
    애플리케이션(파이썬) 레벨에서 그대로 생성해 하위 호환을 유지한다.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────
#  인증 (구 api/auth_db.py)
# ─────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    name: Mapped[str] = mapped_column(String(100), default="")
    avatar_url: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(20), default="local")
    provider_id: Mapped[str | None] = mapped_column(String(255), default=None)
    created: Mapped[str] = mapped_column(String(32), default=_now_str)

    # 비밀번호를 마지막으로 변경한 시각. JWT 는 stateless 라 서버가 발급된 토큰을
    # 직접 폐기할 수 없으므로, 발급 시각 대신 이 값을 토큰에 함께 넣고 검증 때
    # 대조한다 — 비밀번호가 바뀌면 값이 달라져 기존 세션이 전부 무효가 된다
    # (계정 탈취 후 비밀번호를 바꿔도 공격자 세션이 살아있는 문제를 막는다).
    #
    # NULL = 가입 이후 한 번도 변경한 적 없음. 이 경우 pwd_at 클레임이 없는
    # 기존 토큰도 그대로 통과시킨다 (컬럼 추가 이전 발급분 호환).
    password_changed_at: Mapped[str | None] = mapped_column(String(32), default=None)


# ─────────────────────────────────────────
#  시세추정 이력 (구 api/history_db.py)
# ─────────────────────────────────────────

class HistoryRecord(Base):
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str | None] = mapped_column(String(32), unique=True, default=None)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="")
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created: Mapped[str] = mapped_column(String(32), default=_now_str, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), default=None, index=True
    )


# ─────────────────────────────────────────
#  권리점검·상담 활동 피드 (구 api/activity_db.py)
# ─────────────────────────────────────────

class ActivityRecord(Base):
    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[str] = mapped_column(String(32), default=_now_str, index=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), default=None, index=True
    )


class PurchaseCase(Base):
    """한 사용자의 매수 의사결정을 묶는 최상위 작업 단위."""

    __tablename__ = "purchase_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="exploring", nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(20), default="purchase", nullable=False)
    budget_min: Mapped[int | None] = mapped_column(BigInteger, default=None)
    budget_max: Mapped[int | None] = mapped_column(BigInteger, default=None)
    buyer_profile: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    target_regions: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    selected_property_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("case_properties.id", ondelete="SET NULL"), default=None, index=True
    )
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[str | None] = mapped_column(String(32), default=None)
    created: Mapped[str] = mapped_column(String(32), default=_now_str, index=True)
    updated: Mapped[str] = mapped_column(String(32), default=_now_str)


class CaseProperty(Base):
    """매수 검토 케이스 안에서 평가하는 후보 부동산."""

    __tablename__ = "case_properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    address: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(30), default="")
    asking_price: Mapped[int | None] = mapped_column(BigInteger, default=None)
    area_sqm: Mapped[float | None] = mapped_column(Float, default=None)
    legal_region_code: Mapped[str | None] = mapped_column(String(10), default=None, index=True)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="reviewing", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    history_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("history.id", ondelete="SET NULL"), default=None, index=True
    )
    source_listing_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("imported_listings.id", ondelete="SET NULL"), default=None, index=True
    )
    source_snapshot: Mapped[dict | None] = mapped_column(JSON, default=None)
    created: Mapped[str] = mapped_column(String(32), default=_now_str)
    updated: Mapped[str] = mapped_column(String(32), default=_now_str)

    __table_args__ = (
        Index("idx_case_properties_case_status", "case_id", "status"),
    )


class CandidateSourceReview(Base):
    """원본 매물 갱신 당시의 후보·선택 근거를 남겨 이후 판단의 출처를 보존한다."""
    __tablename__ = "candidate_source_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[int] = mapped_column(Integer, ForeignKey("case_properties.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    previous_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    applied_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_decision: Mapped[dict | None] = mapped_column(JSON, default=None)
    invalidated_analyses: Mapped[list] = mapped_column(JSON, default=list)
    previous_analyses: Mapped[list] = mapped_column(JSON, default=list)
    previous_execution: Mapped[list] = mapped_column(JSON, default=list)
    created: Mapped[str] = mapped_column(String(32), default=_now_str)


class CandidateAnalysis(Base):
    """후보 매물에 연결된 기능별 최신 분석 결과."""

    __tablename__ = "candidate_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[int] = mapped_column(Integer, ForeignKey("case_properties.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_id: Mapped[int | None] = mapped_column(Integer, default=None)
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    analyzed_at: Mapped[str | None] = mapped_column(String(32), default=None)
    expires_at: Mapped[str | None] = mapped_column(String(32), default=None)
    created: Mapped[str] = mapped_column(String(32), default=_now_str)
    updated: Mapped[str] = mapped_column(String(32), default=_now_str)

    __table_args__ = (Index("uq_candidate_analysis_type", "property_id", "analysis_type", unique=True),)


class CandidateChecklistItem(Base):
    """후보별 의사결정 누락을 막는 검토 항목."""

    __tablename__ = "candidate_checklist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[int] = mapped_column(Integer, ForeignKey("case_properties.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="todo", nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="system", nullable=False)
    evidence: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[str | None] = mapped_column(String(32), default=None)
    created: Mapped[str] = mapped_column(String(32), default=_now_str)
    updated: Mapped[str] = mapped_column(String(32), default=_now_str)

    __table_args__ = (Index("uq_candidate_checklist_item", "property_id", "category", "title", unique=True),)


class CaseExecutionPlan(Base):
    """최종 후보 선택 이후의 계약·잔금 준비 계획."""

    __tablename__ = "case_execution_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_cases.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    property_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("case_properties.id", ondelete="SET NULL"), default=None, index=True)
    contract_planned_date: Mapped[str | None] = mapped_column(String(10), default=None)
    closing_planned_date: Mapped[str | None] = mapped_column(String(10), default=None)
    status: Mapped[str] = mapped_column(String(20), default="preparing", nullable=False)
    created: Mapped[str] = mapped_column(String(32), default=_now_str)
    updated: Mapped[str] = mapped_column(String(32), default=_now_str)


class CaseExecutionTask(Base):
    """외부 수행 여부와 확인 근거를 기록하는 거래 준비 항목."""

    __tablename__ = "case_execution_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("case_execution_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("case_properties.id", ondelete="SET NULL"), default=None, index=True)
    template_key: Mapped[str | None] = mapped_column(String(80), default=None)
    phase: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    actor_type: Mapped[str] = mapped_column(String(30), default="self", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="scheduled", nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    due_date: Mapped[str | None] = mapped_column(String(10), default=None, index=True)
    completed_at: Mapped[str | None] = mapped_column(String(32), default=None)
    checked_by: Mapped[str] = mapped_column(String(150), default="")
    outcome: Mapped[str] = mapped_column(Text, default="")
    evidence_note: Mapped[str] = mapped_column(Text, default="")
    follow_up: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="system", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[str] = mapped_column(String(32), default=_now_str)
    updated: Mapped[str] = mapped_column(String(32), default=_now_str)

    __table_args__ = (Index("uq_case_execution_task_template", "plan_id", "template_key", unique=True),)


class CaseRegion(Base):
    """매수 검토 케이스에 저장한 관심 지역과 저장 당시 판단 근거."""

    __tablename__ = "case_regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    region_code: Mapped[str] = mapped_column(
        String(10), ForeignKey("legal_regions.code", ondelete="RESTRICT"), nullable=False, index=True
    )
    region_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="market_explorer", nullable=False)
    property_type: Mapped[str] = mapped_column(String(30), default="all", nullable=False)
    budget_max_won: Mapped[int | None] = mapped_column(BigInteger, default=None)
    period_from: Mapped[str | None] = mapped_column(String(6), default=None)
    period_to: Mapped[str | None] = mapped_column(String(6), default=None)
    stats_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created: Mapped[str] = mapped_column(String(32), default=_now_str)

    __table_args__ = (
        Index("uq_case_regions_case_region", "case_id", "region_code", unique=True),
    )


# ─────────────────────────────────────────
#  API 응답 캐시 · 지역코드 · 임베딩 캐시 (구 backend/cache_db.py)
# ─────────────────────────────────────────

class ApiCache(Base):
    __tablename__ = "api_cache"

    cache_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    ttl: Mapped[float] = mapped_column(Float, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)


class RegionCode(Base):
    __tablename__ = "region_codes"

    region_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    lawd_code: Mapped[str] = mapped_column(String(10), nullable=False)
    sido: Mapped[str] = mapped_column(String(30), default="")
    sigungu: Mapped[str] = mapped_column(String(30), default="")


class LegalRegion(Base):
    """행정안전부 10자리 법정동코드의 전국 계층 마스터.

    기존 ``region_codes``는 이름을 기본키로 사용해 서울 중구·부산 중구 같은
    동명이구를 함께 저장할 수 없다. 현재 시세추정 경로의 하위 호환 때문에 그
    테이블은 유지하고, 동네 탐색은 코드가 기본키인 이 테이블을 사용한다.
    """

    __tablename__ = "legal_regions"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    parent_code: Mapped[str | None] = mapped_column(String(10), default=None, index=True)
    sido_code: Mapped[str] = mapped_column(String(2), nullable=False)
    sigungu_code: Mapped[str] = mapped_column(String(3), nullable=False)
    eup_myeon_dong_code: Mapped[str] = mapped_column(String(3), nullable=False)
    ri_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    # 국토부 실거래 조회·건축물대장 시군구 식별에 쓰는 앞 5자리. 시도 노드는 NULL.
    lawd_code: Mapped[str | None] = mapped_column(String(5), default=None, index=True)
    resident_code: Mapped[str] = mapped_column(String(10), default="")
    cadastral_code: Mapped[str] = mapped_column(String(10), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    remarks: Mapped[str] = mapped_column(Text, default="")
    effective_date: Mapped[str | None] = mapped_column(String(8), default=None)
    # 목록 API는 공식 폐지일을 주지 않는다. 별도 변경이력 연계 전에는 추정값을 넣지 않는다.
    abolished_date: Mapped[str | None] = mapped_column(String(8), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    synced_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("idx_legal_regions_parent_active", "parent_code", "is_active"),
    )


class EmbedCache(Base):
    __tablename__ = "embed_cache"

    text_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    text_preview: Mapped[str] = mapped_column(Text, default="")
    vector_json: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


# ─────────────────────────────────────────
#  실거래가 로컬 스토어 (구 backend/transaction_store.py)
# ─────────────────────────────────────────

class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    lawd_cd: Mapped[str] = mapped_column(String(10), nullable=False)
    deal_ym: Mapped[str] = mapped_column(String(6), nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    area_sqm: Mapped[float | None] = mapped_column(Float, default=None)
    area_pyeong: Mapped[float | None] = mapped_column(Float, default=None)
    per_sqm: Mapped[int | None] = mapped_column(BigInteger, default=None)
    floor: Mapped[str | None] = mapped_column(String(20), default=None)
    year_built: Mapped[str | None] = mapped_column(String(10), default=None)
    dong: Mapped[str | None] = mapped_column(String(50), default=None)
    apt_name: Mapped[str | None] = mapped_column(String(100), default=None)
    deal_year: Mapped[str | None] = mapped_column(String(10), default=None)
    deal_month: Mapped[str | None] = mapped_column(String(10), default=None)
    deal_day: Mapped[str | None] = mapped_column(String(10), default=None)
    bjdong_code: Mapped[str | None] = mapped_column(String(10), default=None, index=True)
    property_detail: Mapped[str | None] = mapped_column(String(30), default=None)
    building_area_sqm: Mapped[float | None] = mapped_column(Float, default=None)
    land_area_sqm: Mapped[float | None] = mapped_column(Float, default=None)
    building_use: Mapped[str | None] = mapped_column(String(100), default=None)
    jimok: Mapped[str | None] = mapped_column(String(50), default=None)
    transaction_type: Mapped[str | None] = mapped_column(String(30), default=None)
    cancellation_date: Mapped[str | None] = mapped_column(String(8), default=None)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("idx_tx_key", "endpoint", "category", "lawd_cd", "deal_ym"),
        Index("idx_tx_apt", "lawd_cd", "apt_name"),
    )


class IngestLog(Base):
    __tablename__ = "ingest_log"

    endpoint: Mapped[str] = mapped_column(String(50), primary_key=True)
    category: Mapped[str] = mapped_column(String(20), primary_key=True)
    lawd_cd: Mapped[str] = mapped_column(String(10), primary_key=True)
    deal_ym: Mapped[str] = mapped_column(String(6), primary_key=True)
    fetched_at: Mapped[float] = mapped_column(Float, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False, index=True)
    started_at: Mapped[float | None] = mapped_column(Float, default=None)
    completed_at: Mapped[float | None] = mapped_column(Float, default=None)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)


# ─────────────────────────────────────────
#  법률·세금 상담 RAG 코퍼스 (구 backend/chat_corpus.py)
# ─────────────────────────────────────────

class ChatChunk(Base):
    __tablename__ = "chat_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(JSON, default=None)


class ImportedListing(Base):
    """업로드한 사용자의 매물. 실거래·샘플 매물과 섞지 않는다."""
    __tablename__ = "imported_listings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    legal_region_code: Mapped[str | None] = mapped_column(String(10))
    property_type: Mapped[str] = mapped_column(String(30), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    area_sqm: Mapped[float] = mapped_column(Float, nullable=False)
    confirmed_at: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        Index("uq_imported_listing_source", "user_id", "source_name", "external_id", unique=True),
        Index("ix_imported_listing_search", "user_id", "legal_region_code", "status"),
    )


class ListingRevision(Base):
    __tablename__ = "listing_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("imported_listings.id", ondelete="CASCADE"), nullable=False, index=True)
    imported_at: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class ListingObservation(Base):
    """실패도 남겨 마지막 성공과 마지막 시도를 구별하는 불변 수집 기록."""
    __tablename__ = "listing_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(32), unique=True, default=None)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_at: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[float] = mapped_column(Float, nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    __table_args__ = (Index("ix_listing_observation_owner", "user_id", "external_id", "fetched_at"),)
