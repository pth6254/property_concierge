-- docker/init.sql
-- PostgreSQL 컨테이너 최초 기동 시 자동 실행됩니다.
-- rag_pipeline.py 의 INIT_SQL 과 완전히 동일한 스키마입니다.

-- pgvector 익스텐션 활성화
CREATE EXTENSION IF NOT EXISTS vector;

-- 실거래가 문서 벡터 테이블
CREATE TABLE IF NOT EXISTS real_estate_docs (
    id           SERIAL PRIMARY KEY,
    content      TEXT         NOT NULL,
    embedding    vector(768),              -- nomic-embed-text 차원 (768)
    category     VARCHAR(20),
    region       VARCHAR(100),
    price        INTEGER,                  -- 만원 단위
    area         FLOAT,                    -- ㎡
    floor        INTEGER,
    year_built   INTEGER,
    special_tags TEXT[],                   -- 추출된 특수조건 태그
    source       VARCHAR(50),              -- molit | manual | tavily
    deal_date    VARCHAR(10),
    created_at   TIMESTAMP DEFAULT NOW()
);

-- IVFFlat 인덱스 (코사인 유사도 기반 ANN 검색)
CREATE INDEX IF NOT EXISTS real_estate_docs_embedding_idx
    ON real_estate_docs
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- LangChain PGVector 컬렉션 테이블 (langchain_community 내부 사용)
-- 직접 사용하지 않아도 PGVector 클래스가 자동 생성하지만
-- 미리 만들어두면 첫 연결 지연 없음
CREATE TABLE IF NOT EXISTS langchain_pg_collection (
    name       VARCHAR     NOT NULL,
    cmetadata  JSON,
    uuid       UUID PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS langchain_pg_embedding (
    collection_id UUID REFERENCES langchain_pg_collection(uuid) ON DELETE CASCADE,
    embedding     vector(768),
    document      VARCHAR,
    cmetadata     JSON,
    custom_id     VARCHAR,
    uuid          UUID PRIMARY KEY
);
