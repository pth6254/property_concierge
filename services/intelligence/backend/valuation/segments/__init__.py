"""AVM 세그먼트 등록표.

세그먼트 = 용도 × 거래 단위. 세그먼트마다 주된 평가 방법·검토용 방법·공개 상태를 한 곳에서 관리한다.
공개 상태는 각 세그먼트의 홀드아웃 검증을 통과해야 바뀐다. 거래가 부족하다고 다른 세그먼트의 모델·거래로 대체하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    id: str
    label: str
    subtypes: frozenset[str]
    unit: str                      # single_unit / whole_building / single_parcel
    primary_method: str
    check_methods: tuple[str, ...]
    status: str                    # active / withheld / scenario / public_reference / unsupported
    note: str


SEGMENTS: tuple[Segment, ...] = (
    Segment("R-APT", "아파트 (호)", frozenset({"apartment"}), "single_unit", "sales_comparison",
            ("official_price_ratio", "jeonse_ratio"), "active", "동일 단지 최근 6개월·면적 ±10% 5건 이상일 때만 산출"),
    Segment("R-RH", "연립·다세대 (호)", frozenset({"row_house"}), "single_unit", "sales_comparison",
            ("same_building_trades", "official_price_ratio"), "withheld", "근거 단계(L1~L3)별 홀드아웃 검증 전 보류"),
    Segment("R-OFF", "오피스텔 (호)", frozenset({"officetel"}), "single_unit", "sales_comparison",
            ("rental_income",), "withheld", "별도 모델·검증 전 보류"),
    Segment("R-DET", "단독·다가구 (토지+건물)", frozenset({"detached", "multi_household", "detached_unspecified"}), "whole_building",
            "land_plus_building_cost", ("bulk_sales_comparison",), "withheld", "거래가 적어 토지·건물 분리 계산 필요"),
    Segment("C-UNIT", "구분상가·사무실 (호)", frozenset({"commercial", "office"}), "single_unit", "income_scenario",
            ("sales_comparison",), "scenario", "현재는 입력 임대료·환원율 가정 시나리오"),
    Segment("C-BLDG", "상업·업무 건물 전체", frozenset({"commercial", "office"}), "whole_building", "income_scenario",
            ("sales_comparison",), "scenario", "입력 임대료·운영비·환원율 가정 시나리오"),
    Segment("L-LAND", "토지 (필지)", frozenset({"land"}), "single_parcel", "land_public_data",
            (), "public_reference", "공개자료 참고, 시장가격 미산출"),
    Segment("I-IND", "공장·창고", frozenset({"factory", "warehouse"}), "whole_building", "unsupported",
            (), "unsupported", "고도화 보류(사용자 결정)"),
)


def resolve(subtype: str, scope: str | None = None) -> Segment | None:
    """세부 유형과 평가 범위로 세그먼트를 찾는다. 같은 유형이 범위로 나뉘면(상가 호/건물) 범위가 맞는 것을 고른다."""
    candidates = [segment for segment in SEGMENTS if subtype in segment.subtypes]
    for segment in candidates:
        if scope and segment.unit == scope:
            return segment
    return candidates[0] if candidates else None
