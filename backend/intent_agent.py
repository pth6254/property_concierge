"""
DeepAgent 부동산 컨시어지 — Step 1: 의도 분석 에이전트
로컬 모델 또는 OpenRouter 모델로 주소·유형 검색 힌트를 추출한다.

변경사항:
  - category 값을 완전 한국어로 통일 (주거용/상업용/업무용/산업용/토지)
  - 모든 LLM 응답값 한국어 강제
  - 영문·혼용 응답 → 한국어로 정규화하는 매핑 테이블 확장
  - Pydantic 전 필드 default 보유 (필드 누락 에러 방지)
  - num_predict=1024 (JSON 잘림 방지)
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional
from typing_extensions import TypedDict

from model_factory import get_appraisal_intent_llm
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field


# ─────────────────────────────────────────
#  1. 카테고리 상수 — 한국어로 통일
# ─────────────────────────────────────────

CATEGORY_주거용  = "주거용"
CATEGORY_상업용  = "상업용"
CATEGORY_업무용  = "업무용"
CATEGORY_산업용  = "산업용"
CATEGORY_토지    = "토지"

VALID_CATEGORIES = [
    CATEGORY_주거용, CATEGORY_상업용,
    CATEGORY_업무용, CATEGORY_산업용, CATEGORY_토지,
]

VALID_TRANSACTION_TYPES = ["매매", "전세", "월세", "임대", "분양"]


# ─────────────────────────────────────────
#  2. 데이터 모델
# ─────────────────────────────────────────

class PropertyIntent(BaseModel):
    """의도 분석 결과 — 모든 값 한국어"""

    # LLM이 추출한 검색 후보다. 지오코딩 이후의 최종 유형은 사용자 선택·공식
    # 데이터·규칙으로 다시 확정하며 이 값을 그대로 신뢰하지 않는다.
    category: str            = Field(default="주거용")
    category_detail: str     = Field(default="")        # 아파트, 빌라, 상가, 사무실 등

    # 위치
    location_raw: str        = Field(default="")        # 사용자 원문
    location_normalized: str = Field(default="")        # 정규화된 행정구역명

    # 거래 유형: 매매 / 전세 / 월세 / 임대 / 분양
    transaction_type: str    = Field(default="")

    # 가격 (만원 단위)
    price_min: Optional[int]   = Field(default=None)
    price_max: Optional[int]   = Field(default=None)
    price_raw: str             = Field(default="")      # 원본 가격 텍스트

    # 면적 (㎡)
    area_min: Optional[float]  = Field(default=None)
    area_max: Optional[float]  = Field(default=None)
    area_raw: str              = Field(default="")      # 원본 면적 텍스트

    # 비정형 특수 조건
    special_conditions: list[str] = Field(default_factory=list)

    # 상세 호실 정보 (집합건물용)
    dong_no:         str            = Field(default="")   # 동번호 (예: "101동", "A동")
    ho_no:           str            = Field(default="")   # 호번호 (예: "1502호", "302호")
    floor_inferred:  Optional[int]  = Field(default=None) # ho_no에서 추론한 층수

    # 감정평가 기준시점 (YYYYMMDD, 빈 문자열이면 현재 시점)
    appraisal_date: str        = Field(default="")

    # 분석 메타
    confidence: float          = Field(default=0.5)
    missing_fields: list[str]  = Field(default_factory=list)
    clarification_question: str = Field(default="")


class IntentState(TypedDict, total=False):
    """LangGraph 상태 객체 — TypedDict (dict 호환)"""
    user_input:     str
    intent:         Optional[PropertyIntent]
    raw_llm_output: str
    error:          str
    retry_count:    int


# ─────────────────────────────────────────
#  3. LLM 설정
# ─────────────────────────────────────────

def get_llm():
    return get_appraisal_intent_llm()


# ─────────────────────────────────────────
#  4. 프롬프트 — 완전 한국어 기준
# ─────────────────────────────────────────

INTENT_SYSTEM_PROMPT = """당신은 한국 부동산 전문 AI 어시스턴트입니다.
사용자의 요청을 분석하여 아래 형식의 JSON 하나만 출력하세요.
설명, 마크다운, 코드블록 없이 순수 JSON만 출력하세요.

## 반드시 포함해야 할 키 (정확히 이 이름 사용, 추가·변경 금지)
- category           : 아래 5가지 중 하나의 문자열
- category_detail    : 세부 유형 문자열 (예: 아파트, 빌라, 상가, 사무실, 창고, 토지)
- location_raw       : 사용자가 말한 위치 원문 문자열
- location_normalized: 사용자가 입력한 주소를 최대한 그대로 보존한 문자열
                       도로명·지번·건물번호 등이 있으면 반드시 포함할 것
                       (예: 사용자가 "경기 오산시 가장산업동로 37" 입력 →
                            location_normalized = "경기 오산시 가장산업동로 37")
                       시·구 단위로 축약하지 말 것
- transaction_type   : 아래 거래유형 중 하나의 문자열
- price_min          : 최소 가격 정수(만원) 또는 null
- price_max          : 최대 가격 정수(만원) 또는 null
- price_raw          : 원본 가격 텍스트 문자열
- area_min           : 최소 면적 실수(㎡) 또는 null
- area_max           : 최대 면적 실수(㎡) 또는 null
- area_raw           : 원본 면적 텍스트 문자열
- special_conditions : 특수조건 문자열 배열
- dong_no             : 동 번호 문자열 (예: "101동", "A동", 없으면 "")
- ho_no               : 호 번호 문자열 (예: "1502호", "302호", 없으면 "")
- appraisal_date     : 감정평가 기준시점 YYYYMMDD 문자열 (현재시점이면 "", 과거 시점이면 날짜 변환)
                       예: "3개월 전" → 현재가 2026년 6월이면 "20260314"
                           "2025년 3월 14일" → "20250314"
                           "작년 초" → 대략 "20250101"
                           명시 없으면 ""
- confidence         : 신뢰도 실수 0.0~1.0
- missing_fields     : 누락된 항목명 문자열 배열
- clarification_question : 추가 확인 질문 문자열 (없으면 빈 문자열)

## category 허용값 (검색 후보이며 최종 부동산 유형을 확정하지 않음)
주거용 → 아파트, 빌라, 오피스텔, 원룸, 단독주택
상업용 → 상가, 점포, 식당, 카페 등 수익형 상업시설
업무용 → 사무실, 오피스
산업용 → 공장, 창고, 물류센터, 지식산업센터
토지   → 토지, 대지, 농지, 임야

## transaction_type 허용값
매매, 전세, 월세, 임대, 분양

## 변환 규칙
- 1평 = 3.3058㎡
- 20평대 → area_min: 66.1, area_max: 99.2
- 50평 이상 → area_min: 165.3, area_max: null
- 가격 단위는 만원 (1억=10000, 3억=30000, 5억~7억 → min:50000 max:70000)
- 모르는 숫자는 null, 모르는 문자열은 ""

## 출력 예시
{"category":"주거용","category_detail":"아파트","location_raw":"서울시 마포구 월드컵북로 396","location_normalized":"서울시 마포구 월드컵북로 396","transaction_type":"매매","price_min":80000,"price_max":90000,"price_raw":"8억~9억","area_min":84.0,"area_max":84.0,"area_raw":"84㎡","dong_no":"","ho_no":"","appraisal_date":"","special_conditions":[],"confidence":0.95,"missing_fields":[],"clarification_question":""}"""

INTENT_USER_TEMPLATE = "사용자 요청: {user_input}"


# ─────────────────────────────────────────
#  5. 정규화 매핑 테이블
# ─────────────────────────────────────────

# 모델이 임의로 바꾼 키 이름 → 정규 키로 복원
KEY_ALIASES = {
    "location":            "location_raw",
    "location_name":       "location_raw",
    "location_detail":     "location_raw",
    "address":             "location_normalized",
    "property_type":       "category",
    "type":                "category",
    "trade_type":          "transaction_type",
    "transaction":         "transaction_type",
    "deal_type":           "transaction_type",
    "deposit":             "price_raw",
    "price":               "price_raw",
    "area":                "area_raw",
    "size":                "area_raw",
    "동":   "dong_no",
    "호":   "ho_no",
    "동번호": "dong_no",
    "호번호": "ho_no",
}

# category 정규화 — 영문·혼용·축약어 → 한국어 5종
CATEGORY_MAP = {
    # 주거용
    "주거용": "주거용", "residential": "주거용",
    "아파트": "주거용", "apartment": "주거용",
    "빌라": "주거용",   "villa": "주거용",
    "오피스텔": "주거용","officetels": "주거용",
    "원룸": "주거용",   "단독주택": "주거용",
    "house": "주거용",  "housing": "주거용",
    # 상업용
    "상업용": "상업용", "commercial": "상업용",
    "상가": "상업용",   "store": "상업용",
    "점포": "상업용",   "shop": "상업용",
    "카페": "상업용",   "식당": "상업용",
    "cafe": "상업용",   "restaurant": "상업용",
    # 업무용
    "업무용": "업무용", "office": "업무용",
    "사무실": "업무용", "오피스": "업무용",
    "업무": "업무용",
    # 산업용
    "산업용": "산업용", "industrial": "산업용",
    "공장": "산업용",   "factory": "산업용",
    "창고": "산업용",   "warehouse": "산업용",
    "물류": "산업용",   "logistics": "산업용",
    "지식산업센터": "산업용",
    # 토지
    "토지": "토지", "land": "토지",
    "대지": "토지", "농지": "토지",
    "임야": "토지", "lot": "토지",
}

# transaction_type 정규화
TRANSACTION_MAP = {
    "매매": "매매", "sale": "매매", "purchase": "매매", "buy": "매매", "売買": "매매",
    "전세": "전세", "lease": "전세", "jeonse": "전세",
    "월세": "월세", "rent": "월세", "rental": "월세", "monthly rent": "월세",
    "임대": "임대", "임대차": "임대",
    "분양": "분양", "presale": "분양",
}


# ─────────────────────────────────────────
#  6. 파싱 정규화 함수
# ─────────────────────────────────────────

def _infer_floor_from_ho(ho_no: str) -> Optional[int]:
    """
    호번호에서 층수 추론.
    예) "1502호" → 15, "302호" → 3, "B101호" → -1
    """
    if not ho_no:
        return None
    # 지하층: B로 시작하거나 "지하" 포함
    ho_clean = ho_no.replace("호", "").strip()
    if ho_clean.upper().startswith("B") or "지하" in ho_no:
        return -1
    # 숫자만 추출
    digits = re.sub(r"[^0-9]", "", ho_clean)
    if not digits:
        return None
    num = int(digits)
    # 4자리: 앞 두 자리가 층 (예: 1502 → 15층)
    if num >= 1000:
        return num // 100
    # 3자리: 첫 자리가 층 (예: 302 → 3층)
    if num >= 100:
        return num // 100
    return None


def normalize_parsed_data(data: dict) -> dict:
    """
    LLM raw dict → PropertyIntent 호환 dict 변환
    어떤 모델이 어떤 형태로 반환해도 한국어 표준값으로 복원
    """
    out = dict(data)

    # ① 키 이름 정규화
    for alias, canonical in KEY_ALIASES.items():
        if alias in out and canonical not in out:
            out[canonical] = out.pop(alias)

    # ② list → str (배열로 온 단일값 필드)
    for field in ("category", "transaction_type", "category_detail",
                  "location_raw", "location_normalized", "price_raw", "area_raw"):
        val = out.get(field)
        if isinstance(val, list):
            out[field] = val[0] if val else ""

    # ③ nested dict → str (location이 {"name": "마포구"} 형태일 때)
    for field in ("location_raw", "location_normalized"):
        val = out.get(field)
        if isinstance(val, dict):
            out[field] = (
                val.get("name") or val.get("value") or
                val.get("description") or str(val)
            )

    # ④ category → 한국어 5종으로 정규화
    raw_cat = str(out.get("category", "")).strip().lower()
    # 먼저 소문자로 시도, 안 되면 원문 그대로 시도
    out["category"] = (
        CATEGORY_MAP.get(raw_cat)
        or CATEGORY_MAP.get(out.get("category", "").strip())
        or "주거용"
    )

    # ⑤ transaction_type → 한국어로 정규화
    raw_tt = str(out.get("transaction_type", "")).strip().lower()
    out["transaction_type"] = (
        TRANSACTION_MAP.get(raw_tt)
        or TRANSACTION_MAP.get(out.get("transaction_type", "").strip())
        or out.get("transaction_type", "")
    )

    # ⑥ location 교차 보완
    if not out.get("location_raw") and out.get("location_normalized"):
        out["location_raw"] = out["location_normalized"]
    if not out.get("location_normalized") and out.get("location_raw"):
        out["location_normalized"] = out["location_raw"]

    # ⑦ 숫자 필드 타입 보정 (문자열로 온 경우)
    for field in ("price_min", "price_max"):
        val = out.get(field)
        if isinstance(val, str):
            try:
                out[field] = int(val.replace(",", "").replace("만원", "").strip())
            except ValueError:
                out[field] = None

    for field in ("area_min", "area_max"):
        val = out.get(field)
        if isinstance(val, str):
            try:
                out[field] = float(val.replace("㎡", "").strip())
            except ValueError:
                out[field] = None

    # ⑧ ho_no에서 floor_inferred 자동 계산
    if not out.get("floor_inferred") and out.get("ho_no"):
        out["floor_inferred"] = _infer_floor_from_ho(out.get("ho_no", ""))

    return out


# ─────────────────────────────────────────
#  7. LangGraph 노드
# ─────────────────────────────────────────

def intent_analysis_node(state: dict) -> dict:
    llm = get_llm()
    user_input = state.get("user_input", "")
    messages = [
        ("system", INTENT_SYSTEM_PROMPT),
        ("human", INTENT_USER_TEMPLATE.format(user_input=user_input)),
    ]

    try:
        response = llm.invoke(messages)
        raw = response.content.strip()
        state["raw_llm_output"] = raw

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("LLM 응답에서 JSON을 찾을 수 없음")

        data = json.loads(json_match.group())
        data = normalize_parsed_data(data)

        state["intent"] = PropertyIntent(**data)
        state["error"] = ""

    except json.JSONDecodeError as e:
        state["error"] = f"JSON 파싱 오류: {e}\n원문: {raw[:300]}"
        state["retry_count"] = state.get("retry_count", 0) + 1

    except Exception as e:
        state["error"] = f"의도 분석 오류: {e}"
        state["retry_count"] = state.get("retry_count", 0) + 1

    return state


def validate_node(state: dict) -> dict:
    error       = state.get("error", "")
    retry_count = state.get("retry_count", 0)

    if error:
        if retry_count <= 2:
            print(f"[검증] 재시도 예정 ({retry_count}/2): {error[:60]}")
        else:
            print(f"[검증] 최대 재시도 초과. 분석 실패.")
        return state

    intent = state.get("intent")
    if not intent:
        return state

    # category 값 안전 검사
    if intent.category not in VALID_CATEGORIES:
        print(f"[검증] ⚠️ 알 수 없는 카테고리 '{intent.category}' → 주거용으로 보정")
        intent.category = "주거용"

    if intent.confidence < 0.6:
        print(f"[검증] ⚠️ 낮은 신뢰도 ({intent.confidence}) | 누락: {intent.missing_fields}")

    return state


# ─────────────────────────────────────────
#  8. 그래프 구성
# ─────────────────────────────────────────

def should_retry(state: dict) -> str:
    if state.get("error") and state.get("retry_count", 0) <= 2:
        return "retry"
    return "end"


def build_intent_graph() -> StateGraph:
    graph = StateGraph(IntentState)
    graph.add_node("의도분석",   intent_analysis_node)
    graph.add_node("검증",       validate_node)
    graph.set_entry_point("의도분석")
    graph.add_edge("의도분석", "검증")
    graph.add_conditional_edges(
        "검증",
        should_retry,
        {"retry": "의도분석", "end": END},
    )
    return graph.compile()


def analyze_intent(user_input: str) -> dict:
    """자연어 부동산 요청 → 구조화된 IntentState 반환"""
    graph = build_intent_graph()
    return graph.invoke({"user_input": user_input, "error": "", "retry_count": 0})


# ─────────────────────────────────────────
#  9. CLI 테스트
# ─────────────────────────────────────────

TEST_CASES = [
    "마포구 조용한 동네 아파트 전세 4억~5억 20평대",
    "강남 유동인구 많은 곳에 카페 창업하려고. 보증금 1억 이내.",
    "인천 남동공단 근처 창고 임대. 트럭 진입 가능하고 층고 6m 이상. 300평 이상.",
    "사무실 구하는데 주차 많은 곳",
]

if __name__ == "__main__":
    model_name = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
    print("=" * 60)
    print(f"  모델: {model_name}")
    print("=" * 60)

    for i, query in enumerate(TEST_CASES, 1):
        print(f"\n[테스트 {i}] {query}")
        print("-" * 50)
        result = analyze_intent(query)

        if result.get("error"):
            print(f"❌ 오류: {result['error'][:120]}")
            print(f"   원문: {result.get('raw_llm_output', '')[:200]}")
        else:
            intent = result["intent"]
            print(f"✅ 카테고리   : {intent.category} / {intent.category_detail}")
            print(f"   위치       : {intent.location_normalized} (원문: {intent.location_raw})")
            print(f"   거래유형   : {intent.transaction_type}")
            print(f"   가격       : {intent.price_min}~{intent.price_max}만원 ({intent.price_raw})")
            print(f"   면적       : {intent.area_min}~{intent.area_max}㎡ ({intent.area_raw})")
            print(f"   특수조건   : {intent.special_conditions}")
            print(f"   신뢰도     : {intent.confidence}")
            if intent.missing_fields:
                print(f"   ⚠️ 누락항목 : {intent.missing_fields}")
            if intent.clarification_question:
                print(f"   💬 재질문   : {intent.clarification_question}")
