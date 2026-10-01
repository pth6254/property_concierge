"""브라우저 인증은 Spring만 수행한다. AI는 인증된 내부 호출의 행위자만 받는다."""
from fastapi import Depends, Header, HTTPException
from api.internal_contracts import require_service

def get_optional_user(x_ai_user_id: str | None = Header(default=None), _=Depends(require_service)):
    if x_ai_user_id is None:
        return None
    try:
        value = int(x_ai_user_id)
        if value <= 0 or value > 2**63-1:
            raise ValueError
        return {"id": value}
    except ValueError:
        raise HTTPException(422, "내부 분석 행위자가 올바르지 않습니다") from None

def get_current_user(user=Depends(get_optional_user)):
    if user is None:
        raise HTTPException(401, "로그인이 필요한 분석입니다")
    return user
