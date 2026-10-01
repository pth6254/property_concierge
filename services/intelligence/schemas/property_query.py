"""
property_query.py — 부동산 의사결정 요청 스키마

금액 단위: 원 (int)
면적 단위: m² (float)
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class PropertyQuery(BaseModel):
    # 요청 의도
    intent: Literal[
        "price_analysis",   # 가격 분석
        "buy_decision",     # 매수 판단
        "sell_decision",    # 매도 판단
        "recommendation",   # 매물 추천
        "comparison",       # 매물 비교
        "simulation",       # 대출/수익률 시뮬레이션
    ]

    # 물건 정보
    property_type: Optional[str]   = None   # 주거용 / 상업용 / 업무용 / 산업용 / 토지
    region: Optional[str]          = None   # 시·군·구 단위 (예: 마포구)
    address: Optional[str]         = None   # 도로명 또는 지번 주소
    complex_name: Optional[str]    = None   # 단지명·건물명 (예: 마포래미안푸르지오)
    area_m2: Optional[float]       = None   # 전용면적 m²

    # 가격 정보 (원 단위)
    asking_price: Optional[int]    = None   # 호가 또는 매도 희망가 (원)

    # 사용 목적
    purpose: Optional[Literal[
        "live",             # 실거주
        "investment",       # 투자
        "sell",             # 매도
        "hold",             # 보유
    ]] = None

    # 예산 범위 (원 단위)
    budget_min: Optional[int]      = None   # 최소 예산 (원)
    budget_max: Optional[int]      = None   # 최대 예산 (원)

    # 감정평가 기준시점 YYYYMMDD (빈 문자열이면 현재 시점)
    appraisal_date: str             = ""

    # 감정평가 목적
    appraisal_purpose: Optional[Literal[
        "담보",   # 담보 감정
        "경매",   # 경매
        "과세",   # 과세
        "매매",   # 매매 참고
        "보상",   # 보상
        "임의",   # 임의
    ]] = None

    # 원문 입력 (NLP 파싱 전 사용자 입력 보존)
    raw_input: Optional[str]       = None
