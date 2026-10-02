"""listings 내부 계약 클라이언트. 저장·권한·트랜잭션은 Kotlin에서 처리한다."""
from __future__ import annotations

from typing import Optional
from api.core_bridge import core_store
import csv
import io
from fastapi import HTTPException
from pydantic import ValidationError
from schemas.listing_import import ListingInput


@core_store("listings")
def import_csv(user_id, source_name, csv_text, *, commit=False):
    ...

@core_store("listings")
def search_listings(user_id, *, region_code=None, property_type=None, transaction_type=None,
                    budget_max=None, area_min=None, status=None, fresh_only=False, page=1, page_size=20):
    ...

@core_store("listings")
def get_listing(user_id, listing_id):
    ...

@core_store("listings")
def listing_history(user_id, listing_id):
    ...


def validate_csv(user_id, source_name, csv_text, regions):
    """행 오류가 있으면 전체를 저장하지 않고 오래된 자료로 최신 상태를 덮어쓰지 않는다."""
    if "\x00" in csv_text:
        raise HTTPException(422, "CSV에 허용되지 않는 제어 문자가 있습니다")
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")), strict=True)
    fields = set(ListingInput.model_fields)
    required = {key for key, field in ListingInput.model_fields.items() if field.is_required()}
    try:
        header = reader.fieldnames or []
    except csv.Error:
        raise HTTPException(422, "CSV 헤더 형식을 확인해주세요") from None
    if len(header) != len(set(header)) or not required.issubset(header) or set(header) - fields:
        raise HTTPException(422, "CSV 헤더가 맞지 않습니다. 템플릿의 필수 열과 열 이름을 확인해주세요.")
    rows, errors, warnings, seen = [], [], [], set()
    by_code = {r.code: r for r in regions}
    by_name = sorted(regions, key=lambda r: len(r.full_name), reverse=True)
    try:
        for index, raw in enumerate(reader, 2):
            if index > 1001:
                raise HTTPException(422, "한 번에 최대 1,000개 매물만 수입할 수 있습니다")
            try:
                if None in raw or any(value is None for value in raw.values()):
                    raise ValueError("열 개수가 헤더와 다릅니다")
                item = ListingInput.model_validate({key: value for key, value in raw.items() if value.strip()})
                address_details = None
                if item.address_token:
                    from api.core_bridge import request_core
                    from schemas.listing_address import ListingAddress
                    proof = request_core("/internal/v1/addresses/verify", {"token": item.address_token, "user_id": user_id})
                    if proof.status_code == 422:
                        raise ValueError("주소 확인 정보가 유효하지 않거나 만료되었습니다. 주소를 다시 검색·선택해주세요.")
                    if proof.status_code != 200:
                        raise HTTPException(503, "주소 확인 서비스에 연결하지 못했습니다")
                    verified = ListingAddress.model_validate(proof.json())
                    if item.address not in (verified.jibun_address, verified.road_address):
                        raise ValueError("선택한 주소와 입력 주소가 다릅니다. 주소를 다시 선택해주세요.")
                    expected_name = verified.building_name or verified.jibun_address[:150]
                    if item.name != expected_name:
                        raise ValueError("선택한 주소의 이름과 입력 이름이 다릅니다. 사용자 이름은 별칭에 입력해주세요.")
                    item.legal_region_code = verified.legal_region_code
                    item.address = verified.jibun_address
                    address_details = verified.model_dump()
                if item.building_token:
                    if not item.address_token or address_details is None:
                        raise ValueError("건축물대장 확인 정보에는 선택한 주소 확인 정보가 필요합니다")
                    from api.core_bridge import request_core
                    evidence = request_core("/internal/v1/buildings/verify", {
                        "token": item.building_token, "user_id": user_id, "address_token": item.address_token,
                        "building_dong": item.building_dong, "unit_number": item.unit_number,
                        "area_sqm": item.area_sqm, "area_basis": item.area_basis, "floor": item.floor,
                    })
                    if evidence.status_code == 422:
                        raise ValueError("건축물대장 확인 정보가 만료되었거나 주소·동·호가 바뀌었습니다. 다시 조회해주세요.")
                    if evidence.status_code != 200:
                        raise HTTPException(503, "건축물대장 확인 서비스에 연결하지 못했습니다")
                    # 사용자 면적은 덮어쓰지 않는다. 공식 조회값과의 일치 여부만 저장한다.
                    address_details["building_register"] = evidence.json()
                if item.external_id in seen:
                    raise ValueError("CSV 안에서 external_id가 중복됩니다")
                seen.add(item.external_id)
                address = " ".join(item.address.split())
                if address.startswith("서울 "):
                    address = "서울특별시 " + address[3:]
                region = by_code.get(item.legal_region_code) if item.legal_region_code else next((r for r in by_name if address == r.full_name or address.startswith(r.full_name + " ")), None)
                if item.legal_region_code and not region:
                    raise ValueError("유효한 법정 읍·면·동 코드가 아닙니다")
                if address_details and region:
                    parts, full = address.split(), region.full_name.split()
                    aliases = {"11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
                               "30": "대전", "31": "울산", "36": "세종", "41": "경기", "42": "강원",
                               "43": "충북", "44": "충남", "45": "전북", "46": "전남", "47": "경북",
                               "48": "경남", "50": "제주", "51": "강원", "52": "전북"}
                    if parts[0] not in (full[0], aliases.get(region.code[:2])) or parts[1:len(full)] != full[1:]:
                        raise ValueError("주소 검색 결과와 법정동 기준정보가 일치하지 않습니다. 주소를 다시 확인해주세요.")
                    address = " ".join(full + parts[len(full):])
                    item.address = address
                    address_details["jibun_address"] = address
                    if address_details["road_address"]:
                        address_details["road_address"] = full[0] + " " + address_details["road_address"].split(" ", 1)[-1]
                    if not address_details["building_name"]:
                        item.name = address[:150]
                if region and not (address == region.full_name or address.startswith(region.full_name + " ")):
                    raise ValueError("법정동 코드와 주소가 일치하지 않습니다. 법정동 주소를 확인해주세요")
                item.legal_region_code = region.code if region else None
                if not region:
                    warnings.append({"row": index, "message": "법정동 미연결: 저장은 가능하지만 지역 검색·후보 저장에서 제외됩니다"})
                rows.append((index, item, address_details))
            except (ValidationError, ValueError) as exc:
                if isinstance(exc, ValidationError):
                    message = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False))
                else:
                    message = str(exc)
                errors.append({"row": index, "message": message})
    except csv.Error:
        raise HTTPException(422, "CSV 형식 또는 필드 길이를 확인해주세요") from None
    if not rows and not errors:
        raise HTTPException(422, "CSV에 매물 행이 없습니다")
    output = {"valid": not errors, "errors": errors, "warnings": warnings,
              "total": len(rows) + len(errors), "preview": [item.model_dump(mode="json") | {"identity": item.identity_details()} |
                ({"address_details": details} if details else {}) for _, item, details in rows[:20]],
              "created": 0, "updated": 0, "unchanged": 0, "skipped_older": 0, "committed": False}
    return output, rows
