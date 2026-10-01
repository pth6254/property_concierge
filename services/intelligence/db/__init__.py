"""
db/ — 공용 PostgreSQL 데이터 계층 (SQLAlchemy)

api/*_db.py, backend/cache_db.py, backend/transaction_store.py,
backend/chat_corpus.py 가 각자 열던 SQLite 파일을 이 패키지의
엔진 하나로 통합한다. RAG 벡터스토어(backend/rag_pipeline.py)가 쓰던
pgvector 컨테이너와 같은 PostgreSQL 인스턴스(real_estate_db)를 공유한다.
"""
