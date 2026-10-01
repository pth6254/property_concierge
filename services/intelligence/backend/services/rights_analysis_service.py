"""
rights_analysis_service.py — 등기부등본·건축물대장 PDF 권리관계 위험 점검

사용자가 업로드한 PDF(인터넷등기소 등기사항전부증명서, 정부24 건축물대장)를
파싱해 권리관계 위험 신호를 결정론적 규칙으로 점검한다.

⚖️ 포지셔닝: 법률사무(권리분석)가 아닌 "위험 신호 점검 (참고용)".
   결과에 법적 판단이 아님을 고지한다.

분석 흐름:
  1. PDF 텍스트 추출 (pypdf — 등기부 PDF는 텍스트 레이어 보유)
  2. 규칙 기반 파싱: 갑구(소유권) 위험 등기 / 을구(근저당·전세권) 금액
  3. 위험 체크리스트 + 보증금 안전성 (선순위 채권 + 보증금 vs 시세)
  4. 시세는 사용자 입력 또는 AVM 추정치 연동

한계 (결과에 명시):
  - 텍스트 추출 기반이라 말소(취소선) 등기를 구분하지 못할 수 있음
    → '주요 등기사항 요약' 섹션이 있으면 그것을 우선 사용 (유효 등기만 수록)
  - 스캔 이미지 PDF는 분석 불가 (텍스트 레이어 필요)
"""

from __future__ import annotations

import io
import re

# ─────────────────────────────────────────
#  위험 등기 키워드 (갑구·을구)
# ─────────────────────────────────────────

CRITICAL_KEYWORDS = {
    "경매개시결정": "경매가 진행 중인 물건입니다. 계약 시 보증금 회수가 매우 어렵습니다.",
    "임의경매":     "근저당권자가 경매를 신청한 이력이 있습니다.",
    "강제경매":     "채권자가 강제경매를 신청한 이력이 있습니다.",
    "압류":         "국세·지방세 체납 등으로 압류된 상태일 수 있습니다. 조세채권은 임차보증금보다 우선할 수 있습니다.",
    "가압류":       "채권 분쟁으로 가압류가 설정돼 있습니다. 소유자의 재정 상태에 문제가 있을 수 있습니다.",
    "가처분":       "소유권 분쟁 중일 수 있습니다. 처분금지가처분이 있으면 계약 자체가 위험합니다.",
    "예고등기":     "등기 원인의 무효·취소 소송이 진행 중입니다.",
    "신탁":         "신탁된 부동산입니다. 수탁자(신탁사) 동의 없는 계약은 무효가 될 수 있습니다.",
    "환매특약":     "환매특약이 있어 소유권이 되돌아갈 수 있습니다.",
}

WARNING_KEYWORDS = {
    "임차권등기명령": "이전 임차인이 보증금을 못 받아 임차권등기를 한 이력이 있습니다.",
    "가등기":         "소유권이전 가등기가 있으면 본등기 시 후순위 권리가 소멸될 수 있습니다.",
}

# 소액임차인 최우선변제 (주택임대차보호법 시행령 — 2023.2.21 이후 기준)
# (지역, 소액보증금 상한, 최우선변제액)
SMALL_TENANT_PROTECTION = [
    ("서울특별시",                          165_000_000, 55_000_000),
    ("과밀억제권역·세종·용인·화성·김포",     145_000_000, 48_000_000),
    ("광역시·안산·광주·파주·이천·평택",      85_000_000,  28_000_000),
    ("그 밖의 지역",                        75_000_000,  25_000_000),
]

_MONEY = r"금\s*([\d,]+)\s*원"


# ─────────────────────────────────────────
#  PDF → 텍스트
# ─────────────────────────────────────────

def extract_pdf_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ─────────────────────────────────────────
#  등기부등본 파싱
# ─────────────────────────────────────────

def parse_registry(text: str) -> dict:
    """
    등기부등본 텍스트 → 구조화.
    '주요 등기사항 요약' 섹션이 있으면 위험 판정에 그것을 우선 사용
    (요약에는 유효한 등기만 수록 — 말소 등기 오탐 방지).
    """
    if not text or len(text.strip()) < 50:
        return {"error": "텍스트를 추출할 수 없습니다. 스캔 이미지 PDF는 분석할 수 없으며, "
                         "인터넷등기소에서 발급한 원본 PDF가 필요합니다."}

    # 주소 (헤더: [집합건물] 서울특별시 ... / [건물] ... / [토지] ...)
    m = re.search(r"\[(?:집합건물|건물|토지)\]\s*([^\n]+)", text)
    address = m.group(1).strip() if m else ""

    # 요약 섹션 분리
    summary_idx = text.find("주요 등기사항 요약")
    scan_text   = text[summary_idx:] if summary_idx >= 0 else text
    has_summary = summary_idx >= 0

    # 소유자 (요약부 '소유지분현황' 또는 갑구 최후 소유권이전)
    owners = re.findall(r"(?:소유자|공유자)\s+([가-힣]{2,10})\s", scan_text)
    owner  = owners[-1] if owners else ""

    # 위험 등기 검출
    critical, warnings = [], []
    for kw, desc in CRITICAL_KEYWORDS.items():
        if kw in scan_text:
            critical.append({"keyword": kw, "description": desc})
    for kw, desc in WARNING_KEYWORDS.items():
        if kw in scan_text:
            warnings.append({"keyword": kw, "description": desc})

    # 근저당권 채권최고액 합산
    mortgage_amounts = []
    for m in re.finditer(r"채권최고액\s*" + _MONEY, scan_text):
        mortgage_amounts.append(int(m.group(1).replace(",", "")))

    # 전세권·임차권 보증금
    seonse_amounts = []
    for m in re.finditer(r"전세금\s*" + _MONEY, scan_text):
        seonse_amounts.append(int(m.group(1).replace(",", "")))
    for m in re.finditer(r"임차보증금\s*" + _MONEY, scan_text):
        seonse_amounts.append(int(m.group(1).replace(",", "")))

    return {
        "error":            "",
        "address":          address,
        "owner":            owner,
        "has_summary":      has_summary,
        "critical":         critical,
        "warnings":         warnings,
        "mortgage_total":   sum(mortgage_amounts),
        "mortgage_count":   len(mortgage_amounts),
        "senior_deposits":  sum(seonse_amounts),
        "senior_count":     len(seonse_amounts),
    }


# ─────────────────────────────────────────
#  건축물대장 파싱
# ─────────────────────────────────────────

def parse_building_ledger(text: str) -> dict:
    """건축물대장 텍스트 → 위반건축물·용도·사용승인일."""
    if not text or len(text.strip()) < 50:
        return {"error": "텍스트를 추출할 수 없습니다 (스캔 이미지 PDF 분석 불가)."}

    violation = "위반건축물" in text

    m = re.search(r"주\s*용\s*도\s*[:\s]*([가-힣\s()·,0-9]+?)(?:\n|호수|세대)", text)
    main_use = m.group(1).strip()[:30] if m else ""

    m = re.search(r"사용승인일[:\s]*([\d.\-/년월일\s]+)", text)
    approval = m.group(1).strip()[:15] if m else ""

    return {"error": "", "violation": violation, "main_use": main_use,
            "approval_date": approval}


# ─────────────────────────────────────────
#  보증금 안전성 판정
# ─────────────────────────────────────────

def _small_tenant_rule(address: str) -> tuple[str, int, int]:
    if "서울" in address:
        return SMALL_TENANT_PROTECTION[0]
    for region_kw in ("인천", "부산", "대구", "광주", "대전", "울산"):
        if region_kw in address:
            return SMALL_TENANT_PROTECTION[2]
    return SMALL_TENANT_PROTECTION[3]


def assess_deposit_safety(
    market_price: int,
    mortgage_total: int,
    senior_deposits: int,
    my_deposit: int,
    address: str = "",
) -> dict:
    """
    보증금 안전성 = (선순위 채권 + 내 보증금) / 시세.
      < 60%  : 안전
      60~80% : 주의
      > 80%  : 위험 (깡통전세 가능성 — 경매 시 배당 부족 우려)
    """
    if market_price <= 0:
        return {"available": False}

    senior_total = mortgage_total + senior_deposits
    burden       = senior_total + my_deposit
    ratio        = burden / market_price

    if ratio > 0.80:  grade, label = "danger",  "위험"
    elif ratio > 0.60: grade, label = "caution", "주의"
    else:             grade, label = "safe",    "안전"

    # 경매 낙찰가율 보수 가정 (아파트 평균 ~80%) 배당 시뮬레이션
    expected_auction = round(market_price * 0.80)
    recovery = max(0, min(my_deposit, expected_auction - senior_total))

    region, small_limit, priority_amount = _small_tenant_rule(address)
    small_tenant = my_deposit <= small_limit

    return {
        "available":        True,
        "senior_total":     senior_total,
        "total_burden":     burden,
        "burden_ratio":     round(ratio, 4),
        "grade":            grade,
        "label":            label,
        "expected_auction": expected_auction,
        "expected_recovery": recovery,
        "recovery_shortfall": my_deposit - recovery,
        "small_tenant":     small_tenant,
        "small_tenant_rule": {"region": region, "limit": small_limit,
                              "priority_amount": priority_amount},
    }


# ─────────────────────────────────────────
#  통합 분석
# ─────────────────────────────────────────

def analyze_rights(
    registry_pdf: bytes | None = None,
    building_pdf: bytes | None = None,
    my_deposit: int = 0,
    market_price: int = 0,
) -> dict:
    """
    PDF 권리관계 위험 점검 통합 실행.

    market_price: 사용자 입력 시세 (원). 0이면 보증금 안전성 계산 생략
                  (프론트에서 AVM 추정치를 넣어 호출할 수 있음).
    """
    result: dict = {"error": "", "disclaimer": (
        "본 결과는 업로드된 문서의 텍스트를 자동 점검한 참고 자료이며, "
        "법률사무(권리분석)가 아닙니다. 말소된 등기가 포함될 수 있고 "
        "누락이 있을 수 있으므로 계약 전 반드시 공인중개사·법무사의 "
        "원본 등기부 확인을 거치시기 바랍니다."
    )}

    registry = None
    if registry_pdf:
        try:
            registry = parse_registry(extract_pdf_text(registry_pdf))
        except Exception as e:
            registry = {"error": f"등기부등본 파싱 실패: {e}"}
        result["registry"] = registry

    if building_pdf:
        try:
            result["building"] = parse_building_ledger(extract_pdf_text(building_pdf))
        except Exception as e:
            result["building"] = {"error": f"건축물대장 파싱 실패: {e}"}

    if not registry_pdf and not building_pdf:
        result["error"] = "분석할 PDF가 없습니다."
        return result

    # ── 종합 위험 등급 ──
    risk_score = 0
    reasons: list[str] = []

    if registry and not registry.get("error"):
        if registry["critical"]:
            risk_score += 60 + 10 * (len(registry["critical"]) - 1)
            reasons += [f"🔴 {c['keyword']}: {c['description']}" for c in registry["critical"]]
        if registry["warnings"]:
            risk_score += 15 * len(registry["warnings"])
            reasons += [f"🟡 {w['keyword']}: {w['description']}" for w in registry["warnings"]]
        if not registry["has_summary"]:
            reasons.append("🟡 '주요 등기사항 요약'이 없는 문서 — 말소 등기가 위험 신호로 오탐될 수 있습니다.")

        # 보증금 안전성
        if my_deposit > 0 and market_price > 0:
            safety = assess_deposit_safety(
                market_price, registry["mortgage_total"],
                registry["senior_deposits"], my_deposit, registry["address"],
            )
            result["deposit_safety"] = safety
            if safety["available"]:
                if safety["grade"] == "danger":
                    risk_score += 40
                    reasons.append(
                        f"🔴 선순위 채권+보증금이 시세의 {safety['burden_ratio']:.0%} — 깡통전세 위험. "
                        f"경매 시 예상 회수 부족액 약 {safety['recovery_shortfall']:,}원")
                elif safety["grade"] == "caution":
                    risk_score += 20
                    reasons.append(f"🟡 선순위 채권+보증금이 시세의 {safety['burden_ratio']:.0%} — 여유가 크지 않습니다.")
                else:
                    reasons.append(f"🟢 선순위 채권+보증금이 시세의 {safety['burden_ratio']:.0%} — 안전 범위.")

    if result.get("building") and not result["building"].get("error"):
        if result["building"]["violation"]:
            risk_score += 30
            reasons.append("🔴 위반건축물 — 전세대출·보증보험 가입이 거절될 수 있습니다.")

    risk_score = min(risk_score, 100)
    if risk_score >= 60:  overall = ("danger",  "고위험 — 계약 비추천")
    elif risk_score >= 30: overall = ("caution", "주의 — 전문가 확인 필수")
    elif reasons:         overall = ("safe",    "특이 위험 신호 없음")
    else:                 overall = ("safe",    "특이 위험 신호 없음")

    result["risk_score"]  = risk_score
    result["risk_grade"]  = overall[0]
    result["risk_label"]  = overall[1]
    result["reasons"]     = reasons
    return result
