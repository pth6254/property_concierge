"""
opinion_guard.py — LLM 분석 의견 출력 가드레일

목적:
  가격 계산은 price_engine(결정론), 의견 서술은 LLM으로 분리되어 있지만
  LLM이 의견 텍스트 안에 임의 수치를 만들어 넣으면 리포트 본문과
  테이블 수치가 어긋난다. 이 모듈은 두 가지를 강제한다:

  1. 출력 스키마 검증 — 프로바이더(ollama/openai/anthropic/google)가 무엇이든
     경계에서 OpinionOutput 스키마로 수렴 (누락 키 보정, 타입 강제, 항목 수 제한)
  2. 수치 화이트리스트 — "LLM은 프롬프트로 받은 숫자만 말할 수 있다"
     출력의 모든 수치 토큰을 입력 컨텍스트의 수치와 대조,
     불일치 수치가 든 문장/항목은 제거

사용:
  allowed = extract_numbers(프롬프트에 주입한 컨텍스트 텍스트)
  clean, report = validate(raw_llm_dict, allowed)
  if not clean["appraisal_opinion"]: → 재시도 or 폴백
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# 추천 등급 enum (프롬프트와 동일)
RECOMMENDATIONS = ["매수 적극 고려", "매수 고려", "관망", "매수 비추천"]

MAX_LIST_ITEMS = 5      # strengths / risk_factors 최대 항목 수
MAX_ITEM_CHARS = 150    # 항목당 최대 길이
MAX_OPINION_CHARS = 800

# 수치 대조 허용 오차 (상대) — "약 62억" 같은 반올림 인용은 허용하되(≤1%),
# 그보다 벗어난 근접 위조 수치는 차단
REL_TOLERANCE = 0.01


# ─────────────────────────────────────────
#  출력 스키마
# ─────────────────────────────────────────

class OpinionOutput(BaseModel):
    """LLM 분석 의견의 유일한 통과 형식."""
    appraisal_opinion: str = ""
    strengths: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    recommendation: str = "관망"

    @field_validator("appraisal_opinion", "recommendation", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        if v is None:
            return ""
        if isinstance(v, list):          # 문장 배열로 주는 모델 대응
            return " ".join(str(x) for x in v)
        return str(v)

    @field_validator("strengths", "risk_factors", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):           # 단일 문자열로 주는 모델 대응
            return [v] if v.strip() else []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []


def normalize_recommendation(text: str) -> str:
    """자유 서술 추천 문구 → 4단계 enum 정규화."""
    t = (text or "").strip()
    if t in RECOMMENDATIONS:
        return t
    if "적극" in t:
        return "매수 적극 고려"
    if any(k in t for k in ("비추천", "부정", "매도", "회피")):
        return "매수 비추천"
    if any(k in t for k in ("관망", "보류", "중립", "신중", "유보")):
        return "관망"
    if any(k in t for k in ("매수", "추천", "고려", "긍정")):
        return "매수 고려"
    return "관망"


# ─────────────────────────────────────────
#  수치 추출·정규화
# ─────────────────────────────────────────

_EOK_COMPOSITE = re.compile(r"(\d[\d,]*)\s*억\s*(\d[\d,]*)\s*만")   # 62억 1144만
_EOK_SIMPLE    = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*억")           # 62억 / 6.2억
_NUM_LITERAL   = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def _normalize_krw(text: str) -> str:
    """억 단위 표기를 만원 단위 숫자로 치환해 단일 스케일로 비교 가능하게 한다."""
    def _composite(m):
        return f"{int(_to_float(m.group(1)) * 10_000 + _to_float(m.group(2)))}만"
    def _simple(m):
        return f"{int(round(_to_float(m.group(1)) * 10_000))}만"
    text = _EOK_COMPOSITE.sub(_composite, text)
    text = _EOK_SIMPLE.sub(_simple, text)
    return text


def extract_numbers(text: str) -> set[float]:
    """텍스트의 모든 수치 리터럴 (억 표기는 만원 스케일로 정규화 후)."""
    if not text:
        return set()
    normalized = _normalize_krw(str(text))
    return {_to_float(m) for m in _NUM_LITERAL.findall(normalized)}


def _is_allowed_number(v: float, allowed: set[float]) -> bool:
    """
    수치 허용 판정:
      - 작은 정수(≤200): 개수·년차·층수 등 서술용 — 허용
      - 연도(1900~2100): 허용
      - 그 외: 허용 집합과 상대오차 2% 이내 일치 (원↔만원 스케일 변환 포함)
    """
    if v <= 200:
        return True
    if 1900 <= v <= 2100 and v == int(v):
        return True
    for a in allowed:
        if a <= 0:
            continue
        for scaled in (v, v / 10_000, v * 10_000):   # 원↔만원 표기 차이 허용
            if abs(scaled - a) <= max(a * REL_TOLERANCE, 0.5):
                return True
    return False


def find_violations(text: str, allowed: set[float]) -> list[float]:
    """텍스트에서 허용되지 않은 수치 목록."""
    return sorted(v for v in extract_numbers(text) if not _is_allowed_number(v, allowed))


# ─────────────────────────────────────────
#  문장 단위 정화
# ─────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def sanitize_text(text: str, allowed: set[float]) -> tuple[str, list[float]]:
    """
    위반 수치가 포함된 문장만 제거하고 나머지를 보존.
    반환: (정화된 텍스트, 차단된 수치 목록)
    """
    if not text:
        return "", []
    blocked: list[float] = []
    kept: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text.strip()):
        if not sentence.strip():
            continue
        bad = find_violations(sentence, allowed)
        if bad:
            blocked.extend(bad)
        else:
            kept.append(sentence.strip())
    return " ".join(kept), blocked


# ─────────────────────────────────────────
#  통합 검증
# ─────────────────────────────────────────

def validate(raw: dict, allowed: set[float]) -> tuple[dict, dict]:
    """
    LLM 원시 출력 → 스키마 강제 + 수치 가드 적용.

    반환:
      clean  : OpinionOutput 필드 dict (위반 문장·항목 제거됨)
      report : {"blocked": [수치...], "dropped_items": int}
               blocked 존재 + opinion 비어있음 → 호출측 재시도/폴백 판단
    """
    try:
        out = OpinionOutput.model_validate(raw or {})
    except Exception:
        out = OpinionOutput()

    blocked_all: list[float] = []
    dropped_items = 0

    # 의견 본문: 문장 단위 정화
    opinion, blocked = sanitize_text(out.appraisal_opinion[:MAX_OPINION_CHARS], allowed)
    blocked_all.extend(blocked)

    # 목록 항목: 위반 항목 전체 제거
    def _clean_items(items: list[str]) -> list[str]:
        nonlocal dropped_items, blocked_all
        kept = []
        for item in items[:MAX_LIST_ITEMS]:
            item = item[:MAX_ITEM_CHARS]
            bad = find_violations(item, allowed)
            if bad:
                blocked_all.extend(bad)
                dropped_items += 1
            else:
                kept.append(item)
        return kept

    clean = {
        "appraisal_opinion": opinion,
        "strengths":         _clean_items(out.strengths),
        "risk_factors":      _clean_items(out.risk_factors),
        "recommendation":    normalize_recommendation(out.recommendation),
    }
    report = {
        "blocked":       sorted(set(blocked_all)),
        "dropped_items": dropped_items,
    }
    return clean, report
