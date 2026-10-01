"""
DeepAgent 부동산 가치 감정평가 — 심층 분석: RAG 파이프라인
pgvector + Ollama 임베딩 + 비정형 조건 재순위화

역할:
  - 실거래가 API가 반환한 거래 Document를 pgvector에 저장
  - 사용자의 special_conditions를 벡터화해 유사 매물 검색
  - Ollama로 조건 충족도를 재순위화

의존:
  pip install psycopg2-binary pgvector langchain-community
  PostgreSQL + pgvector 익스텐션 필요
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

import psycopg2
from langchain_core.documents import Document
from langchain_community.vectorstores import PGVector
from model_factory import get_llm, get_llm_json, get_embeddings

from dotenv import load_dotenv, find_dotenv

# 자동으로 상위 디렉토리를 탐색하며 .env를 찾아 로드합니다.
load_dotenv(find_dotenv())
PG_CONN_STR = os.getenv(
    "PG_CONNECTION_STRING",
    "postgresql://postgres:password@localhost:5432/real_estate_db",
)


# ─────────────────────────────────────────
#  1. pgvector 커넥션 & 테이블 초기화
# ─────────────────────────────────────────

INIT_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS real_estate_docs (
    id          SERIAL PRIMARY KEY,
    content     TEXT        NOT NULL,
    embedding   vector(1024),          -- mxbai-embed-text 차원
    category    VARCHAR(20),
    region      VARCHAR(100),
    price       INTEGER,              -- 만원 단위
    area        FLOAT,                -- ㎡
    floor       INTEGER,
    year_built  INTEGER,
    special_tags TEXT[],              -- 추출된 특수조건 태그
    source      VARCHAR(50),          -- molit | manual | tavily
    deal_date   VARCHAR(10),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS real_estate_docs_embedding_idx
    ON real_estate_docs USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
"""


def init_db():
    """pgvector 테이블 초기화"""
    try:
        conn = psycopg2.connect(PG_CONN_STR)
        with conn.cursor() as cur:
            cur.execute(INIT_SQL)
        conn.commit()
        conn.close()
        print("[pgvector] DB 초기화 완료")
    except Exception as e:
        print(f"[pgvector] DB 초기화 실패: {e}")
        print("  → PostgreSQL이 실행 중인지 확인하세요")
        print("  → docker run -e POSTGRES_PASSWORD=password -p 5432:5432 ankane/pgvector")


# ─────────────────────────────────────────
#  2. 실거래가 데이터 → Document 변환
# ─────────────────────────────────────────

# 비정형 표현 → 정형 태그 매핑 테이블
CONDITION_TAG_MAP = {
    # 주거용
    "조용":       ["저소음", "주거환경_양호"],
    "역세권":     ["지하철_도보5분"],
    "초품아":     ["초등학교_인접"],
    "남향":       ["남향"],
    "신축":       ["5년_이내"],
    "올수리":     ["풀리모델링"],
    "주차":       ["주차_가능"],
    # 상업용
    "1층":        ["1층", "가시성_우수"],
    "코너":       ["코너자리", "양면노출"],
    "권리금":     ["권리금_협의"],
    "유동인구":   ["유동인구_풍부"],
    # 산업용
    "트럭":       ["대형차량_진입"],
    "층고":       ["고층고"],
    "3상":        ["산업용_전력"],
    "냉동":       ["냉동창고"],
    "냉장":       ["냉장창고"],
    # 토지
    "전원주택":   ["전원주택_가능"],
    "맹지":       ["맹지_아님_요구"],
    "개발":       ["개발호재"],
}


def extract_tags(text: str) -> list[str]:
    """텍스트에서 특수조건 태그 추출"""
    tags = []
    for keyword, tag_list in CONDITION_TAG_MAP.items():
        if keyword in text:
            tags.extend(tag_list)
    return list(set(tags))


def transaction_to_document(
    transaction: dict,
    category: str,
    region: str,
) -> Document:
    """
    국토부 실거래가 API 응답 1건 → LangChain Document 변환.
    content는 RAG 검색 대상 텍스트, metadata는 필터링용.
    """
    price     = transaction.get("price", 0)
    area_raw  = transaction.get("area_sqm") or transaction.get("area", 0)
    try:
        area = float(str(area_raw).replace("(", "").replace(")", "").replace(",", "").strip() or 0)
    except ValueError:
        area = 0.0
    floor = str(transaction.get("floor", "")).strip()
    year_built = str(transaction.get("year_built", "")).strip()
    place_name = transaction.get("apt_name", "")
    sub_region = transaction.get("dong", "")

    # 거래 데이터의 실제 법정동(dong)으로 주소 구성
    # MOLIT API는 시군구 단위로 조회하므로 서초구 전체 거래가 섞여 들어옴
    # → 각 거래의 실제 dong을 써야 "서울 서초구 서초동"처럼 정확한 주소가 됨
    if sub_region:
        region_prefix = region.rsplit(" ", 1)[0] if " " in region else region
        actual_address = f"{region_prefix} {sub_region}"
    else:
        actual_address = region
    address = transaction.get("address", actual_address)

    # RAG 검색에 활용할 자연어 설명 생성
    # → 이 텍스트가 임베딩되어 벡터 DB에 저장됨
    content_parts = [
        f"위치: {address}",
        f"유형: {category}",
        f"가격: {price:,}만원",
        f"면적: {area}㎡",
    ]

    if place_name:
        content_parts.insert(1, f"장소명: {place_name}")

    if floor:
        content_parts.append(f"층수: {floor}층")
        # 저층(1~3층) / 중층 / 고층 태그 추가
        try:
            floor_int = int(str(floor).replace("층", ""))
            if floor_int <= 3:
                content_parts.append("저층 (1~3층)")
            elif floor_int <= 10:
                content_parts.append("중층")
            else:
                content_parts.append("고층 (11층 이상)")
        except ValueError:
            pass

    if year_built:
        try:
            age = 2025 - int(year_built)
            if age <= 5:
                content_parts.append("신축 (5년 이내)")
            elif age <= 15:
                content_parts.append("준신축")
            else:
                content_parts.append(f"구축 ({age}년)")
        except ValueError:
            pass

    content = " | ".join(content_parts)
    tags = extract_tags(content)

    return Document(
        page_content=content,
        metadata={
            "category":   category,
            "region":     actual_address,
            "price":      price,
            "area":       area,
            "floor":      str(floor),
            "year_built": int(year_built) if year_built else 0,
            "place_name": place_name,
            "sub_region":    sub_region,       
            "special_tags": tags,
            "source":     "molit",
            "deal_date":  transaction.get("deal_date", ""),
        },
    )


def build_documents_from_transactions(
    transactions: list[dict],
    category: str,
    region: str,
) -> list[Document]:
    """실거래가 목록 전체를 Document 리스트로 변환"""
    docs = []
    for t in transactions:
        try:
            docs.append(transaction_to_document(t, category, region))
        except Exception as e:
            print(f"[doc_convert] 변환 실패: {e} | {t}")
    return docs


# ─────────────────────────────────────────
#  3. pgvector 저장 & 검색
# ─────────────────────────────────────────

def get_vectorstore(collection_name: str = "real_estate") -> PGVector:
    """PGVector 인스턴스 반환 (LangChain 래퍼)"""
    embeddings = get_embeddings()
    return PGVector(
        connection_string=PG_CONN_STR,
        collection_name=collection_name,
        embedding_function=embeddings,
    )


def _drop_collection(collection: str):
    """pgvector 컬렉션 삭제 — 임베딩 모델 교체로 차원 불일치 시 재생성용"""
    try:
        conn = psycopg2.connect(PG_CONN_STR)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM langchain_pg_embedding WHERE collection_id IN "
                "(SELECT uuid FROM langchain_pg_collection WHERE name = %s)",
                (collection,),
            )
            cur.execute(
                "DELETE FROM langchain_pg_collection WHERE name = %s",
                (collection,),
            )
        conn.commit()
        conn.close()
        print(f"[vectorstore] 컬렉션 '{collection}' 삭제 완료 → 재생성 예정")
    except Exception as e:
        print(f"[vectorstore] 컬렉션 삭제 실패: {e}")


def upsert_documents(docs: list[Document], collection: str = "real_estate"):
    """Document 리스트를 pgvector에 임베딩하여 저장"""
    if not docs:
        print("[vectorstore] 저장할 문서 없음")
        return

    print(f"[vectorstore] {len(docs)}건 임베딩 중...")
    try:
        vs = get_vectorstore(collection)
        vs.add_documents(docs)
        print(f"[vectorstore] 저장 완료")
    except Exception as e:
        if "dimensions" in str(e):
            # 임베딩 모델 교체로 차원 불일치 — 컬렉션 재생성 후 1회 재시도
            print(f"[vectorstore] 차원 불일치 감지 → 컬렉션 재생성 후 재시도")
            _drop_collection(collection)
            try:
                vs = get_vectorstore(collection)
                vs.add_documents(docs)
                print(f"[vectorstore] 재생성 후 저장 완료")
            except Exception as e2:
                print(f"[vectorstore] 재생성 후에도 저장 실패: {e2}")
        else:
            print(f"[vectorstore] 저장 실패: {e}")


def search_similar(
    query: str,
    category: str,
    k: int = 10,
    price_max: Optional[int] = None,
    price_min: Optional[int] = None,
    area_min: Optional[float] = None,
    area_max: Optional[float] = None,
    region: str = "",              # ← 추가
    collection: str = "real_estate",
) -> list[Document]:
    """
    쿼리 텍스트와 유사한 매물 Document 검색.
    같은 지역 매물을 우선 검색 후 부족하면 전체에서 보완.
    """
    try:
        vs = get_vectorstore(collection)

        # 메타데이터 필터 구성
        filters = {"category": category}
        if price_max:
            filters["price"] = {"$lte": price_max}
        if area_min:
            filters["area"] = {"$gte": area_min}

        if area_min and area_max:
            filters["area"] = {"$gte": area_min, "$lte": area_max}
        elif area_min:
            filters["area"] = {"$gte": area_min}
        elif area_max:
            filters["area"] = {"$lte": area_max}

        # ── 1단계: 같은 지역 우선 검색 ──
        if region:
            region_filters = {**filters, "region": region}
            region_results = vs.similarity_search_with_score(
                query, k=k, filter=region_filters,
            )
            print(f"[vectorstore] 지역({region}) 필터 → {len(region_results)}건")
        else:
            region_results = []

        # ── 2단계: 지역 결과가 부족하면 전체에서 보완 ──
        if len(region_results) < k:
            all_results = vs.similarity_search_with_score(
                query, k=k, filter=filters,
            )
            # 중복 제거 후 합치기
            existing = {doc.page_content for doc, _ in region_results}
            extra = [(doc, score) for doc, score in all_results
                     if doc.page_content not in existing]
            combined = region_results + extra
        else:
            combined = region_results

        print(f"[vectorstore] '{query[:30]}...' → {len(combined)}건 검색")
        return combined[:k]

    except Exception as e:
        print(f"[vectorstore] 검색 실패: {e}")
        return []


# ─────────────────────────────────────────
#  4. 비정형 조건 쿼리 생성
# ─────────────────────────────────────────

QUERY_EXPAND_PROMPT = """다음 부동산 요구사항을 RAG 검색에 최적화된 한국어 문장으로 변환하세요.
원래 조건의 의미를 유지하면서 검색에 유리한 표현으로 확장하세요.
반드시 한 문장으로만 답하세요.

요구사항: {conditions}
위치: {location}
유형: {category}"""


def build_rag_query(
    special_conditions: list[str],
    location: str,
    category: str,
    transaction_type: str,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
) -> str:
    # 예산 텍스트 생성
    if price_min and price_max:
        price_text = f"예산 {price_min:,}만원 ~ {price_max:,}만원"
    elif price_max:
        price_text = f"예산 {price_max:,}만원 이하"
    elif price_min:
        price_text = f"예산 {price_min:,}만원 이상"
    else:
        price_text = ""

    if not special_conditions:
        base = f"{location} {category} {transaction_type} 적합한 매물"
        return f"{base} {price_text}".strip()
    """
    special_conditions → RAG 검색 최적화 쿼리 생성.
    Ollama가 조건을 자연어로 확장해 검색 정확도를 높임.
    """
    if not special_conditions:
        # 특수조건 없으면 기본 쿼리
        return f"{location} {category} {transaction_type} 적합한 매물"

    conditions_text = ", ".join(special_conditions)

    llm = get_llm()
    prompt = QUERY_EXPAND_PROMPT.format(
        conditions=conditions_text,
        location=location,
        category=category,
    )

    try:
        response = llm.invoke([("human", prompt)])
        expanded = response.content.strip()
        # 한 문장만 추출
        expanded = expanded.split("\n")[0].strip()
        print(f"[rag_query] 원본: {conditions_text}")
        print(f"[rag_query] 확장: {expanded}")
        return f"{expanded} {price_text}".strip()
    except Exception as e:
        print(f"[rag_query] LLM 확장 실패: {e}")
        return f"{location} {conditions_text} {price_text}".strip()


# ─────────────────────────────────────────
#  5. LLM 재순위화 (Reranking)
# ─────────────────────────────────────────

# ─────────────────────────────────────────
#  유형별 재순위화 프롬프트
# ─────────────────────────────────────────

RERANK_PROMPT = {
    "주거용": """
## 평가 기준 (주거용)
- 위치 일치 여부 (40점): 같은 구/동이면 높은 점수
- 가격대 일치 (20점): 요구 가격 범위 내이면 높은 점수
- 면적 유사도 (20점): 요구 면적과 가까울수록 높은 점수
- 층수/신축/향 조건 (20점): 고층/신축/남향 조건 충족 시 높은 점수""",

    "상업용": """
## 평가 기준 (상업용)
- 위치 일치 여부 (30점): 같은 구/동이면 높은 점수
- 가격대 일치 (20점): 요구 가격 범위 내이면 높은 점수
- 1층 여부 (20점): 1층이면 높은 점수 (가시성, 접근성)
- 유동인구/코너 여부 (30점): 유동인구 많고 코너자리면 높은 점수""",

    "업무용": """
## 평가 기준 (업무용)
- 위치 일치 여부 (35점): 같은 구/동이면 높은 점수
- 가격대 일치 (20점): 요구 가격 범위 내이면 높은 점수
- 교통 접근성 (25점): 역세권, 주차 여부
- 층수/건물등급 (20점): 고층, 신축 여부""",

    "산업용": """
## 평가 기준 (산업용)
- 위치 일치 여부 (30점): 같은 구/동이면 높은 점수
- 가격대 일치 (20점): 요구 가격 범위 내이면 높은 점수
- 층고/트럭진입 (30점): 높은 층고, 대형차량 진입 가능 시 높은 점수
- 전력/냉동시설 (20점): 산업용 전력, 냉동·냉장 시설 여부""",

    "토지": """
## 평가 기준 (토지)
- 위치 일치 여부 (40점): 같은 시/군이면 높은 점수
- 가격대 일치 (20점): 요구 가격 범위 내이면 높은 점수
- 용도지역 일치 (20점): 요구 용도지역과 일치 시 높은 점수
- 개발호재 (20점): 개발 가능성, 도로 접함 여부""",
}

_RERANK_BASE = """당신은 부동산 입지 분석 전문가입니다.
사용자의 요구사항과 후보 매물 목록을 비교해 각 매물의 조건 충족 점수를 평가하세요.

## 사용자 요구사항
{requirements}

## 후보 매물 목록
{candidates}
{criteria}

## 절대 규칙 (반드시 적용)
- 가격 범위가 명시된 경우, 범위를 벗어난 매물은 총점 최대 20점만 부여하세요. 예외 없이 적용합니다.
- 면적 범위가 명시된 경우, 범위를 벗어난 매물은 총점 최대 20점만 부여하세요. 예외 없이 적용합니다.
- 가격·면적 모두 범위를 벗어난 매물은 총점 최대 10점만 부여하세요.
- 가격 범위 내, 면적 범위 내 매물은 각 항목 만점을 부여하세요.
- 특수조건 미충족 시 항목당 15점 감점을 적용하세요.
- 예산 초과 또는 면적 범위 이탈 매물은 선정하더라도 조건에 맞는 매물보다 하위에 있어야 합니다.
- 예산 초과 또는 면적 범위 이탈 매물이 여러 개 이상인 경우 그 중에서도 조건 범위와 이탈한 정도가 적은 순으로 배열해야 합니다.


반드시 아래 JSON 형식으로만 응답하세요:
{{
  "ranked": [
    {{"index": 0, "score": 85, "reason": "역세권 조건 충족, 가격 적정"}},
    {{"index": 1, "score": 60, "reason": "가격은 맞으나 층고 조건 미확인"}}
  ]
}}"""


def get_rerank_prompt(category: str) -> str:
    """카테고리별 재순위화 프롬프트 반환"""
    criteria = RERANK_PROMPT.get(category, RERANK_PROMPT["주거용"])
    return _RERANK_BASE.replace("{criteria}", criteria)


def rerank_with_llm(
    candidates: list[Document],
    intent_summary: str,
    special_conditions: list[str],
    top_k: int = 5,
    category: str = "주거용",
    price_min: Optional[int] = None, 
    price_max: Optional[int] = None,
    area_min: Optional[float] = None,
    area_max: Optional[float] = None,    
) -> list[tuple[Document, float, str]]:
    """
    LLM으로 후보 매물을 재순위화.
    반환: [(Document, score, reason), ...]  내림차순 정렬
    """
    if not candidates:
        return []

    # 후보 매물 텍스트 구성
    candidate_texts = []
    for i, (doc, sim_score) in enumerate(candidates):
        candidate_texts.append(
            f"[{i}] {doc.page_content} (유사도: {sim_score:.2f})"
        )

    llm = get_llm_json()
    rerank_prompt = get_rerank_prompt(category)

    if price_min and price_max:
        budget_text = f"예산 범위: {price_min:,}만원 ~ {price_max:,}만원 (범위 이탈 시 최대 30점)"
    elif price_max:
        budget_text = f"예산 상한: {price_max:,}만원 이하 (초과 시 최대 30점)"
    elif price_min:
        budget_text = f"예산 하한: {price_min:,}만원 이상 (미달 시 최대 30점)"
    else:
        budget_text = ""

    if area_min and area_max:
        area_text = f"면적 범위: {area_min:.0f}㎡ ~ {area_max:.0f}㎡ (범위 이탈 시 최대 20점)"
    elif area_max:
        area_text = f"면적 상한: {area_max:.0f}㎡ 이하 (초과 시 최대 20점)"
    elif area_min:
        area_text = f"면적 하한: {area_min:.0f}㎡ 이상 (미달 시 최대 20점)"
    else:
        area_text = ""

    prompt = rerank_prompt.format(
        requirements=f"{intent_summary}\n특수조건: {', '.join(special_conditions)}",
        candidates="\n".join(candidate_texts),
    )

    try:
        response = llm.invoke([("human", prompt)])
        raw = response.content.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("JSON 없음")

        data = json.loads(match.group())
        ranked = data.get("ranked", [])

        results = []
        for item in ranked[:top_k]:
            idx    = item.get("index", 0)
            score  = item.get("score", 0)
            reason = item.get("reason", "")
            if idx < len(candidates):
                doc, _ = candidates[idx]
                results.append((doc, float(score), reason))

        # 점수 내림차순 정렬
        results.sort(key=lambda x: x[1], reverse=True)
        print(f"[rerank] {len(results)}건 재순위화 완료")
        return results

    except Exception as e:
        print(f"[rerank] LLM 재순위화 실패: {e} — 유사도 점수 그대로 사용")
        # 폴백: 유사도 점수 그대로 반환
        return [
            (doc, float(score) * 100, "유사도 기반")
            for doc, score in candidates[:top_k]
        ]


# ─────────────────────────────────────────
#  6. 통합 RAG 파이프라인 진입점
# ─────────────────────────────────────────

def run_rag_pipeline(
    state: dict,
    price_data: dict,
) -> dict:
    """
    AgentState + 실거래가 데이터를 받아 RAG 분석 완료된 결과 반환.

    반환 키:
      rag_top_matches   : [(content, score, reason), ...]
      rag_query         : 사용된 검색 쿼리
      rag_match_count   : 검색된 총 후보 수
    """
    intent = state.get("intent")
    if not intent:
        return {**state, "rag_top_matches": [], "rag_query": "", "rag_match_count": 0}

    category    = intent.category
    location    = intent.location_normalized or intent.location_raw
    special     = intent.special_conditions or []
    trans_type  = intent.transaction_type
    price_min   = intent.price_min
    price_max   = intent.price_max
    area_min    = intent.area_min
    area_max    = intent.area_max


    # ── Step A: 실거래가 데이터 → Document → pgvector ──
    geo     = state.get("geocoding_result") or {}
    samples = price_data.get("samples", [])
    if samples:
        if isinstance(geo, dict):
            r1 = geo.get("region_1depth", "")
            r2 = geo.get("region_2depth", "")
            r3 = geo.get("region_3depth", "")
            region = " ".join(filter(None, [r1, r2, r3]))
        else:
            region = ""
        docs = build_documents_from_transactions(samples, category, region)
        upsert_documents(docs)
    else:
        print("[rag] 실거래 샘플 없음 — 기존 벡터DB만 검색")

    # ── Step B: 비정형 조건 쿼리 생성 ──
    rag_query = build_rag_query(special, location, category, trans_type, price_min=price_min, price_max=price_max)

    # ── Step C: 벡터 유사도 검색 ──
    candidates = search_similar(
        query=rag_query,
        category=category,
        k=15,
        price_min=price_min,
        price_max=price_max,
        area_min=area_min,
        area_max=area_max,
        region=geo.get("region_2depth", "") if isinstance(geo, dict) else "",
    )

    if not candidates:
        print("[rag] 검색 결과 없음")
        return {
            **state,
            "rag_top_matches": [],
            "rag_query": rag_query,
            "rag_match_count": 0,
        }

    # ── Step D: LLM 재순위화 ──
    from models import _intent_summary
    summary = _intent_summary(intent)
    ranked = rerank_with_llm(candidates, summary, special, top_k=5, category=category,  price_min=price_min, price_max=price_max, area_min=area_min, area_max=area_max, )

    top_matches = [
        {
            "content": doc.page_content,
            "metadata": doc.metadata,
            "rag_score": round(score, 1),
            "reason": reason,
        }
        for doc, score, reason in ranked
    ]

    print(f"\n[rag] 최종 Top-{len(top_matches)} 매물:")
    for i, m in enumerate(top_matches, 1):
        print(f"  {i}. 점수 {m['rag_score']} | {m['content'][:60]}")
        print(f"     이유: {m['reason']}")

    return {
        **state,
        "rag_top_matches": top_matches,
        "rag_query": rag_query,
        "rag_match_count": len(candidates),
    }
