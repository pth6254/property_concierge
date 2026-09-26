"""현재 OpenRouter 모델의 JSON 응답을 확인한다. 키와 응답 원문은 출력하지 않는다."""
from __future__ import annotations

import json
import sys

from backend.model_factory import get_chat_llm


def main() -> int:
    try:
        response = get_chat_llm(json_mode=True).invoke([
            ("system", "반드시 JSON 객체만 응답하세요."),
            ("human", '다음 객체를 그대로 반환하세요: {"ok": true}'),
        ])
        parsed = json.loads(response.content)
        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            print("OpenRouter JSON 응답 검증 실패")
            return 1
    except Exception as exc:
        # 예외 본문에 요청 정보가 포함될 수 있어 종류만 기록한다.
        status = getattr(exc, "status_code", None)
        suffix = f" (HTTP {status})" if isinstance(status, int) else ""
        print(f"OpenRouter 호출 실패: {type(exc).__name__}{suffix}")
        return 1
    print("OpenRouter JSON 응답 검증 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
