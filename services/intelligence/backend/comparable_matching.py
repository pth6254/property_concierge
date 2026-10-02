"""비교사례 표시와 신뢰도가 동일한 확인 범위로 지역을 분류한다."""
import re


def normalized_name(value):
    return re.sub(r"\s+", "", value or "")


def comparable_match_level(sample, *, matched_complex="", target_dong="", target_sigungu_code=""):
    matched = matched_complex or sample.get("apt_name_matched") or ""
    dong = target_dong or sample.get("target_dong") or ""
    gu = target_sigungu_code or sample.get("target_sigungu_code") or ""
    observed_gu = (sample.get("bjdong_code") or sample.get("query_sigungu_code") or "")[:5]
    if gu and observed_gu and gu != observed_gu:
        return "nearby"
    same_dong = bool(dong and normalized_name(dong) == normalized_name(sample.get("dong")))
    # 단지 조회에 실제 성공한 이름만 사용한다. 구 폴백의 첫 단지를 대상 단지로 만들지 않는다.
    if matched and normalized_name(sample.get("apt_name")) == normalized_name(matched) and (not dong or same_dong):
        return "same_complex"
    if same_dong and gu and observed_gu == gu:
        return "same_dong"
    if gu and observed_gu == gu:
        return "same_gu"
    return "fallback"
