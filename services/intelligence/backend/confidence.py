"""
confidence.py — AVM 추정 신뢰도 산출 (통합 모듈)

기존 문제:
  appraisal_report / price_analysis_service 가 각자 건수 if/else 4단계로
  신뢰도를 계산 — 표본 산포·매칭 수준·시점수정 방식이 반영되지 않음.

이 모듈의 신뢰도 정의:
  "유사 조건에서 추정치가 실거래가 ±10% 이내에 들 확률"

산출 방식 (2단계):
  1) 휴리스틱 점수 — 매칭 수준(동일단지~폴백) 기반점 + 표본 수·산포(CV)·
     신선도·시점수정 방식 가감
  2) 백테스트 보정 — tools/backtest_avm.py 가 생성한
     data/avm_calibration.json 의 버킷별 실측 적중률(hit10)과 블렌딩
     (버킷 표본이 많을수록 실측값 비중 증가)

사용:
  from confidence import compute_confidence
  r = compute_confidence(count=6, samples=[...], used_months=3, source="")
  r["score"]  # 0.10 ~ 0.95
  r["basis"]  # "calibrated" | "heuristic"
"""

from __future__ import annotations

import json
import os
from statistics import mean, pstdev

_BACKEND_DIR  = os.path.dirname(os.path.abspath(__file__))
from concierge_workspace import REPO_ROOT
_PROJECT_ROOT = str(REPO_ROOT)

CALIBRATION_PATH = os.getenv(
    "AVM_CALIBRATION_PATH",
    os.path.join(_PROJECT_ROOT, "data", "avm_calibration.json"),
)

SCORE_FLOOR, SCORE_CAP = 0.10, 0.95

# 매칭 수준별 기반 점수
_BASE_BY_MATCH = {
    "same_complex": 0.85,
    "same_dong":    0.72,
    "same_gu":      0.60,
    "nearby":       0.50,
    "fallback":     0.30,
}
_DEFAULT_BASE = 0.60

# 보정테이블 블렌딩: 실측 가중치 = n / (n + _BLEND_PRIOR)
_BLEND_PRIOR = 20

_FALLBACK_KEYWORDS = ["공시가격", "수익환원법", "원가법", "공시지가"]

_calibration_cache: tuple[float, dict] | None = None   # (mtime, data)


# ─────────────────────────────────────────
#  보정테이블 로드
# ─────────────────────────────────────────

def load_calibration() -> dict:
    """data/avm_calibration.json 로드 (mtime 캐시). 없으면 빈 dict."""
    global _calibration_cache
    try:
        mtime = os.path.getmtime(CALIBRATION_PATH)
    except OSError:
        return {}
    if _calibration_cache and _calibration_cache[0] == mtime:
        return _calibration_cache[1]
    try:
        with open(CALIBRATION_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _calibration_cache = (mtime, data)
        return data
    except Exception as e:
        print(f"[confidence] 보정테이블 로드 실패: {e}")
        return {}


def count_band(n: int) -> str:
    if n >= 10: return "n10+"
    if n >= 5:  return "n5-9"
    if n >= 2:  return "n2-4"
    return "n1"


# ─────────────────────────────────────────
#  매칭 수준·산포 도출
# ─────────────────────────────────────────

def dominant_match_level(samples: list[dict] | None) -> str:
    """샘플 목록에서 지배적 매칭 수준 (다수결)."""
    if not samples:
        return ""
    votes: dict[str, int] = {}
    for s in samples:
        from comparable_matching import comparable_match_level
        lv = comparable_match_level(s)
        votes[lv] = votes.get(lv, 0) + 1
    return max(votes, key=lambda k: votes[k])


def _dispersion_cv(samples: list[dict] | None) -> float | None:
    """㎡당 단가(없으면 가격)의 변동계수(CV = 표준편차/평균)."""
    if not samples:
        return None
    vals = [s.get("per_sqm") or 0 for s in samples if (s.get("per_sqm") or 0) > 0]
    if len(vals) < 2:
        vals = [s.get("price") or 0 for s in samples if (s.get("price") or 0) > 0]
    if len(vals) < 2:
        return None
    m = mean(vals)
    return pstdev(vals) / m if m > 0 else None


# ─────────────────────────────────────────
#  신뢰도 산출
# ─────────────────────────────────────────

def compute_confidence(
    count: int,
    samples: list[dict] | None = None,
    match_level: str = "",
    used_months: int = 0,
    source: str = "",
) -> dict:
    """
    반환: {
      "score": 0.10~0.95,
      "basis": "calibrated" | "heuristic",
      "match_level": str, "band": str,
      "factors": {개별 가감 내역},
    }
    """
    factors: dict[str, float] = {}

    if count <= 0:
        return {"score": SCORE_FLOOR, "basis": "heuristic",
                "match_level": "none", "band": "n0", "factors": {"no_data": SCORE_FLOOR}}

    # 폴백 출처(공시가격 역산 등)는 매칭 수준 무관 저신뢰
    is_fallback = any(kw in (source or "") for kw in _FALLBACK_KEYWORDS)
    if is_fallback:
        match_level = "fallback"

    if not match_level:
        match_level = dominant_match_level(samples) or ""

    base = _BASE_BY_MATCH.get(match_level, _DEFAULT_BASE)
    factors["base(" + (match_level or "unknown") + ")"] = base
    score = base

    # 표본 수
    if count >= 20:   adj = +0.05
    elif count >= 10: adj = +0.03
    elif count >= 5:  adj = 0.0
    elif count >= 2:  adj = -0.08
    else:             adj = -0.18
    score += adj
    factors["count"] = adj

    # 표본 산포 (CV)
    cv = _dispersion_cv(samples)
    if cv is not None:
        if cv <= 0.10:   adj = +0.02
        elif cv <= 0.20: adj = 0.0
        elif cv <= 0.35: adj = -0.08
        else:            adj = -0.15
        score += adj
        factors[f"dispersion(cv={cv:.2f})"] = adj

    # 데이터 신선도
    if used_months > 12:  adj = -0.12
    elif used_months > 6: adj = -0.06
    else:                 adj = 0.0
    score += adj
    factors["freshness"] = adj

    # 시점수정 방식 (부동산원 지수 적용 비율)
    if samples:
        reb = sum(1 for s in samples if s.get("time_adj_source") == "reb_index")
        adjusted_cnt = sum(1 for s in samples if s.get("time_adj_months", 0) > 0)
        if adjusted_cnt > 0 and reb == adjusted_cnt:
            score += 0.03
            factors["time_adj(reb_index)"] = +0.03

    heuristic = max(SCORE_FLOOR, min(SCORE_CAP, score))
    if is_fallback:
        heuristic = min(heuristic, 0.40)

    # ── 백테스트 보정 블렌딩 ──
    band = count_band(count)
    calib = load_calibration()
    bucket = (calib.get("buckets") or {}).get(f"{match_level}|{band}")
    if bucket and bucket.get("n", 0) > 0:
        hit10 = float(bucket["hit10"])
        n = int(bucket["n"])
        w = n / (n + _BLEND_PRIOR)
        blended = hit10 * w + heuristic * (1 - w)
        final = max(SCORE_FLOOR, min(SCORE_CAP, blended))
        if is_fallback:
            final = min(final, 0.40)
        factors["calibration(hit10)"] = hit10
        factors["calibration_weight"] = round(w, 2)
        return {"score": round(final, 2), "basis": "calibrated",
                "match_level": match_level, "band": band, "factors": factors}

    return {"score": round(heuristic, 2), "basis": "heuristic",
            "match_level": match_level, "band": band, "factors": factors}


def confidence_label(score: float, basis: str = "heuristic") -> str:
    """리포트 표기용 라벨."""
    suffix = " · 백테스트 보정" if basis == "calibrated" else ""
    if score >= 0.80: return f"높음 ({score:.0%}){suffix}"
    if score >= 0.60: return f"보통 ({score:.0%}){suffix}"
    if score >= 0.40: return f"낮음 ({score:.0%}){suffix}"
    return f"매우 낮음 ({score:.0%}) — 참고용{suffix}"
