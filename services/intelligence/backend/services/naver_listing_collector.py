"""개별 공개 매물의 화면만 읽는다. 접근 실패를 거래 종료로 추론하지 않는다."""
from __future__ import annotations

import asyncio
import re
import time
import math
from email.utils import parsedate_to_datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, parse_qs

HOSTS = {"land.naver.com", "new.land.naver.com", "fin.land.naver.com", "m.land.naver.com"}


def restriction_response(url: str, status: int, *, navigation: bool, article: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "fin.land.naver.com" or status not in (401, 403, 429):
        return False
    if navigation:
        return parsed.path in (f"/articles/{article}", "/map", "/404")
    query = parse_qs(parsed.query)
    # 광고·로그인·다른 매물의 오류를 현재 매물 차단으로 확대 해석하지 않는다.
    return ((parsed.path.startswith("/front-api/v1/article/") and query.get("articleNumber") == [article])
            or (parsed.path == "/front-api/v1/data-service/transport"
                and query.get("itemType") == ["article"] and query.get("itemId") == [article]))


def retry_seconds(value: str | None) -> int:
    from backend.services.listing_collection_gate import BLOCK_SECONDS
    try:
        seconds = int(value) if value and value.strip().isdigit() else math.ceil(parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        seconds = BLOCK_SECONDS
    return max(BLOCK_SECONDS, seconds)


def allow_browser_request(url: str, *, navigation: bool, article: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if navigation:
        listing_page = host == "fin.land.naver.com" and parsed.path.rstrip("/") == f"/articles/{article}"
        old_missing_page = host == "fin.land.naver.com" and parsed.path == "/404"
        missing_page = host == "financial.pstatic.net" and parsed.path == "/404.html"
        return parsed.scheme == "https" and (listing_page or old_missing_page or missing_page)
    return parsed.scheme == "https" and (host in HOSTS or host.endswith(".pstatic.net"))


def canonical_url(value: str) -> tuple[str, str]:
    try:
        url = urlsplit(value)
        if url.scheme != "https" or url.hostname not in HOSTS or url.username or url.password or url.port:
            raise ValueError()
        match = re.fullmatch(r"/articles/([0-9]{1,30})/?", url.path)
        ids = parse_qs(url.query).get("articleNo", [])
        article = match[1] if match else (ids[0] if len(ids) == 1 else "")
        if not re.fullmatch(r"[0-9]{1,30}", article):
            raise ValueError()
    except ValueError:
        raise ValueError("네이버 부동산 개별 매물 HTTPS 링크가 필요합니다") from None
    return f"https://fin.land.naver.com/articles/{article}", article


def parse_money(value: str) -> int | None:
    """원문 가격 표기의 무단위 부분은 만원. 범위·협의·복수 가격은 추측하지 않는다."""
    value = re.sub(r"[\s,]", "", value)
    match = re.fullmatch(r"(?:(\d+(?:\.\d+)?)억)?(?:(\d+(?:\.\d+)?)(만)?(?:원)?)?", value)
    if not match or not any(match.group(1, 2)):
        return None
    try:
        amount = Decimal(match[1] or 0) * 100000000
        if match[2]:
            amount += Decimal(match[2]) * (1 if value.endswith("원") and not match[3] and not match[1] else 10000)
        return int(amount) if amount == int(amount) and 0 <= amount <= 10**15 else None
    except InvalidOperation:
        return None


def parse_page(text: str, title: str, http_status: int = 200) -> dict:
    lines = [re.sub(r"\s+", " ", s).strip() for s in text.splitlines() if s.strip()]
    if http_status in (401, 403, 429) or re.search(r"비정상적인 접근|자동입력 방지|접근이 제한|보안 확인|captcha", text, re.I):
        return {"outcome": "blocked", "fields": {}, "message": "접근 제한 또는 보안 확인 화면입니다. 기존 매물 상태는 유지합니다."}
    if http_status in (404, 410) or re.search(r"존재하지 않는 매물|삭제된 매물|종료된 매물|매물 정보를 찾을 수 없|페이지를 찾을 수 없습니다", text):
        return {"outcome": "unavailable", "fields": {}, "message": "원문을 확인할 수 없습니다. 거래 완료 여부는 알 수 없습니다."}
    if http_status >= 400:
        return {"outcome": "failed", "fields": {}, "message": "원문 서버 오류입니다. 기존 매물 상태는 유지합니다."}
    fields = {}
    # 가격은 매매·전세·월세 표기가 같은 줄에 있는 단일 값만 채택한다.
    for index, line in enumerate(lines):
        price = re.fullmatch(r"(매매|전세|월세)\s*([\d.,억만원 /]+)", line)
        if not price and index + 1 < len(lines):
            label = {"매매가": "매매", "전세가": "전세", "전세금": "전세", "월세": "월세"}.get(line)
            if label:
                price = re.fullmatch(r"([\d.,억만원 /]+)", lines[index + 1])
                if price:
                    price = (label, price[1])
        if price:
            kind, raw = price if isinstance(price, tuple) else price.groups()
            parts = raw.split("/")
            values = [parse_money(part) for part in parts]
            if None not in values and len(values) == (2 if kind == "월세" else 1):
                fields["transaction_type"] = {"매매": "purchase", "전세": "lease", "월세": "rent"}[kind]
                fields["asking_price" if kind == "매매" else "deposit"] = values[0]
                if kind == "월세":
                    fields["monthly_rent"] = values[1]
                break
    address_candidates = []
    broker_section = False
    for i, line in enumerate(lines):
        if re.search(r"중개사(?:무소| 정보)?|중개업소|공인중개사", line):
            broker_section = True
        elif re.fullmatch(r"(?:매물|기본|상세|건물)\s*정보", line):
            broker_section = False
        joined = line + " " + (lines[i + 1] if i + 1 < len(lines) else "")
        area = re.search(r"(?:공급\s*/\s*전용면적\s*[\d.,]+\s*(?:㎡|m²|m2)?\s*/\s*|전용면적\s*[:：]?\s*)(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2)", joined)
        if area:
            fields["area_sqm"] = float(area[1])
        address_text = joined if re.fullmatch(r"소재지|주소|위치", line) else line
        address = re.match(r"(소재지|주소|위치)\s*[:：]?\s+(.+)", address_text)
        if address and not broker_section:
            # 중개사무소의 주소가 뒤에 나오더라도 매물 소재지를 덮어쓰지 않는다.
            address_candidates.append(({"소재지": 0, "위치": 1, "주소": 2}[address[1]], address[2][:500]))
        date = re.search(r"(?:매물확인일|확인매물|확인일)\s*[:：]?\s*(\d{2,4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}\.?)", joined)
        if date:
            fields["source_confirmed_date"] = date[1]
    if address_candidates:
        priority = min(item[0] for item in address_candidates)
        addresses = {value for rank, value in address_candidates if rank == priority}
        if len(addresses) == 1:
            fields["address"] = addresses.pop()
    if "transaction_type" not in fields or "area_sqm" not in fields:
        return {"outcome": "parse_error", "fields": fields, "message": "가격·전용면적을 모두 식별하지 못했습니다. 원문을 직접 확인해주세요."}
    heading = next((m[1] for line in lines if (m := re.fullmatch(r"(.{2,120}?)\s+(?:매매|전세|월세)\s+[\d.,억만원 /]+", line))), "")
    name = heading or re.sub(r"\s*[-|].*(?:네이버|Naver|Npay).*", "", title, flags=re.I)
    if name and not re.fullmatch(r"네이버(?:페이)?\s*부동산", name):
        fields["name"] = name[:150]
    # 페이지가 보인다는 사실과 거래 가능 여부는 서로 다른 증거다.
    fields["status"] = "unknown"
    return {"outcome": "observed", "fields": fields, "message": "원문 표시값을 읽었습니다. 거래 상태와 입력값을 확인한 뒤 저장해주세요."}


async def collect_page(url: str) -> dict:
    from playwright.async_api import async_playwright
    from backend.services import listing_collection_gate as gate
    canonical, article = canonical_url(url)
    started = time.time()
    restriction = None
    request_sent = False
    result = {}
    try:
        wait = await asyncio.to_thread(gate.reserve)
        if wait:
            return {"outcome": "blocked", "fields": {}, "message": gate.wait_message(wait),
                    "reason_code": "collection_cooldown", "request_sent": False,
                    "retry_after_seconds": wait, "retry_at": time.time() + wait,
                    "source_url": canonical, "external_id": article, "requested_at": started,
                    "fetched_at": time.time(), "parser_version": "naver-dom-v2"}
        async with asyncio.timeout(45):
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(service_workers="block", accept_downloads=False)
                    # 임의 입력 URL·외부 리디렉션·내부망 리소스에 서버 브라우저가 접근하지 않게 한다.
                    async def guard(route):
                        allowed = allow_browser_request(route.request.url,
                            navigation=route.request.is_navigation_request(), article=article)
                        if allowed and route.request.resource_type not in ("image", "media", "font"):
                            await route.continue_()
                        else:
                            await route.abort()
                    await context.route("**/*", guard)
                    page = await context.new_page()
                    def observe_response(response):
                        nonlocal restriction
                        if restriction_response(response.url, response.status,
                                                navigation=response.request.is_navigation_request(), article=article):
                            wait = retry_seconds(response.headers.get("retry-after"))
                            if restriction is None or wait > restriction["retry_after_seconds"]:
                                restriction = {"outcome": "blocked", "fields": {},
                                    "reason_code": f"naver_http_{response.status}", "upstream_status": response.status,
                                    "restriction_source": "document" if response.request.is_navigation_request() else "article_api",
                                    "retry_after_seconds": wait}
                    page.on("response", observe_response)
                    request_sent = True
                    response = await page.goto(canonical, wait_until="domcontentloaded", timeout=25000)
                    for _ in range(10):
                        if restriction:
                            break
                        body = await page.locator("body").inner_text(timeout=5000)
                        result = parse_page(body[:100000], await page.title(), response.status if response else 0)
                        if result["outcome"] != "parse_error":
                            break
                        await page.wait_for_timeout(700)
                finally:
                    await browser.close()
    except Exception as exc:
        # 브라우저 예외에는 실행 경로 등이 들어가므로 사용자 응답에는 정해진 메시지만 남긴다.
        result = {"outcome": "failed", "fields": {}, "message": "원문 조회에 실패했습니다. 브라우저 설치·네트워크 또는 접근 제한을 확인해주세요.", "error_type": type(exc).__name__}
    # 내부 API 차단 뒤 오류 화면으로 이동하거나 탐색 예외가 나도 최초 제한 증거를 보존한다.
    if restriction:
        result = restriction
    if result.get("outcome") == "blocked":
        wait = result.get("retry_after_seconds", gate.BLOCK_SECONDS)
        try:
            wait = await asyncio.to_thread(gate.postpone, wait)
        except Exception:
            # Redis 장애 중에는 다음 수집도 예약에 실패해 외부 요청이 나가지 않는다.
            result["cooldown_persisted"] = False
        result.update(retry_after_seconds=wait, retry_at=time.time() + wait,
                      message="네이버가 원문 접근을 제한했습니다. 매물 삭제나 거래 종료를 뜻하지 않습니다. " + gate.wait_message(wait))
    return {**result, "request_sent": request_sent, "source_url": canonical, "external_id": article,
            "requested_at": started, "fetched_at": time.time(), "parser_version": "naver-dom-v2"}
