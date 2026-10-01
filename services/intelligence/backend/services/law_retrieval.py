"""준비된 공식 법령 벡터에서 시행 중인 본문 조문을 검색한다."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, func
from db.base import session_scope
from db.models import LawCorpusDocument, LawCorpusChunk
from backend.tools.embed_property_laws import Embedder


def retrieve_chat_evidence(question: str, k=4, trace=None):
    """서비스와 평가기가 동일한 공식 법령 우선 검색 경로를 사용한다."""
    chunks = search_laws(question, k=k, trace=trace)
    if chunks is None:
        from backend import chat_corpus
        return chat_corpus.search(question, k=k, trace=trace)
    return chunks


def search_laws(question: str, k=4, trace=None):
    with session_scope() as session:
        count = session.scalar(select(func.count()).select_from(LawCorpusDocument).where(
            LawCorpusDocument.active.is_(True), LawCorpusDocument.status == "ready"))
    if not count:
        return None  # 아직 적재하지 않은 개발·평가 환경의 기존 요약 코퍼스 경로.
    embedder = Embedder(os.environ["OLLAMA_HOST"])
    vector = embedder.embed(["Instruct: Retrieve Korean legal provisions relevant to the question.\nQuery: " + question])[0]
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    distance = LawCorpusChunk.embedding.cosine_distance(vector)
    with session_scope() as session:
        rows = session.execute(select(LawCorpusChunk, LawCorpusDocument, distance.label("distance"))
            .join(LawCorpusDocument).where(LawCorpusDocument.active.is_(True), LawCorpusDocument.status == "ready",
                LawCorpusDocument.model_digest == embedder.digest,
                LawCorpusChunk.metadata_json["kind"].as_string() == "article",
                LawCorpusChunk.metadata_json["effective_date"].as_string() <= today)
            .order_by(distance).limit(k * 4)).all()
        chunks, seen = [], set()
        for chunk, document, score in rows:
            if score > 0.4:
                continue
            meta = chunk.metadata_json
            key = (document.id, meta["number"])
            if key in seen:
                continue
            seen.add(key)
            # 예외 조항이 잘려 답변 의미가 달라지지 않도록 같은 조의 분할 본문을 합친다.
            parts = session.scalars(select(LawCorpusChunk).where(LawCorpusChunk.document_id == document.id,
                LawCorpusChunk.metadata_json["kind"].as_string() == "article",
                LawCorpusChunk.metadata_json["number"].as_string() == meta["number"])
                .order_by(LawCorpusChunk.metadata_json["part"].as_integer())).all()
            text = "".join(part.text.split("\n", 1)[1] for part in parts)
            if len(text) + sum(len(item["text"]) for item in chunks) > 12000:
                continue
            chunks.append({"title": chunk.text.split("\n", 1)[0], "source": "국가법령정보센터",
                "text": text, "score": 1 - float(score), "url": meta["source_url"],
                "effective_date": meta["effective_date"], "collected_at": document.metadata_json["collected_at"],
                "law_id": document.law_id, "article": meta["number"], "origin": "official_law"})
            if len(chunks) == k:
                break
    if trace is not None:
        trace.update(mode="pgvector_law", document_count=count, model_digest=embedder.digest, returned=len(chunks))
    return chunks
