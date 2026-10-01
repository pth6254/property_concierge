"""
chat_corpus.py — 부동산 법률·세금 상담 챗봇 RAG 코퍼스 (PostgreSQL, SQLAlchemy)

구성:
  - 시드 코퍼스: 주택임대차보호법·전세사기 분쟁 유형·세금·상속증여 등
    핵심 지식 청크 (설치 즉시 동작)
  - 확장: tools/build_law_corpus.py 로 국가법령정보센터 법령·판례 추가 수집
  - 저장: chat_chunks 테이블 (PostgreSQL) — 청크 + 임베딩(JSON 배열)
  - 검색: 임베딩 코사인 유사도 (Ollama 등 model_factory 임베딩),
          임베딩 불가 환경에서는 키워드 매칭 폴백

법적 포지셔닝: 코퍼스는 "일반 정보"이며 개별 사안 판단(법률사무)이 아니다.

이전에는 SQLite 파일(data/chat_corpus.db)이었다. 실거래 벡터 검색용
pgvector(real_estate_docs, backend/rag_pipeline.py)와는 별개 테이블이다 —
법률 코퍼스 청크는 22건 수준으로 작고 코사인 유사도를 파이썬에서 계산해도
충분히 빨라, ivfflat 인덱스가 필요한 pgvector 전용 컬럼 타입까지는 쓰지 않았다.
"""

from __future__ import annotations

import math
import re

from sqlalchemy import func, select

from db.base import init_db, session_scope
from db.models import ChatChunk

_INITIALIZED = False


# ─────────────────────────────────────────
#  시드 코퍼스 (출처 표기 필수)
# ─────────────────────────────────────────

SEED_CHUNKS: list[dict] = [
    # ── 주택임대차보호법 ──
    {"title": "대항력 (주택임대차보호법 §3)", "source": "주택임대차보호법",
     "text": "임차인이 주택을 인도받고 전입신고(주민등록)를 마치면 그 다음 날 0시부터 대항력이 생긴다. "
             "대항력이 있으면 집주인이 바뀌어도 새 소유자에게 임차권을 주장할 수 있다. "
             "전입신고 전에 설정된 근저당보다는 후순위이므로, 계약 전 등기부의 선순위 권리 확인이 필수다."},
    {"title": "우선변제권과 확정일자 (주택임대차보호법 §3-2)", "source": "주택임대차보호법",
     "text": "대항력(인도+전입신고)에 더해 임대차계약서에 확정일자를 받으면, 경매·공매 시 "
             "확정일자 순위에 따라 후순위 권리자보다 먼저 보증금을 배당받을 수 있다. "
             "확정일자는 주민센터·등기소·인터넷(정부24)에서 받을 수 있으며, 전입신고와 같은 날 받는 것이 안전하다."},
    {"title": "소액임차인 최우선변제 (주택임대차보호법 §8)", "source": "주택임대차보호법 시행령",
     "text": "보증금이 일정 금액 이하인 소액임차인은 선순위 담보물권자보다도 먼저 일정액을 배당받는다. "
             "서울 기준 보증금 1억6,500만원 이하이면 5,500만원까지 최우선변제된다 (2023.2.21 이후 담보권 기준). "
             "단, 경매개시결정 등기 전에 대항력(인도+전입)을 갖춰야 하며, 낙찰가의 1/2 범위 내에서만 인정된다."},
    {"title": "계약갱신요구권 (주택임대차보호법 §6-3)", "source": "주택임대차보호법",
     "text": "임차인은 임대차 기간 만료 6개월~2개월 전 사이에 1회에 한해 계약갱신을 요구할 수 있고, "
             "갱신 시 2년이 보장된다. 임대인은 본인·직계존비속의 실거주 등 법정 사유가 있을 때만 거절할 수 있다. "
             "실거주 사유로 거절한 뒤 2년 내 제3자에게 임대하면 임차인은 손해배상을 청구할 수 있다."},
    {"title": "전월세 인상률 상한 (주택임대차보호법 §7)", "source": "주택임대차보호법",
     "text": "계약갱신 시 차임·보증금 증액은 기존 금액의 5%를 초과할 수 없다. "
             "지자체 조례로 더 낮게 정할 수 있다. 신규 계약에는 적용되지 않는다."},
    {"title": "묵시적 갱신 (주택임대차보호법 §6)", "source": "주택임대차보호법",
     "text": "임대인이 기간 만료 6개월~2개월 전까지 갱신 거절을 통지하지 않으면 이전과 같은 조건으로 "
             "자동 갱신(묵시적 갱신)되며 기간은 2년으로 본다. 묵시적 갱신 후 임차인은 언제든 해지를 통지할 수 있고 "
             "통지 3개월 후 효력이 생긴다 (임대인은 해지 불가)."},
    {"title": "임차권등기명령 (주택임대차보호법 §3-3)", "source": "주택임대차보호법",
     "text": "임대차가 끝났는데 보증금을 돌려받지 못한 경우, 법원에 임차권등기명령을 신청하면 "
             "이사를 가더라도 대항력과 우선변제권이 유지된다. 임차권등기가 된 집에 새로 들어가는 "
             "임차인은 최우선변제를 받지 못하므로, 등기부에 임차권등기가 보이면 위험 신호다."},

    # ── 전세사기·분쟁 사례 유형 ──
    {"title": "깡통전세 위험 판단 기준", "source": "분쟁사례 유형",
     "text": "선순위 근저당 채권최고액과 보증금의 합이 시세의 80%를 넘으면 깡통전세 위험이 크다. "
             "경매 낙찰가율(아파트 평균 약 80%)을 고려하면 배당 부족으로 보증금 일부를 잃을 수 있다. "
             "계약 전 등기부 을구의 채권최고액 합산, 시세 대비 전세가율 확인, 전세보증금 반환보증(HUG·HF·SGI) 가입이 예방책이다."},
    {"title": "신탁 부동산 전세사기 유형", "source": "분쟁사례 유형",
     "text": "등기부에 신탁등기가 있으면 소유권이 신탁회사에 있어, 위탁자(원소유자)와 체결한 임대차계약은 "
             "신탁사 동의가 없으면 무효가 될 수 있다. 이 경우 임차인은 대항력을 인정받지 못해 보증금을 "
             "전액 잃는 사례가 많다. 신탁원부를 발급받아 임대 권한 및 동의 여부를 반드시 확인해야 한다."},
    {"title": "이중계약·무권대리 사기 유형", "source": "분쟁사례 유형",
     "text": "집주인이 아닌 사람(중개보조원, 대리인)과 계약하거나 같은 집에 여러 임차인과 계약하는 사기 유형. "
             "등기부상 소유자와 계약 상대방의 신분증 대조, 대리 계약 시 인감증명서가 첨부된 위임장 확인, "
             "보증금은 반드시 소유자 명의 계좌로 이체하는 것이 예방책이다."},
    {"title": "보증금 반환 분쟁 대응 절차", "source": "분쟁사례 유형 (주택임대차분쟁조정위)",
     "text": "만기 후 보증금을 돌려받지 못하면: ① 내용증명으로 반환 최고 ② 임차권등기명령 신청(이사 대비) "
             "③ 주택임대차분쟁조정위원회 조정 신청(소송보다 빠르고 저렴, 60일 내 결정) ④ 지급명령 또는 "
             "보증금반환청구 소송 ⑤ 판결 후 강제집행(경매). 전세보증보험 가입자는 보증기관에 이행청구."},
    {"title": "수선의무·원상회복 분쟁", "source": "분쟁사례 유형 (민법 §623)",
     "text": "임대인은 목적물을 사용·수익에 필요한 상태로 유지할 의무(대수선, 보일러·누수 등 주요 설비)가 있고, "
             "임차인은 통상적 사용에 따른 마모(도배 변색 등)를 넘는 파손만 원상회복하면 된다. "
             "조정 사례에서는 소모품(형광등·건전지)은 임차인, 구조적 하자는 임대인 부담이 일반적 기준이다."},

    # ── 매매·계약 ──
    {"title": "계약금과 해약금 (민법 §565)", "source": "민법",
     "text": "계약금이 오간 매매계약은 당사자 일방이 이행에 착수하기 전까지, 매수인은 계약금을 포기하고 "
             "매도인은 계약금의 배액을 상환하고 해제할 수 있다. 중도금 지급 등 이행 착수 후에는 "
             "일방적 해제가 불가능하고 채무불이행 책임(통상 손해배상)이 문제된다."},
    {"title": "공인중개사의 손해배상 책임", "source": "공인중개사법 §30",
     "text": "중개사가 확인·설명 의무(권리관계, 등기부 확인 등)를 위반해 의뢰인에게 손해가 생기면 "
             "배상 책임을 진다. 중개사는 보증보험·공제(법인 4억, 개인 2억 이상)에 의무 가입되어 있어 "
             "중개사고 시 공제금 청구가 가능하다. 다만 임차인 본인의 확인 소홀은 과실상계될 수 있다."},

    # ── 세금 ──
    {"title": "양도소득세 1세대1주택 비과세 요건", "source": "소득세법 §89",
     "text": "1세대가 양도일 현재 국내 1주택을 2년 이상 보유(취득 당시 조정대상지역이면 2년 거주 포함)하고 "
             "양도가액이 12억원 이하이면 양도소득세가 비과세된다. 12억 초과 고가주택은 초과분에 대해서만 "
             "안분 과세되며, 장기보유특별공제(보유·거주 각 연 4%, 최대 80%)가 적용된다."},
    {"title": "취득세율 개요", "source": "지방세법 §11",
     "text": "주택 유상취득 취득세는 1주택 기준 6억 이하 1%, 6~9억 1~3% 구간, 9억 초과 3%다 (지방교육세 별도). "
             "조정대상지역 2주택 또는 비조정 3주택은 8%, 그 이상은 12% 중과가 적용될 수 있다. "
             "상가·오피스텔·토지 등 비주거용은 4%(농특세 등 포함 약 4.6%)다."},
    {"title": "보유세 개요 (재산세·종합부동산세)", "source": "지방세법·종부세법",
     "text": "재산세는 매년 6월 1일 기준 소유자에게 공시가격 × 공정시장가액비율(1주택 43~45%)로 과세된다. "
             "종합부동산세는 인별 주택 공시가격 합산이 9억원(1세대1주택 12억원)을 초과하는 부분에 과세된다. "
             "6월 1일 전후로 잔금일을 조정하면 그 해 보유세 부담자가 달라진다."},
    {"title": "증여세 공제와 세율", "source": "상속세 및 증여세법 §53, §26",
     "text": "증여재산공제는 10년 합산 기준 배우자 6억원, 직계존속→성인 자녀 5천만원(미성년 2천만원), "
             "기타친족 1천만원이다. 혼인·출산 시 직계존속 증여는 1억원 추가 공제된다. "
             "세율은 과세표준 1억 이하 10%부터 30억 초과 50%까지 5단계 누진이며, 신고 시 3% 세액공제가 있다."},
    {"title": "상속세 공제와 세율", "source": "상속세 및 증여세법 §21~24",
     "text": "상속세는 일괄공제 5억원(기초공제+인적공제 대신 선택)과 배우자상속공제(최소 5억, 실제 상속액 기준 "
             "최대 30억)가 대표적이다. 배우자가 있으면 통상 10억원까지는 상속세가 없다. "
             "세율은 증여세와 동일한 10~50% 누진이다. 사망일이 속한 달의 말일부터 6개월 내 신고해야 한다."},
    {"title": "부담부증여", "source": "상속세 및 증여세법 §47",
     "text": "전세보증금이나 대출을 낀 부동산을 증여하면(부담부증여), 채무 부분은 양도로 보아 증여자에게 "
             "양도소득세가, 나머지 부분만 수증자에게 증여세가 과세된다. 채무가 크고 양도차익이 작으면 "
             "단순 증여보다 유리할 수 있으나, 수증자의 채무 상환 능력을 국세청이 사후 관리한다."},

    # ── 재개발·기타 ──
    {"title": "재개발·재건축 조합원 지위 양도 제한", "source": "도시 및 주거환경정비법 §39",
     "text": "투기과열지구에서 재건축은 조합설립인가 후, 재개발은 관리처분계획인가 후 조합원 지위 양도가 "
             "원칙적으로 제한된다 (10년 보유·5년 거주 1주택자 등 예외 있음). 제한 기간에 매수하면 "
             "조합원 분양권을 받지 못하고 현금청산될 수 있으므로 매수 전 조합 단계 확인이 필수다."},
    {"title": "분양권 전매 제한", "source": "주택법 §64",
     "text": "수도권 분양가상한제 적용 주택 등은 당첨일부터 일정 기간(비규제 6개월~규제지역 3년) 전매가 제한된다. "
             "전매 제한 기간 중 이면 계약은 무효이며 형사처벌 대상이다. 분양권 양도소득세는 1년 미만 70%, "
             "1년 이상 60% 단일세율로 일반 주택보다 무겁다."},
]


# ─────────────────────────────────────────
#  저장소
# ─────────────────────────────────────────

def _init():
    global _INITIALIZED
    if _INITIALIZED:
        return
    init_db()
    _INITIALIZED = True


def _try_embed(texts: list[str]) -> list[list[float]] | None:
    """model_factory 임베딩 시도. 불가 환경(Ollama 미기동 등)이면 None."""
    try:
        from model_factory import get_embeddings
        return get_embeddings().embed_documents(texts)
    except Exception as e:
        print(f"[chat_corpus] 임베딩 불가 → 키워드 검색 폴백: {e}")
        return None


def add_chunks(chunks: list[dict]):
    """청크 추가 (임베딩 가능하면 함께 저장)."""
    _init()
    vecs = _try_embed([c["text"] for c in chunks])
    with session_scope() as session:
        session.add_all([
            ChatChunk(
                title=c["title"], source=c.get("source", ""), text=c["text"],
                embedding=vecs[i] if vecs else None,
            )
            for i, c in enumerate(chunks)
        ])


def ensure_corpus():
    """비어 있으면 시드 코퍼스 적재."""
    _init()
    with session_scope() as session:
        count = session.scalar(select(func.count()).select_from(ChatChunk))
    if count == 0:
        add_chunks(SEED_CHUNKS)
        print(f"[chat_corpus] 시드 코퍼스 {len(SEED_CHUNKS)}청크 적재")


# ─────────────────────────────────────────
#  검색
# ─────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _keyword_score(query: str, text: str) -> float:
    """임베딩 폴백: 2글자 이상 토큰 부분일치 점수."""
    tokens = [t for t in re.split(r"[\s,.?!·()]+", query) if len(t) >= 2]
    if not tokens:
        return 0.0
    return sum(text.count(t) for t in tokens) / len(tokens)


def search(query: str, k: int = 4, *, trace: dict | None = None) -> list[dict]:
    """관련 청크 상위 k개. [{title, source, text, score}]"""
    ensure_corpus()
    with session_scope() as session:
        rows = list(session.scalars(select(ChatChunk)))

    if not rows:
        if trace is not None:
            trace.update(mode="empty", corpus_count=0)
        return []

    q_vec = None
    if any(r.embedding for r in rows):
        vecs = _try_embed([query])
        q_vec = vecs[0] if vecs else None

    if trace is not None:
        import hashlib
        import json
        embedded_count = sum(bool(row.embedding) for row in rows)
        mode = "keyword" if q_vec is None else "embedding" if embedded_count == len(rows) else "mixed"
        trace.update(mode=mode, corpus_count=len(rows), embedded_count=embedded_count,
                     embedding_fallback=bool(embedded_count and q_vec is None),
                     corpus_sha256=hashlib.sha256(json.dumps(
                         [(r.id, r.title, r.source, r.text, r.embedding) for r in sorted(rows, key=lambda r: r.id)],
                         ensure_ascii=False, sort_keys=True).encode()).hexdigest())

    scored = []
    for r in rows:
        if q_vec is not None and r.embedding:
            score = _cosine(q_vec, r.embedding)
        else:
            score = _keyword_score(query, r.title + " " + r.text)
        scored.append({"title": r.title, "source": r.source, "text": r.text,
                       "score": round(score, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return [s for s in scored[:k] if s["score"] > 0]


if __name__ == "__main__":
    ensure_corpus()
    for c in search("전세 보증금 못 받으면 어떻게 하나요"):
        print(f"  [{c['score']}] {c['title']} ({c['source']})")
