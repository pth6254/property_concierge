"""컨시어지가 호출할 수 있는 도구의 명시적 허용 목록."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


from backend.services.market_service import get_region_market_summary, resolve_region_name
from schemas.concierge import ConciergeCriteria, ConciergeIntent, ConciergeToolResult
from backend.concierge.decision_tools import compare_properties, simulate_investment


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    intent: ConciergeIntent
    description: str
    enabled: bool
    handler: Callable[..., ConciergeToolResult] | None = None


def find_regions(criteria: ConciergeCriteria, user_id: int, candidate_context: dict | None = None) -> ConciergeToolResult:
    del user_id  # 조회 도구지만 모든 호출자가 같은 서명을 갖도록 유지한다.
    if not criteria.region_code and criteria.region_name:
        resolved = resolve_region_name(criteria.region_name)
        if resolved["status"] == "ambiguous":
            return ConciergeToolResult(
                tool="find_regions", status="needs_input",
                data={"region_candidates": resolved["candidates"]},
                missing_fields=["region_code"],
            )
        if resolved["status"] == "resolved":
            criteria.region_code = resolved["code"]

    missing = []
    if not criteria.region_code:
        missing.append("region")
    if not criteria.property_type:
        missing.append("property_type")
    if not criteria.transaction_type:
        missing.append("transaction_type")
    if missing:
        return ConciergeToolResult(
            tool="find_regions", status="needs_input", missing_fields=missing,
        )

    if criteria.transaction_type != "purchase":
        return ConciergeToolResult(tool="find_regions", status="not_available")
    summary = get_region_market_summary(
        region_code=criteria.region_code, property_type=criteria.property_type,
        months=12, budget_max_won=criteria.budget_max_won,
        group_level="eup_myeon_dong" if criteria.region_code[2:5] != "000" else "sigungu",
    )
    return ConciergeToolResult(
        tool="find_regions", status="completed",
        data={**summary, "items": summary.get("items", [])[:10]},
    )


def select_properties(criteria: ConciergeCriteria, user_id: int, candidate_context: dict | None = None) -> ConciergeToolResult:
    """실거래 단지 추천을 재사용하며 현재 판매 중인 매물로 표현하지 않는다."""
    from db.base import session_scope
    from db.models import LegalRegion
    from backend.services.complex_recommend_service import recommend_complexes

    def reply(answer, status="needs_input", missing=None, **data):
        return ConciergeToolResult(tool="select_properties", status=status,
            missing_fields=missing or [], data={"answer": answer, **data})

    if not criteria.region_code and criteria.region_name:
        resolved = resolve_region_name(criteria.region_name)
        if resolved["status"] == "resolved":
            criteria.region_code = resolved["code"]
        elif resolved["status"] == "ambiguous":
            names = ", ".join(r["full_name"] for r in resolved["candidates"])
            return reply(f"같은 이름의 지역이 여러 곳입니다. 구체적인 지역을 알려주세요: {names}", missing=["region_code"])
    if not criteria.region_code:
        return reply("단지를 추천할 시·군·구 또는 법정동을 알려주세요. 예: 강남구, 역삼동", missing=["region"])
    with session_scope() as session:
        region = session.get(LegalRegion, criteria.region_code)
        if not region or not region.is_active or region.level not in {"sigungu", "eup_myeon_dong"}:
            return reply("단지 추천은 시·군·구 또는 법정동을 지정해주세요. 예산 등 기존 조건은 유지됩니다.", missing=["region_code"])
        region_name = region.full_name
    missing = [key for key in ("property_type", "transaction_type") if not getattr(criteria, key)]
    if missing:
        return reply("추천할 부동산 유형과 거래 유형을 확인해주세요. 현재는 아파트 매매 실거래 기반 단지 추천을 제공합니다.", missing=missing)
    if criteria.property_type != "apartment" or criteria.transaction_type != "purchase":
        return reply("현재 단지 추천은 아파트 매매 실거래를 지원합니다. 다른 유형은 동네 탐색에서 지역 통계를 확인해주세요.", status="not_available")
    if criteria.budget_max_won is not None and criteria.budget_max_won < 10000:
        return reply("입력한 예산에 맞는 단지 후보가 없습니다. 예산을 조정해주세요.", status="completed", results=[])
    result = recommend_complexes(region_name, region_code=criteria.region_code,
        budget_max=(criteria.budget_max_won or 0) // 10000, months=12, limit=5,
        area_min_sqm=criteria.area_min_sqm or 0, strict_budget=True)
    if result.get("error"):
        return reply(result["error"] + "\n지역·예산·면적 조건을 조정해 주세요. 현재 판매 중인 매물 여부는 확인하지 않습니다.",
                     status="completed", results=[])
    lines = [f"{region_name}의 최근 12개월 매매 실거래 기반 아파트 단지 후보입니다."]
    for index, item in enumerate(result["results"], 1):
        lines.append(f"{index}. {item['complex_name']} ({item['dong']}) — 시점수정 평균 {item['avg_price']:,}만원, "
                     f"평균 면적 {item['avg_area_m2']}㎡, 거래 {item['deal_count']}건")
    lines.append("가격은 시점수정한 실거래 평균이며 개별 매물 호가가 아닙니다. 현재 매물 존재 여부는 별도 확인이 필요합니다.")
    lines.append("아래 단지 카드에서 검토할 주소·면적과 알고 있는 희망가를 확인한 뒤 후보로 저장할 수 있습니다.")
    return reply("\n\n".join(lines), status="completed", results=result["results"],
                 source="국토교통부 실거래가", months=12, region_name=region_name)


def search_imported_listings(criteria: ConciergeCriteria, user_id: int, candidate_context: dict | None = None) -> ConciergeToolResult:
    from backend.services.listing_store import search_listings
    if not criteria.transaction_type:
        return ConciergeToolResult(tool="search_listings", status="needs_input", missing_fields=["transaction_type"],
            data={"answer": "등록 매물의 거래 유형(매매·전세·월세)을 알려주세요. 본인이 업로드한 자료에서 검색합니다."})
    if criteria.region_name and not criteria.region_code:
        resolved = resolve_region_name(criteria.region_name)
        if resolved["status"] != "resolved":
            return ConciergeToolResult(tool="search_listings", status="needs_input", missing_fields=["region"], data={"answer": "구체적인 시·군·구 또는 법정동을 알려주세요."})
        criteria.region_code = resolved["code"]
    result = search_listings(user_id, region_code=criteria.region_code, property_type=criteria.property_type,
        transaction_type=criteria.transaction_type, budget_max=criteria.budget_max_won,
        area_min=criteria.area_min_sqm, fresh_only=True, page_size=5)
    lines = ["본인이 등록한 자료 중 최근 7일 이내에 거래 가능으로 확인된 매물을 조회했습니다."]
    for item in result["items"]:
        price = f"희망가 {item['asking_price']:,}원" if item["transaction_type"] == "purchase" else f"보증금 {item['deposit']:,}원" + (f", 월세 {item['monthly_rent']:,}원" if item["monthly_rent"] else "")
        lines.append(f"• {item['name']} / {item['address']} / {item['area_sqm']}㎡ / {price} / 출처 {item['source_name']} / 확인 {item['confirmed_at']}")
    if not result["items"]:
        lines.append("조건에 맞는 등록 매물이 없습니다. 매물 보관함에서 자료를 업로드하거나 확인일·상태를 갱신해주세요.")
    if criteria.transaction_type == "rent" and criteria.budget_max_won is not None:
        lines.append("이번 예산 상한은 보증금에 적용했습니다. 월세 상한은 별도로 적용하지 않았습니다.")
    lines.append("외부 포털의 실시간 매물 조회가 아니며 매물 존재 여부는 출처에서 다시 확인해주세요.")
    return ConciergeToolResult(tool="search_listings", status="completed", data={"answer": "\n".join(lines), "result_url": "/listings"})


def appraise_property(criteria: ConciergeCriteria, user_id: int, candidate_context: dict | None = None) -> ConciergeToolResult:
    from api.candidate_appraisal import start_candidate_appraisal
    if not candidate_context or not candidate_context.get("candidate_id"):
        return ConciergeToolResult(tool="appraise_property", status="needs_input", missing_fields=["candidate"])
    data = start_candidate_appraisal(user_id, candidate_context["case_id"], candidate_context["candidate_id"])
    return ConciergeToolResult(tool="appraise_property", status="needs_input" if data.get("missing_fields") else "queued",
                               data=data, missing_fields=data.get("missing_fields", []))


def answer_tax_legal(criteria: ConciergeCriteria, user_id: int, candidate_context: dict | None = None, *, message: str, history: list | None = None) -> ConciergeToolResult:
    from backend.services.chat_service import answer_question
    return ConciergeToolResult(tool="answer_tax_legal", status="completed", data=answer_question(message, history=history))


def general_help(criteria: ConciergeCriteria, user_id: int, candidate_context: dict | None = None) -> ConciergeToolResult:
    return ConciergeToolResult(tool="general_help", status="completed", data={"answer":
        "실거래 기반 동네 추천과 선택한 후보의 AVM 시세추정을 도와드립니다. "
        "동네 추천은 희망 지역·부동산 유형·거래 유형을 알려주세요. "
        "AVM은 케이스와 후보를 선택한 뒤 요청할 수 있습니다. "
        "법률·세금 질문, 후보 자금 계산과 케이스의 후보 비교도 여기에서 요청할 수 있습니다."})


TOOL_REGISTRY: dict[ConciergeIntent, ToolDefinition] = {
    ConciergeIntent.SEARCH_LISTING: ToolDefinition("search_listings", ConciergeIntent.SEARCH_LISTING,
        "본인이 등록한 매물 검색", True, search_imported_listings),
    ConciergeIntent.FIND_REGION: ToolDefinition(
        name="find_regions", intent=ConciergeIntent.FIND_REGION,
        description="실거래 기반 시·군·구 및 법정동 비교", enabled=True, handler=find_regions,
    ),
    ConciergeIntent.SELECT_PROPERTY: ToolDefinition(
        "select_properties", ConciergeIntent.SELECT_PROPERTY, "실거래 기반 아파트 단지 추천", True, select_properties,
    ),
    ConciergeIntent.APPRAISE: ToolDefinition(
        "appraise_property", ConciergeIntent.APPRAISE, "AVM 기반 가격 추정", True, appraise_property,
    ),
    ConciergeIntent.COMPARE: ToolDefinition(
        "compare_properties", ConciergeIntent.COMPARE, "후보 부동산 비교", True, compare_properties,
    ),
    ConciergeIntent.SIMULATE: ToolDefinition(
        "simulate_investment", ConciergeIntent.SIMULATE, "자금·투자 시나리오 계산", True, simulate_investment,
    ),
    ConciergeIntent.RIGHTS_CHECK: ToolDefinition(
        "check_rights", ConciergeIntent.RIGHTS_CHECK, "권리관계 점검", False,
    ),
    ConciergeIntent.TAX_LEGAL: ToolDefinition(
        "answer_tax_legal", ConciergeIntent.TAX_LEGAL, "부동산 세금·법률 정보 안내", True, answer_tax_legal,
    ),
    ConciergeIntent.GENERAL: ToolDefinition(
        "general_help", ConciergeIntent.GENERAL, "컨시어지 사용 안내", True, general_help,
    ),
}


def execute_tool(intent: ConciergeIntent, criteria: ConciergeCriteria, user_id: int, candidate_context: dict | None = None, *, message: str = "", funding: dict | None = None, history: list | None = None) -> ConciergeToolResult:
    definition = TOOL_REGISTRY[intent]
    if not definition.enabled or definition.handler is None:
        return ConciergeToolResult(
            tool=definition.name, status="not_available",
            data={"description": definition.description},
        )
    if intent == ConciergeIntent.TAX_LEGAL:
        return definition.handler(criteria, user_id, candidate_context, message=message, history=history)
    if intent == ConciergeIntent.SIMULATE:
        return definition.handler(criteria, user_id, candidate_context, funding=funding)
    return definition.handler(criteria, user_id, candidate_context)
