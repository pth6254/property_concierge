"""정답 집합과 반환 순위로 계산하는 검색 지표. LLM 채점은 사용하지 않는다."""
import math


def retrieval_metrics(retrieved: list[str], relevant: list[str], k: int) -> dict:
    if k < 1:
        raise ValueError("k는 1 이상이어야 합니다")
    gold = set(relevant)
    top = retrieved[:k]
    seen = set()
    gains = []
    for title in top:
        gains.append(int(title in gold and title not in seen))
        seen.add(title)
    hits = sum(gains)
    dcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains))
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(k, len(gold))))
    return {
        "precision_at_k": hits / k,
        "recall_at_k": hits / len(gold) if gold else None,
        "mrr_at_k": next((1 / (rank + 1) for rank, gain in enumerate(gains) if gain), 0),
        "ndcg_at_k": dcg / ideal if ideal else None,
        "retrieved_count": len(top), "relevant_count": len(gold),
    }
