"""법률·세금 상담 기록을 사용자별 Redis 키에 한시적으로 보관한다."""
import json
from uuid import UUID, uuid4

from db.redis_client import get_redis

TTL_SECONDS = 24 * 60 * 60


def conversation_key(user_id: int, conversation_id: str) -> str:
    return f"law-chat:{user_id}:{str(UUID(conversation_id))}"


def load_conversation(user_id: int, conversation_id: str) -> dict:
    raw = get_redis().get(conversation_key(user_id, conversation_id))
    if not raw:
        raise LookupError("conversation_not_found")
    return json.loads(raw)


def delete_user_conversations(user_id: int) -> None:
    redis = get_redis()
    # 회원 탈퇴 시 해당 사용자의 임시 대화만 제거한다. ID 뒤 구분자로 다른 계정을 보호한다.
    for key in redis.scan_iter(match=f"law-chat:{int(user_id)}:*", count=100):
        redis.delete(key)


def answer_in_conversation(user_id: int, question: str, conversation_id: str | None) -> dict:
    from backend.services.chat_service import answer_question
    if conversation_id:
        previous = load_conversation(user_id, conversation_id)
    else:
        conversation_id = str(uuid4())
        previous = {"messages": []}
    # 표시용 기록과 추론 길이를 분리해 과거 답변이 무한히 입력에 누적되지 않게 한다.
    history = [{"role": m["role"], "content": m["content"]} for m in previous["messages"][-6:]]
    result = answer_question(question, history)
    result["conversation_id"] = conversation_id
    messages = (previous["messages"] + [{"role": "user", "content": question},
        {"role": "assistant", "content": result["answer"], "sources": result.get("sources", []),
         "tool": result.get("tool_used"), "disclaimer": result.get("disclaimer")}])[-40:]
    get_redis().set(conversation_key(user_id, conversation_id), json.dumps(
        {"conversation_id": conversation_id, "messages": messages}, ensure_ascii=False), ex=TTL_SECONDS)
    return result
