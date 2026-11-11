"""변화 알림함의 조건을 저장된 자료에서 계산한다. 저장·외부 API·LLM·작업 실행은 하지 않는다.

Spring이 소유자를 확인한 케이스 스냅샷(보관하지 않은 케이스만)과 재확인이 필요한 매물 목록을 넘기면
현재 성립하는 알림 조건을 돌려준다. 저장·읽음·해결 처리는 Spring(NotificationStore)이 한다.

- 같은 조건은 같은 (kind, subject_key, fingerprint)를 만든다. 조건이 바뀌면 fingerprint가 바뀌어 새 알림이 된다.
- 판단 기준은 기존 화면과 같다. 분석 유효기간은 case_snapshot_presentation(analysis_freshness), 원본 변경은
  CaseStore.sourceStatus, 매물 7일 재확인은 ListingService.needs_confirmation, 실거래 연결은 listing_trade_overlay.find_trades다.
- 새 실거래는 서비스가 처음 수집한 시각(transactions.first_seen_at)으로 고른다. 기록 시작 전 거래(NULL)는 새 거래로 보지 않는다.
- 알림 문구는 확인할 사실과 다음 행동만 적는다. 거래 안전·가격 적정성을 판단하지 않는다.
"""
from __future__ import annotations

from datetime import datetime

from backend.services.case_snapshot_presentation import decorate_stored_snapshot

ANALYSIS_LABELS = {"appraisal": "시세", "simulation": "자금", "rights": "권리"}
VALID_DAYS = {"appraisal": 30, "simulation": 14, "rights": 7}
TRADE_WINDOW_DAYS = 14
APARTMENT = {"apartment", "아파트"}
SOURCE_FIELDS = {"asking_price": "희망가", "status": "거래 상태", "name": "매물명", "address": "주소", "area_sqm": "면적",
                 "property_type": "유형", "legal_region_code": "법정동", "identity": "동·호·층·면적 기준"}
STATUS_LABELS = {"active": "거래 가능", "withdrawn": "철회", "completed": "거래 완료", "unknown": "미확인"}
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def won(value) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "미확인"
    manwon = round(value / 10_000)
    eok, rest = divmod(manwon, 10_000)
    if eok and rest:
        return f"{eok:,}억 {rest:,}만원"
    return f"{eok:,}억원" if eok else f"{rest:,}만원"


def _epoch(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.strptime(text[:19].replace("T", " "), TIME_FORMAT).timestamp()
    except ValueError:
        return None


def _iso_epoch(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _condition(kind: str, subject: str, fingerprint: str, title: str, body: str, link: str, *,
               case_id: int | None = None, property_id: int | None = None, listing_id: int | None = None) -> dict:
    return {"kind": kind, "subject_key": subject, "fingerprint": fingerprint[:120], "title": title[:200], "body": body,
            "link": link, "case_id": case_id, "property_id": property_id, "listing_id": listing_id}


def _source_value(field: str, value) -> str:
    if field == "asking_price":
        return won(value)
    if field == "status":
        return STATUS_LABELS.get(str(value), "미확인")
    if field == "identity":
        return "변경"
    return "미입력" if value in (None, "") else str(value)


def _candidate_conditions(case: dict, candidate: dict, now: float) -> list[dict]:
    label = candidate.get("alias") or candidate.get("name") or f"후보 #{candidate['id']}"
    ids = {"case_id": case["id"], "property_id": candidate["id"]}
    link = f"/cases/{case['id']}#candidate-{candidate['id']}"
    found = []
    for analysis in candidate.get("analyses") or []:
        kind = analysis.get("analysis_type")
        if kind not in ANALYSIS_LABELS or analysis.get("status") != "stale":
            continue
        expires = _epoch(analysis.get("expires_at"))
        expired = expires is not None and expires < now
        analyzed = (analysis.get("analyzed_at") or "")[:10] or "이전"
        body = (f"{analyzed}에 한 분석의 유효기간({VALID_DAYS[kind]}일)이 지났습니다. 다시 실행해야 비교·요약에 현재 값으로 쓰입니다."
                if expired else "물건 정보가 바뀌어 이전 분석을 현재 값으로 쓰지 않습니다. 다시 실행해주세요.")
        found.append(_condition("analysis_expired", f"candidate:{candidate['id']}:{kind}",
                                f"{analysis.get('analyzed_at')}|{'expired' if expired else 'changed'}",
                                f"{label} · {ANALYSIS_LABELS[kind]} 분석 다시 확인", body, link, **ids))
    source = candidate.get("source_status") or {}
    if source.get("status") == "missing":
        found.append(_condition("source_changed", f"candidate:{candidate['id']}:source", "missing",
                                f"{label} · 원본 매물을 찾을 수 없습니다",
                                "보관함에서 삭제됐거나 조회할 수 없습니다. 후보의 가격·거래 상태를 직접 확인해주세요.", link, **ids))
    elif source.get("status") == "changed":
        changes = source.get("changes") or {}
        revision = (source.get("current") or {}).get("revision_id")
        parts = [f"{SOURCE_FIELDS.get(field, field)} {_source_value(field, values.get('saved'))} → {_source_value(field, values.get('current'))}"
                 for field, values in list(changes.items())[:3]]
        more = f" 외 {len(changes) - 3}건" if len(changes) > 3 else ""
        found.append(_condition("source_changed", f"candidate:{candidate['id']}:source",
                                f"rev:{revision}:{','.join(sorted(changes))}",
                                f"{label} · 원본 매물이 바뀌었습니다",
                                f"{', '.join(parts)}{more}. 후보 카드에서 확인한 뒤 반영하세요. 반영 전에는 저장 당시 값으로 검토합니다.",
                                link, **ids))
    return found


def _trade_target(case: dict, candidate: dict, now: float) -> dict | None:
    identity = candidate.get("identity") or {}
    region = str(candidate.get("legal_region_code") or "")
    area = candidate.get("area_sqm")
    # 타임라인 실거래 연결과 같은 조건: 아파트·법정동·전용면적. 공급·미확인 면적으로 다른 면적대 거래를 고르지 않는다.
    if (candidate.get("category") not in APARTMENT or len(region) != 10 or not region.isdigit()
            or not isinstance(area, (int, float)) or area <= 0 or identity.get("area_basis") != "exclusive"):
        return None
    # 후보 등록 시각으로 거르지 않는다. 등록 직전 2주 안에 수집된 거래도 검토에 새로 쓸 근거이고,
    # 저장 시각(서버 현지 시각 문자열)과 수집 시각(epoch)의 시간대 차이로 새 거래를 빠뜨리지 않기 위해서다.
    return {"subject": f"candidate:{candidate['id']}:trades", "case_id": case["id"], "property_id": candidate["id"],
            "label": candidate.get("alias") or candidate.get("name") or f"후보 #{candidate['id']}", "name": candidate.get("name") or "",
            "legal_region_code": region, "area_sqm": float(area), "since": now - TRADE_WINDOW_DAYS * 86400,
            "has_appraisal": any(a.get("analysis_type") == "appraisal" for a in candidate.get("analyses") or [])}


def _trade_conditions(targets: list[dict], find_trades) -> list[dict]:
    found, cache = [], {}
    for target in targets:
        key = (target["legal_region_code"], target["name"], round(target["area_sqm"], 2))
        if key not in cache:
            cache[key] = find_trades(legal_region_code=key[0], name=key[1], area_sqm=key[2])
        result = cache[key]
        fresh = [trade for trade in result.get("trades") or []
                 if isinstance(trade.get("first_seen_at"), (int, float)) and trade["first_seen_at"] >= target["since"]]
        if not fresh:
            continue
        latest = max(fresh, key=lambda trade: trade["deal_date"])
        newest_seen = int(max(trade["first_seen_at"] for trade in fresh))
        body = (f"최근 계약 {latest['deal_date']} · {latest['area_sqm']}㎡ · {won(latest['price_won'])}. "
                f"{result.get('complex_name') or '같은 단지'}의 전용면적 ±10% 신고 거래이며 현재 시세가 아닙니다.")
        if target["has_appraisal"]:
            body += " 시세 분석을 다시 확인해보세요."
        found.append(_condition("trade_update", target["subject"], str(newest_seen),
                                f"{target['label']} · 같은 단지 실거래 {len(fresh)}건 새로 반영",
                                body, f"/cases/{target['case_id']}#candidate-{target['property_id']}",
                                case_id=target["case_id"], property_id=target["property_id"]))
    return found


def _listing_conditions(listings: list[dict], now: float) -> list[dict]:
    found = []
    for listing in listings:
        if listing.get("status") != "active" or not listing.get("needs_confirmation"):
            continue
        confirmed = _iso_epoch(listing.get("confirmed_at"))
        collected = listing.get("last_collection_at")
        newer = isinstance(collected, (int, float)) and confirmed is not None and collected > confirmed
        days = int((now - confirmed) // 86400) if confirmed is not None else None
        label = listing.get("alias") or listing.get("name") or f"매물 #{listing['id']}"
        body = ("확인한 뒤 원문을 다시 수집한 기록이 있습니다. 바뀐 내용을 확인해 저장해주세요."
                if newer else
                f"마지막 확인 후 {days if days is not None else 7}일이 지났습니다. 거래 가능 여부와 가격을 다시 확인해 저장해야 후보 저장·추천에 쓰입니다.")
        found.append(_condition("listing_reconfirm", f"listing:{listing['id']}",
                                f"{listing.get('confirmed_at')}|{'collected' if newer else 'age'}",
                                f"{label} · 매물 재확인 필요", body,
                                f"/listings?listing_id={listing['id']}#saved-listings", listing_id=listing["id"]))
    return found


def notification_conditions(snapshots: list[dict], listings: list[dict], now: float, find_trades=None) -> dict:
    """현재 성립하는 알림 조건과, 실거래 알림 대상이 될 수 있는 후보(trade_subjects)를 돌려준다.

    trade_subjects는 Spring이 더 이상 대상이 아닌 후보(제외·삭제·면적 기준 변경)의 실거래 알림만 해결 처리하는 데 쓴다.
    새 거래가 없을 뿐인 후보의 기존 실거래 알림은 남긴다.
    """
    if find_trades is None:
        from backend.services.listing_trade_overlay import find_trades
    conditions, targets = [], []
    for snapshot in snapshots:
        case = decorate_stored_snapshot(snapshot)
        if case.get("status") == "archived":
            continue
        for candidate in case.get("properties") or []:
            if candidate.get("status") == "rejected":
                continue
            conditions.extend(_candidate_conditions(case, candidate, now))
            target = _trade_target(case, candidate, now)
            if target:
                targets.append(target)
    conditions.extend(_trade_conditions(targets, find_trades))
    conditions.extend(_listing_conditions(listings, now))
    return {"conditions": conditions, "trade_subjects": [target["subject"] for target in targets]}
