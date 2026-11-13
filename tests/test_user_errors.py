"""작업 실패 문구: 내부 표시는 기능별 안내로 바꾸고, 사용자가 이해할 수 있는 한국어 안내는 그대로 둔다."""
import pytest

from api.user_errors import GENERIC, user_error


@pytest.mark.parametrize("raw", [
    "deep_analysis: intent 없음", "geocoding_node: intent 없음", "리포트 생성 오류: KeyError('price')",
    "query 타입 오류: NoneType", "PropertyQuery가 전달되지 않았습니다.", "국토부 API 키가 설정되지 않았습니다", "", None,
])
def test_internal_messages_become_guidance(raw):
    assert user_error("appraisal", raw) == GENERIC["appraisal"]
    assert user_error("candidate_appraisal", raw) == GENERIC["appraisal"]


@pytest.mark.parametrize("raw", [
    "'강남구' 최근 6개월 아파트 실거래 없음", "텍스트를 추출할 수 없습니다 (스캔 이미지 PDF 분석 불가).",
    "예산 50,000~90,000만원에 맞는 단지 없음",
])
def test_user_facing_korean_messages_are_kept(raw):
    assert user_error("appraisal", raw) == raw


def test_unknown_task_gets_generic_message():
    assert "다시 시도" in user_error("probe", "Traceback (most recent call last)")
