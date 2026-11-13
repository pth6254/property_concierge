"""작업 실패 문구를 사용자에게 보여도 되는 문장으로 바꾼다.

분석 그래프는 실패 이유를 `result["error"]`에 담는데, 일부는 노드 이름·예외 원문이다("deep_analysis: intent 없음",
"리포트 생성 오류: KeyError ..."). 이를 그대로 보이면 사용자는 무엇을 해야 할지 모르고 내부 구조가 드러난다.
사용자가 이해할 수 있는 한국어 안내(예: "'강남구' 최근 6개월 아파트 실거래 없음")는 그대로 두고,
내부 표시가 섞인 문구만 기능별 안내로 바꾼다. 원문은 운영자가 보도록 오류 로그(Sentry 연결 시 오류 보고)에 남긴다.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 영문 단어(4자 이상)·밑줄 식별자·예외 표시가 있으면 내부 문구로 본다. PDF·API·AVM 같은 짧은 약어는 허용한다.
_INTERNAL = re.compile(r"[A-Za-z]{4,}|_|Traceback|오류: |타입 오류|API 키")

GENERIC = {
    "appraisal": "시세추정을 완료하지 못했습니다. 주소·단지명·면적을 확인하고 다시 시도해주세요. 계속되면 화면 아래 의견 보내기로 알려주세요.",
    "chat": "답변을 만들지 못했습니다. 잠시 후 다시 질문해주세요.",
    "concierge": "요청을 처리하지 못했습니다. 잠시 후 다시 요청해주세요.",
    "listing_collection": "매물 원문을 불러오지 못했습니다. 링크를 확인하거나 직접 입력으로 등록해주세요.",
}
DEFAULT = "작업을 완료하지 못했습니다. 잠시 후 다시 시도해주세요."


def user_error(task_type: str, raw, job_id: str = "") -> str:
    text = " ".join(str(raw or "").split())
    if text and not _INTERNAL.search(text):
        return text
    logger.error("작업 실패(내부 문구를 안내로 바꿈): task=%s job=%s detail=%s", task_type, job_id, text[:500])
    key = "appraisal" if task_type == "candidate_appraisal" else task_type
    return GENERIC.get(key, DEFAULT)
