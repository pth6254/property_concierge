"""공식 법령 파일을 임베딩해 법령 전용 pgvector 테이블에 재개 가능하게 적재한다."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert

from db.base import session_scope
from db.models import LawCorpusDocument, LawCorpusChunk
from backend.tools.collect_property_laws import ROOT, as_list, clean_text

MODEL = "qwen3-embedding:4b"
DIMENSIONS = 2560
PIPELINE = "law-v1-1000chars-no-overlap"


def hash_id(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def split_text(text: str, size=1000):
    # 겹침 없이 원문을 전부 보존한다. 문단 경계가 가까우면 문단 끝에서 나눈다.
    while text:
        end = min(size, len(text))
        boundary = text.rfind("\n", 0, end)
        if end < len(text) and boundary >= size // 2:
            end = boundary + 1
        yield text[:end]
        text = text[end:]


def prepare_chunks(law: dict) -> list[dict]:
    sections = []
    for article in law["articles"]:
        if article["is_article"] != "조문":
            continue
        # 미래 시행 조문은 현행 검색 대상에 섞지 않는다. 원본 파일에는 그대로 남는다.
        effective = article.get("effective_date") or law["effective_date"]
        if effective > law["collected_at"][:10].replace("-", ""):
            continue
        label = f"제{article['number']}조" + (f"의{article['branch_number']}" if article["branch_number"] else "")
        sections.append(("article", label, article["title"], effective, article["text"]))
    for i, unit in enumerate(as_list((law.get("supplementary") or {}).get("부칙단위"))):
        text = clean_text(unit.get("부칙내용"))
        if text:
            sections.append(("supplementary", str(i), "부칙", law["effective_date"], text))
    for i, unit in enumerate(as_list((law.get("annexes") or {}).get("별표단위"))):
        text = clean_text(unit.get("별표내용"))
        if text:
            sections.append(("annex", str(i), clean_text(unit.get("별표제목")), law["effective_date"], text))
    chunks = []
    for kind, number, title, effective, text in sections:
        for part, piece in enumerate(split_text(text)):
            header = f"{law['law_name']} {number} {title}"
            chunks.append({"text": header + "\n" + piece, "metadata_json": {
                "kind": kind, "number": number, "title": title, "part": part,
                "effective_date": effective, "source_url": law["source_url"],
            }})
    return chunks


def validate_vectors(vectors, count):
    if len(vectors) != count:
        raise ValueError("임베딩 개수 불일치")
    for vector in vectors:
        if len(vector) != DIMENSIONS or not all(isinstance(x, (float, int)) and math.isfinite(x) for x in vector):
            raise ValueError("임베딩 차원 또는 수치 오류")
        if not any(vector):
            raise ValueError("영벡터는 코사인 검색에 사용할 수 없음")


class Embedder:
    def __init__(self, host):
        self.host = host.rstrip("/")
        self.session = requests.Session()
        response = self.session.get(self.host + "/api/tags", timeout=15)
        response.raise_for_status()
        models = response.json()["models"]
        self.digest = next(item["digest"] for item in models if item["name"] == MODEL)

    def embed(self, texts):
        response = self.session.post(self.host + "/api/embed", json={
            "model": MODEL, "input": texts, "truncate": False, "keep_alive": "10m",
        }, timeout=(10, 180))
        response.raise_for_status()
        vectors = response.json()["embeddings"]
        validate_vectors(vectors, len(texts))
        return vectors


def ingest_law(law: dict, embedder, batch_size=16):
    chunks = prepare_chunks(law)
    if not chunks:
        raise ValueError("적재할 법령 본문 없음")
    document_id = hash_id([law["raw_sha256"], embedder.digest, PIPELINE])
    metadata = {key: value for key, value in law.items() if key not in {"articles", "supplementary", "annexes"}}
    metadata.update(pipeline=PIPELINE, dimensions=DIMENSIONS)
    with session_scope() as session:
        session.execute(insert(LawCorpusDocument).values(id=document_id, law_id=law["law_id"], model=MODEL,
            model_digest=embedder.digest, status="loading", active=False, chunk_count=len(chunks), metadata_json=metadata
        ).on_conflict_do_nothing(index_elements=["id"]))
        existing = set(session.scalars(select(LawCorpusChunk.id).where(LawCorpusChunk.document_id == document_id)))
    pending = [{**chunk, "id": hash_id([document_id, i, chunk]), "document_id": document_id} for i, chunk in enumerate(chunks)]
    pending = [chunk for chunk in pending if chunk["id"] not in existing]
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        vectors = embedder.embed([chunk["text"] for chunk in batch])
        validate_vectors(vectors, len(batch))
        with session_scope() as session:
            session.execute(insert(LawCorpusChunk).values([
                {**chunk, "embedding": vector} for chunk, vector in zip(batch, vectors)
            ]).on_conflict_do_nothing(index_elements=["id"]))
        print(f"  {law['law_name']}: {min(start + batch_size, len(pending))}/{len(pending)}", flush=True)
    with session_scope() as session:
        count = session.scalar(select(func.count()).select_from(LawCorpusChunk).where(LawCorpusChunk.document_id == document_id))
        if count != len(chunks):
            raise ValueError("법령별 적재 건수 불일치")
        # 새 버전 전체가 준비된 뒤에만 이전 버전을 검색 대상에서 제외한다.
        session.execute(update(LawCorpusDocument).where(LawCorpusDocument.law_id == law["law_id"],
            LawCorpusDocument.model == MODEL).values(active=False))
        session.execute(update(LawCorpusDocument).where(LawCorpusDocument.id == document_id).values(status="ready", active=True))
    return {"law_name": law["law_name"], "chunks": len(chunks), "embedded": len(pending), "document_id": document_id}


def search(query: str, embedder, k=5):
    # qwen 임베딩의 질의 지시문은 문서 임베딩에는 붙이지 않는다.
    vector = embedder.embed(["Instruct: Retrieve Korean legal provisions relevant to the question.\nQuery: " + query])[0]
    distance = LawCorpusChunk.embedding.cosine_distance(vector)
    with session_scope() as session:
        rows = session.execute(select(LawCorpusChunk.text, LawCorpusChunk.metadata_json, distance.label("distance"))
            .join(LawCorpusDocument).where(LawCorpusDocument.active.is_(True), LawCorpusDocument.status == "ready",
                LawCorpusDocument.model_digest == embedder.digest)
            .order_by(distance).limit(k)).all()
        return [{"text": row.text, "metadata": row.metadata_json, "distance": float(row.distance)} for row in rows]


def load_laws(root: Path, manifest: Path):
    records = json.loads(manifest.read_text(encoding="utf-8"))["results"]
    if not records or any(item["status"] != "collected" for item in records):
        raise ValueError("완전히 수집된 manifest가 필요합니다")
    for item in records:
        directory = (root / item["directory"]).resolve()
        if not directory.is_relative_to(root.resolve()):
            raise ValueError("원문 경로 오류")
        raw_hash = hashlib.sha256((directory / "raw.json").read_bytes()).hexdigest()
        law = json.loads((directory / "law.json").read_text(encoding="utf-8"))
        if raw_hash != item["raw_sha256"] or raw_hash != law["raw_sha256"]:
            raise ValueError("수집 원문 해시 불일치")
        yield law


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="수집 법령 임베딩 → pgvector 적재")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 64:
        parser.error("batch-size는 1~64")
    embedder = Embedder(os.environ["OLLAMA_HOST"])
    results = [ingest_law(law, embedder, args.batch_size) for law in load_laws(args.manifest.parent, args.manifest)]
    report = args.manifest.parent / "embedding_report.json"
    report.write_text(json.dumps({"model": MODEL, "model_digest": embedder.digest, "dimensions": DIMENSIONS,
        "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"완료: {len(results)}개 법령 / {sum(row['chunks'] for row in results)}개 청크", flush=True)


if __name__ == "__main__":
    main()
