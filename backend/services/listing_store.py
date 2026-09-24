"""사용자 제공 매물의 CSV 검증과 저장. 외부 사이트에는 접근하지 않는다."""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text

from db.base import session_scope
from db.models import ImportedListing, LegalRegion, ListingRevision, ListingObservation
from schemas.listing_import import ListingInput

STALE_SECONDS = 7 * 86400


def _view(row, session):
    observation = None
    first_seen = last_seen = None
    from backend.services.naver_listing_collector import canonical_url
    try:
        _, article = canonical_url(row.payload.get("source_url") or "")
        filters = [ListingObservation.user_id == row.user_id, ListingObservation.external_id == article]
        observation = session.scalar(select(ListingObservation).where(*filters).order_by(ListingObservation.fetched_at.desc()).limit(1))
        first_seen, last_seen = session.execute(select(func.min(ListingObservation.fetched_at), func.max(ListingObservation.fetched_at)).where(*filters, ListingObservation.outcome == "observed")).one()
    except ValueError:
        pass
    return {**row.payload, "id": row.id, "source_name": row.source_name,
            "needs_confirmation": row.confirmed_at < time.time() - STALE_SECONDS or bool(observation and observation.fetched_at > row.confirmed_at),
            "first_seen_at": first_seen, "last_seen_at": last_seen,
            "last_collection_at": observation.fetched_at if observation else None,
            "last_collection_outcome": observation.outcome if observation else None,
            "region_linked": bool(row.legal_region_code)}


def import_csv(user_id, source_name, csv_text, *, commit=False):
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
    with session_scope() as session:
        regions = session.scalars(select(LegalRegion).where(LegalRegion.is_active.is_(True), LegalRegion.level == "eup_myeon_dong")).all()
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
                    if item.external_id in seen:
                        raise ValueError("CSV 안에서 external_id가 중복됩니다")
                    seen.add(item.external_id)
                    address = " ".join(item.address.split())
                    if address.startswith("서울 "):
                        address = "서울특별시 " + address[3:]
                    region = by_code.get(item.legal_region_code) if item.legal_region_code else next((r for r in by_name if address == r.full_name or address.startswith(r.full_name + " ")), None)
                    if item.legal_region_code and not region:
                        raise ValueError("유효한 법정 읍·면·동 코드가 아닙니다")
                    if region and not (address == region.full_name or address.startswith(region.full_name + " ")):
                        raise ValueError("법정동 코드와 주소가 일치하지 않습니다. 법정동 주소를 확인해주세요")
                    item.legal_region_code = region.code if region else None
                    if not region:
                        warnings.append({"row": index, "message": "법정동 미연결: 저장은 가능하지만 지역 검색·후보 저장에서 제외됩니다"})
                    rows.append((index, item))
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
                  "total": len(rows) + len(errors), "preview": [item.model_dump(mode="json") for _, item in rows[:20]],
                  "created": 0, "updated": 0, "unchanged": 0, "skipped_older": 0, "committed": False}
        if errors or not commit:
            return output
        # 같은 사용자·출처의 동시 업로드를 직렬화해 유일성 제약 경합을 방지한다.
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"listing-import:{user_id}:{source_name}"})
        for index, item in rows:
            existing = session.scalar(select(ImportedListing).where(ImportedListing.user_id == user_id,
                ImportedListing.source_name == source_name, ImportedListing.external_id == item.external_id))
            payload = item.model_dump(mode="json")
            confirmed = item.confirmed_at.timestamp()
            if existing and confirmed < existing.confirmed_at:
                output["skipped_older"] += 1
                continue
            if existing and payload == existing.payload:
                output["unchanged"] += 1
                continue
            if existing and confirmed == existing.confirmed_at:
                # 같은 확인 시각의 상충 자료는 임의로 선택하지 않고 전체를 롤백한다.
                raise HTTPException(409, f"{index}행: 같은 확인 시각의 내용이 다릅니다. 정확한 확인 시각을 입력해주세요")
            row = existing or ImportedListing(user_id=user_id, source_name=source_name, external_id=item.external_id)
            row.legal_region_code = item.legal_region_code
            row.property_type = item.property_type
            row.transaction_type = item.transaction_type
            row.status = item.status
            row.price = item.asking_price if item.transaction_type == "purchase" else item.deposit
            row.area_sqm = item.area_sqm
            row.confirmed_at = confirmed
            row.payload = payload
            session.add(row)
            session.flush()
            session.add(ListingRevision(listing_id=row.id, imported_at=time.time(), payload=payload))
            output["updated" if existing else "created"] += 1
        output["committed"] = True
        return output


def search_listings(user_id, *, region_code=None, property_type=None, transaction_type=None,
                    budget_max=None, area_min=None, status=None, fresh_only=False, page=1, page_size=20):
    with session_scope() as session:
        filters = [ImportedListing.user_id == user_id]
        if region_code:
            region = session.get(LegalRegion, region_code)
            if not region or not region.is_active:
                raise HTTPException(404, "선택한 지역을 찾을 수 없습니다")
            length = {"sido": 2, "sigungu": 5, "eup_myeon_dong": 10}.get(region.level)
            if not length:
                raise HTTPException(422, "시·도, 시·군·구, 읍·면·동을 선택해주세요")
            filters.append(ImportedListing.legal_region_code.startswith(region.code[:length]))
        if property_type:
            filters.append(ImportedListing.property_type == property_type)
        if transaction_type:
            filters.append(ImportedListing.transaction_type == transaction_type)
        if budget_max is not None:
            filters.append(ImportedListing.price <= budget_max)
        if area_min is not None:
            filters.append(ImportedListing.area_sqm >= area_min)
        if status:
            filters.append(ImportedListing.status == status)
        if fresh_only:
            filters.extend([ImportedListing.confirmed_at >= time.time() - STALE_SECONDS, ImportedListing.status == "active"])
            # 원문 재조회 결과를 아직 검토하지 않은 자료는 최신 추천에서 제외한다.
            source_url = ImportedListing.payload["source_url"].as_string()
            source_article = func.coalesce(func.substring(source_url, r"/articles/([0-9]+)"), func.substring(source_url, r"[?&]articleNo=([0-9]+)"))
            filters.append(~select(ListingObservation.id).where(
                ListingObservation.user_id == user_id,
                ListingObservation.external_id == source_article,
                source_url.op("~")(r"^https://(land|new.land|fin.land|m.land)\.naver\.com/"),
                ListingObservation.fetched_at > ImportedListing.confirmed_at,
            ).exists())
        count = session.scalar(select(func.count()).select_from(ImportedListing).where(*filters))
        rows = session.scalars(select(ImportedListing).where(*filters).order_by(ImportedListing.confirmed_at.desc(), ImportedListing.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
        return {"items": [_view(row, session) for row in rows], "total": count, "page": page, "page_size": page_size}


def get_listing(user_id, listing_id):
    with session_scope() as session:
        row = session.scalar(select(ImportedListing).where(ImportedListing.id == listing_id, ImportedListing.user_id == user_id))
        if not row:
            raise HTTPException(404, "매물을 찾을 수 없습니다")
        return _view(row, session)


def listing_history(user_id, listing_id):
    get_listing(user_id, listing_id)
    with session_scope() as session:
        rows = session.execute(select(ListingRevision).join(ImportedListing).where(
            ImportedListing.user_id == user_id, ImportedListing.id == listing_id
        ).order_by(ListingRevision.id.desc()).limit(100)).scalars().all()
        return {"items": [{"imported_at": datetime.fromtimestamp(row.imported_at, timezone.utc).isoformat(), **row.payload} for row in rows]}
