"""
llm_utils.py — LLM·외부 검색 유틸리티 v1.0

analysis_tools.py에서 분리된 LLM/API 호출 모듈.
외부 의존: Ollama (로컬 LLM), Kakao REST API, Tavily 웹검색.

공개 인터페이스:
  generate_appraisal_opinion() — Ollama 감정평가 의견서 생성
  search_nearby_facilities()   — Kakao POI 주변 시설 조회
  search_web_tavily()          — Tavily 웹 검색 요약
"""

from __future__ import annotations

import json
import os
import re
import time

import requests
from dotenv import find_dotenv, load_dotenv
from model_factory import get_llm_json

load_dotenv(find_dotenv())

KAKAO_API_KEY  = os.getenv("KAKAO_REST_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

if not KAKAO_API_KEY:
    print("[llm_utils] ⚠️  KAKAO_REST_API_KEY 없음 → 주변시설 조회 불가")


# ─────────────────────────────────────────
#  Kakao 주변 시설 검색
# ─────────────────────────────────────────

KAKAO_CATEGORY_URL   = "https://dapi.kakao.com/v2/local/search/category.json"
KAKAO_CATEGORY_CODES = {
    "지하철역": "SW8", "학교": "SC4", "마트": "MT1",
    "편의점": "CS2",  "병원": "HP8", "음식점": "FD6",
    "카페": "CE7",    "주차장": "PK6", "은행": "BK9",
}


def search_nearby_facilities(lat: float, lng: float,
                              categories: list[str], radius: int = 1000) -> dict:
    if not KAKAO_API_KEY:
        return {}
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    result  = {}
    for cat_name in categories:
        cat_code = KAKAO_CATEGORY_CODES.get(cat_name)
        if not cat_code:
            continue
        try:
            res  = requests.get(KAKAO_CATEGORY_URL, headers=headers, params={
                "category_group_code": cat_code,
                "x": lng, "y": lat, "radius": radius, "size": 15, "sort": "distance",
            }, timeout=5)
            docs = res.json().get("documents", [])
            result[cat_name] = {
                "count":        len(docs),
                "nearest_m":    int(docs[0].get("distance", 9999)) if docs else 9999,
                "nearest_name": docs[0].get("place_name", "") if docs else "",
            }
            time.sleep(0.05)
        except Exception as e:
            print(f"[kakao_nearby] {cat_name} 오류: {e}")
    return result


# ─────────────────────────────────────────
#  Tavily 웹 검색
# ─────────────────────────────────────────

def search_web_tavily(query: str, max_results: int = 3) -> str:
    if not TAVILY_API_KEY:
        return ""
    try:
        res  = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_API_KEY, "query": query,
                  "max_results": max_results, "search_depth": "basic",
                  "include_answer": True},
            timeout=10,
        )
        data = res.json()
        if data.get("answer"):
            return data["answer"]
        return " / ".join(r.get("content", "")[:200] for r in data.get("results", []))
    except Exception as e:
        print(f"[tavily] 오류: {e}")
        return ""


# ─────────────────────────────────────────
#  AI 분석 의견 생성 (수치 가드레일 적용)
# ─────────────────────────────────────────

APPRAISAL_PROMPT = """당신은 부동산 시장 데이터 분석 전문가입니다.
아래 데이터를 바탕으로 AI 시세추정 리포트에 들어갈 분석 의견을 작성하세요.

작성 규칙:
- 스스로를 감정평가사로 칭하거나 "감정평가"라는 단어를 사용하지 마세요. (본 서비스는 감정평가가 아닌 AI 시세추정입니다)
- "추정 시세", "시세 분석", "AI 분석" 등의 표현을 사용하세요.
- 수치는 위 데이터에 있는 값만 그대로 인용하세요. 데이터에 없는 금액·비율·수치를
  만들어 쓰면 해당 문장은 자동 검증에서 삭제됩니다.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "appraisal_opinion": "3~4문장의 시세 분석 의견",
  "strengths": ["가치 상승 요인1", "요인2", "요인3"],
  "risk_factors": ["리스크 요인1", "요인2"],
  "recommendation": "매수 적극 고려 | 매수 고려 | 관망 | 매수 비추천"
}"""

_MAX_ATTEMPTS = 2   # 최초 1회 + 수치 위반 재시도 1회


def _invoke_opinion_llm(llm, user_content: str) -> dict | None:
    """LLM 호출 + JSON 파싱. 실패 시 None."""
    try:
        response = llm.invoke([("system", APPRAISAL_PROMPT), ("human", user_content)])
        raw = response.content.strip()
        try:
            return json.loads(raw)                       # 네이티브 JSON 모드
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)  # 텍스트 섞임 대응
            if match:
                return json.loads(match.group())
    except Exception as e:
        print(f"[appraisal_llm] 호출 오류: {e}")
    return None


def generate_appraisal_opinion(category, location, valuation_data, nearby_data, web_summary) -> dict:
    """
    AI 분석 의견 생성.

    가드레일 (opinion_guard):
      - 출력을 OpinionOutput 스키마로 강제 (프로바이더 무관 동일 형식)
      - 컨텍스트로 주입한 수치 외의 숫자가 든 문장·항목은 제거
      - 의견 전체가 제거되면 위반 수치를 명시해 1회 재시도
      - 재시도도 실패하면 결정론적 폴백 의견 반환
    """
    import opinion_guard

    llm = get_llm_json()
    estimated   = valuation_data.get("estimated_value", 0)
    cap_rate    = valuation_data.get("cap_rate", 0)
    ppyeong     = valuation_data.get("price_per_pyeong", 0)
    reg_ppyeong = valuation_data.get("regional_avg_per_pyeong", 0)
    roi_5yr     = valuation_data.get("roi_5yr", 0)
    annual_inc  = valuation_data.get("annual_income", 0)
    value_min   = valuation_data.get("value_min", 0)
    value_max   = valuation_data.get("value_max", 0)

    nearby_text = "\n".join(
        f"  {k}: {v.get('count', 0)}개 (최근접 {v.get('nearest_m', 0)}m)"
        for k, v in nearby_data.items() if isinstance(v, dict) and v.get("count", 0) > 0
    ) or "주변 시설 정보 없음"

    user_content = f"""
분석 대상: {category} / {location}
추정 시장가치: {estimated:,}만원 (범위 {value_min:,}만원 ~ {value_max:,}만원)
평당가: {ppyeong:,}만원/평 (지역 평균: {reg_ppyeong:,}만원/평)
Cap Rate: {cap_rate}% / 5년 예상 수익률: {roi_5yr}% / 연 임대수입 추정: {annual_inc:,}만원
주변 환경: {nearby_text}
시장 동향: {web_summary or '정보 없음'}
"""

    # 수치 화이트리스트 = 프롬프트에 주입한 컨텍스트의 모든 수치
    allowed = opinion_guard.extract_numbers(user_content)

    content = user_content
    for attempt in range(_MAX_ATTEMPTS):
        raw = _invoke_opinion_llm(llm, content)
        if raw is None:
            continue

        clean, report = opinion_guard.validate(raw, allowed)

        if report["blocked"]:
            print(f"[opinion_guard] 미제공 수치 차단: {report['blocked'][:5]}"
                  f" (항목 {report['dropped_items']}개 제거, 시도 {attempt + 1}/{_MAX_ATTEMPTS})")

        if clean["appraisal_opinion"]:
            return clean

        # 의견 전체가 위반으로 제거됨 → 위반 수치를 명시해 재작성 요청
        content = user_content + (
            f"\n\n[재작성 요청] 이전 응답에 데이터에 없는 수치 {report['blocked'][:5]} 가 포함되어"
            " 전부 삭제되었습니다. 위 데이터의 수치만 정확히 인용해 다시 작성하세요."
        )

    # 폴백: 지역 평균 대비 수준 산출 (LLM 실패·전량 차단 시)
    if reg_ppyeong > 0 and ppyeong > 0:
        ratio = ppyeong / reg_ppyeong
        verdict = "높은" if ratio > 1.05 else "낮은" if ratio < 0.95 else "유사한"
        verdict_str = f" 인근 지역 평균 평당가 대비 {verdict} 수준."
    else:
        verdict_str = ""

    return {
        "appraisal_opinion": f"{location} {category} 추정 시세 {estimated:,}만원.{verdict_str}",
        "strengths":    ["실거래 데이터 기반 분석 완료"],
        "risk_factors": ["LLM 분석 의견 생성 실패 — 수치 기반 결과만 제공"],
        "recommendation": "관망",
    }
