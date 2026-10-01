"""
build_law_corpus.py — 국가법령정보센터 법령·판례 수집 → 챗봇 RAG 코퍼스 확장

시드 코퍼스(chat_corpus.SEED_CHUNKS)만으로도 챗봇은 동작하지만,
이 도구로 법령 조문·판례를 추가 수집하면 답변 근거가 풍부해진다.

준비:
  국가법령정보 공동활용(open.law.go.kr) 회원가입 → OC(이메일 ID) 발급 (무료)
  .env에 LAW_OC_KEY=<이메일ID> 추가

사용:
  python backend/tools/build_law_corpus.py --laws "주택임대차보호법,공인중개사법"
  python backend/tools/build_law_corpus.py --prec "전세보증금 반환" --limit 20
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import requests
from dotenv import find_dotenv, load_dotenv

_TOOLS_DIR    = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR  = os.path.dirname(_TOOLS_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for _p in [_BACKEND_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

load_dotenv(find_dotenv())

import chat_corpus

OC = os.getenv("LAW_OC_KEY", "")
BASE = "http://www.law.go.kr/DRF"

CHUNK_CHARS = 800   # 조문 청크 최대 길이


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def fetch_law_articles(law_name: str) -> list[dict]:
    """법령명 → 조문 청크 목록."""
    # 1) 법령 검색 → 법령ID
    res = requests.get(f"{BASE}/lawSearch.do", params={
        "OC": OC, "target": "law", "type": "JSON", "query": law_name, "display": 5,
    }, timeout=15)
    res.raise_for_status()
    laws = (res.json().get("LawSearch") or {}).get("law") or []
    if isinstance(laws, dict):
        laws = [laws]
    match = next((l for l in laws if l.get("법령명한글", "").replace(" ", "") == law_name.replace(" ", "")), None)
    if not match:
        print(f"  ⚠️ '{law_name}' 검색 실패")
        return []

    # 2) 본문 조회
    res = requests.get(f"{BASE}/lawService.do", params={
        "OC": OC, "target": "law", "type": "JSON", "ID": match["법령ID"],
    }, timeout=30)
    res.raise_for_status()
    body = res.json().get("법령") or {}
    articles = (body.get("조문") or {}).get("조문단위") or []
    if isinstance(articles, dict):
        articles = [articles]

    chunks = []
    for art in articles:
        content = _strip_tags(str(art.get("조문내용", "")))
        # 항 내용 병합
        hangs = art.get("항") or []
        if isinstance(hangs, dict):
            hangs = [hangs]
        for h in hangs:
            content += " " + _strip_tags(str(h.get("항내용", "")))
        content = content.strip()
        if len(content) < 30:
            continue
        title = f"{law_name} {art.get('조문번호', '')}조 {_strip_tags(str(art.get('조문제목', '')))}".strip()
        chunks.append({"title": title, "source": law_name, "text": content[:CHUNK_CHARS]})
    return chunks


def fetch_precedents(query: str, limit: int = 20) -> list[dict]:
    """판례 검색 → 판시사항·판결요지 청크."""
    res = requests.get(f"{BASE}/lawSearch.do", params={
        "OC": OC, "target": "prec", "type": "JSON", "query": query, "display": limit,
    }, timeout=15)
    res.raise_for_status()
    precs = (res.json().get("PrecSearch") or {}).get("prec") or []
    if isinstance(precs, dict):
        precs = [precs]

    chunks = []
    for p in precs:
        try:
            res2 = requests.get(f"{BASE}/lawService.do", params={
                "OC": OC, "target": "prec", "type": "JSON", "ID": p["판례일련번호"],
            }, timeout=15)
            body = res2.json().get("PrecService") or {}
            summary = _strip_tags(str(body.get("판시사항", ""))) + " " + _strip_tags(str(body.get("판결요지", "")))
            summary = summary.strip()
            if len(summary) < 50:
                continue
            chunks.append({
                "title": f"판례 {p.get('사건번호', '')} — {_strip_tags(str(p.get('사건명', '')))[:40]}",
                "source": f"대법원 판례 ({p.get('선고일자', '')})",
                "text": summary[:CHUNK_CHARS],
            })
        except Exception as e:
            print(f"  ⚠️ 판례 상세 실패: {e}")
    return chunks


def main():
    parser = argparse.ArgumentParser(description="법령·판례 수집 → 챗봇 코퍼스")
    parser.add_argument("--laws", default="", help="쉼표 구분 법령명")
    parser.add_argument("--prec", default="", help="판례 검색어")
    parser.add_argument("--limit", type=int, default=20, help="판례 최대 건수")
    args = parser.parse_args()

    if not OC:
        sys.exit("❌ LAW_OC_KEY 미설정 — open.law.go.kr 가입 후 .env에 이메일 ID 추가")
    if not args.laws and not args.prec:
        sys.exit("--laws 또는 --prec 필요")

    chat_corpus.ensure_corpus()
    total = 0
    for law in [l.strip() for l in args.laws.split(",") if l.strip()]:
        chunks = fetch_law_articles(law)
        if chunks:
            chat_corpus.add_chunks(chunks)
            print(f"  {law}: {len(chunks)}개 조문 청크 추가")
            total += len(chunks)
    if args.prec:
        chunks = fetch_precedents(args.prec, args.limit)
        if chunks:
            chat_corpus.add_chunks(chunks)
            print(f"  판례 '{args.prec}': {len(chunks)}건 추가")
            total += len(chunks)

    print(f"\n✅ 총 {total}청크 추가 — 챗봇이 즉시 사용합니다")


if __name__ == "__main__":
    main()
