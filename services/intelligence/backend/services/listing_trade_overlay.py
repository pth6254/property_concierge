"""매물 타임라인에 겹쳐 볼 동일 단지 실거래. 저장된 거래만 읽으며 외부 호출·가격 추정은 하지 않는다."""
from __future__ import annotations

from datetime import date
from statistics import median

from sqlalchemy import select

from db.base import session_scope
from db.models import Transaction

APT_ENDPOINT = "RTMSDataSvcAptTrade"
SUFFIXES = ("아파트", "주상복합", "타운", "타워")
LIMIT = 300


def _key(name: str | None) -> str:
    text = "".join((name or "").split())
    for suffix in SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _empty(reason: str, **extra) -> dict:
    return {"available": False, "reason": reason, "trades": [], "complex_name": "", "match": "none", **extra}


def _deal_date(row) -> date | None:
    try:
        return date(int(row.deal_year or row.deal_ym[:4]), int(row.deal_month or row.deal_ym[4:]), int(row.deal_day))
    except (TypeError, ValueError):
        return None


def find_trades(*, legal_region_code: str, name: str, area_sqm: float, months: int = 24,
                tolerance: float = .10, today: date | None = None) -> dict:
    """같은 시군구의 아파트 거래 중 이름이 일치하는 단지를 면적 ±10%로 좁힌다.

    이름이 여러 단지에 걸리거나 일치하지 않으면 추측하지 않고 비운다. 동 코드가 있는 행은 같은 법정동만 쓴다."""
    today = today or date.today()
    if len(legal_region_code or "") != 10 or not legal_region_code.isdigit() or not _key(name) or not area_sqm or area_sqm <= 0:
        return _empty("주소·단지명·면적을 확인할 수 없어 실거래를 연결하지 않았습니다")
    index = today.year * 12 + today.month - 1 - months
    start = f"{index // 12:04d}{index % 12 + 1:02d}"
    with session_scope() as session:
        latest = session.scalar(select(Transaction.deal_ym).where(Transaction.lawd_cd == legal_region_code[:5],
            Transaction.endpoint == APT_ENDPOINT).order_by(Transaction.deal_ym.desc()).limit(1))
        rows = session.scalars(select(Transaction).where(Transaction.lawd_cd == legal_region_code[:5],
            Transaction.endpoint == APT_ENDPOINT, Transaction.deal_ym >= start, Transaction.is_cancelled.is_(False),
            Transaction.price > 0, Transaction.area_sqm > 0)).all()
    if not latest:
        return _empty("이 지역의 저장된 실거래가 없습니다")
    rows = [row for row in rows if not row.bjdong_code or row.bjdong_code == legal_region_code]
    target = _key(name)
    exact = [row for row in rows if _key(row.apt_name) == target]
    match, chosen = "exact", exact
    if not chosen:
        partial = {row.apt_name for row in rows if len(_key(row.apt_name)) >= 3 and (target in _key(row.apt_name) or _key(row.apt_name) in target)}
        if len(partial) == 1:
            match, chosen = "partial_unique", [row for row in rows if row.apt_name in partial]
        elif partial:
            return _empty("비슷한 이름의 단지가 여러 곳이라 연결하지 않았습니다", data_through=latest)
    if not chosen:
        return _empty("이름이 일치하는 단지의 저장된 거래가 없습니다", data_through=latest)
    names = {row.apt_name for row in chosen}
    trades, seen = [], set()
    for row in chosen:
        day = _deal_date(row)
        if day is None or day > today or abs(row.area_sqm / area_sqm - 1) > tolerance + 1e-6:
            continue
        identity = (day, row.floor, row.area_sqm, row.price)
        if identity in seen:
            continue
        seen.add(identity)
        won = row.price * 10_000  # 국토부 신고 금액은 만원 단위
        trades.append({"deal_date": day.isoformat(), "floor": str(row.floor or ""), "area_sqm": row.area_sqm,
                       "price_won": won, "price_per_sqm_won": round(won / row.area_sqm)})
    trades.sort(key=lambda item: item["deal_date"], reverse=True)
    return {"available": bool(trades), "reason": "" if trades else "면적이 비슷한 거래가 기간 안에 없습니다",
            "complex_name": sorted(names)[0], "match": match, "window_months": months, "area_tolerance_pct": round(tolerance * 100),
            "data_through": latest, "trade_total": len(trades), "trades": trades[:LIMIT],
            "median_per_sqm_won": round(median(t["price_per_sqm_won"] for t in trades)) if trades else None}
