"""주소 기준정보와 별칭을 유지하고 조회 실패 시 이전 근거를 보존한다."""
import time
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from db.base import session_scope
from db.models import ComplexCatalog


def lookup(region: str, lawd_code: str, dong: str, name: str, *, force=False) -> dict:
    from services.complex_address_service import _name, resolve_complex_address
    identity = dict(lawd_code=lawd_code, dong=dong, canonical_name=_name(name))
    with session_scope() as session:
        row = session.scalar(select(ComplexCatalog).filter_by(**identity))
        if row and not force and time.time() - row.checked_at < (604800 if row.status == "matched" else 3600):
            if name not in row.aliases:
                row.aliases = [*row.aliases, name]
            return {**row.address, "complex_id": row.id}
    result = resolve_complex_address(region, lawd_code, dong, name, force=force)
    with session_scope() as session:
        session.execute(insert(ComplexCatalog).values(**identity, name=name, region=region,
            aliases=[name], address=result, status=result["address_status"], checked_at=time.time())
            .on_conflict_do_nothing(index_elements=["lawd_code", "dong", "canonical_name"]))
        row = session.scalar(select(ComplexCatalog).filter_by(**identity).with_for_update())
        row.aliases = list(dict.fromkeys([*row.aliases, name, result.get("matched_name") or name]))
        if result["address_status"] == "unavailable" and row.address.get("jibun_address"):
            # 이전 주소는 운영자가 확인할 근거로 남기고 최신 일치로 표시하지 않는다.
            row.address = {**row.address, "address_status": "unavailable"}
        else:
            row.address = result
        row.status = result["address_status"]
        row.checked_at = time.time()
        return {**row.address, "complex_id": row.id}


def refresh(catalog_id: int) -> dict:
    with session_scope() as session:
        row = session.get(ComplexCatalog, catalog_id)
        if not row:
            raise ValueError("단지 기준정보가 없습니다")
        params = (row.region, row.lawd_code, row.dong, row.name)
    return lookup(*params, force=True)
