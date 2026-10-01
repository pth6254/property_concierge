"""모델의 부분 조건을 검증한 뒤 기존 대화 조건에 병합한다."""
from __future__ import annotations

import re
from pydantic import ValidationError
from schemas.concierge import ConciergeCriteria, ConciergeExtraction

_ALIASES = {
    "transaction_type": {"매매": "purchase", "매수": "purchase", "월세": "rent", "전세": "lease"},
    "property_type": {"아파트": "apartment", "연립다세대": "row_house", "단독주택": "detached",
                      "오피스텔": "officetel", "토지": "land"},
    "purpose": {"실거주": "residence", "투자": "investment"},
}
_CLEAR_LABELS = {"budget_max_won": "예산", "area_min_sqm": "면적", "region_name": "지역",
                 "property_type": "부동산유형", "transaction_type": "거래유형", "purpose": "목적"}


def merge_extraction(extraction: ConciergeExtraction, previous: dict, message: str) -> tuple[ConciergeCriteria, list[str]]:
    merged = ConciergeCriteria.model_validate(previous).model_dump()
    issues = []
    updates = {}
    for field, value in extraction.criteria.items():
        if field not in ConciergeCriteria.model_fields:
            issues.append("criteria")
            continue
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            value = _ALIASES.get(field, {}).get(value, value)
        try:
            if value == "":
                raise ValueError("빈 조건")
            updates[field] = getattr(ConciergeCriteria.model_validate({field: value}, strict=True), field)
        except (ValidationError, ValueError):
            issues.append(field)

    # null과 삭제를 구분한다. 모델이 임의로 clear_fields를 만들더라도 조건을 지울 수 없다.
    command = re.sub(r"\s+", "", message).rstrip(".!?")
    confirmed = {field for field, label in _CLEAR_LABELS.items()
                 if re.fullmatch(label + r"(?:조건|제한)?(?:을|를)?(?:없애줘|지워줘|삭제해줘|해제해줘)", command)}
    for field in extraction.clear_fields:
        if field not in confirmed:
            issues.append(field if field in ConciergeCriteria.model_fields else "criteria")
    for field in confirmed:
        updates.pop(field, None)
        merged[field] = None
        if field == "region_name":
            updates.pop("region_code", None)
            merged["region_code"] = None

    # 지역명이 바뀌었는데 이전 지역 코드가 남으면 다른 지역을 조회하게 된다.
    if "region_name" in updates and updates["region_name"] != merged.get("region_name"):
        merged["region_code"] = None
    if "region_code" in updates and "region_name" not in updates and updates["region_code"] != merged.get("region_code"):
        merged["region_name"] = None
    if "region_name" in updates or "region_code" in updates:
        from backend.services.market_service import resolve_region_name
        from db.base import session_scope
        from db.models import LegalRegion
        code = updates.get("region_code")
        if code:
            with session_scope() as session:
                row = session.get(LegalRegion, code)
                valid_code = bool(row and row.is_active)
            if not valid_code:
                issues.append("region_code")
                updates.pop("region_code", None)
        if updates.get("region_name"):
            resolved = resolve_region_name(updates["region_name"])
            if resolved["status"] == "resolved":
                if code and code != resolved["code"]:
                    issues.append("region_code")
                updates["region_code"] = resolved["code"]
            else:
                updates.pop("region_code", None)
                merged["region_code"] = None
                if resolved["status"] == "not_found":
                    issues.append("region_name")
                    updates.pop("region_name", None)

    merged.update(updates)
    return ConciergeCriteria.model_validate(merged), list(dict.fromkeys(issues))
