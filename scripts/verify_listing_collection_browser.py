"""실제 Chromium + 가상 원문으로 수집기를 검증한다. 네이버 성공 실측과 구분한다."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.async_api import BrowserContext
from backend.services.naver_listing_collector import collect_page


async def main():
    original = BrowserContext.new_page
    html = """<html><head><title>검증용 가상 단지 - 네이버페이 부동산</title></head><body>
    <p>매매 7억 5,000</p><p>공급/전용면적</p><p>112㎡/84.5㎡</p>
    <p>소재지</p><p>서울특별시 강남구 역삼동 123</p><p>확인매물 26.09.20.</p>
    </body></html>"""
    async def fixture_page(context):
        page = await original(context)
        # 페이지 단위 라우트로 가상 원문을 반환하므로 외부 네트워크에 접속하지 않는다.
        await page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html))
        return page
    with patch("backend.services.listing_collection_gate.reserve", return_value=0), patch.object(BrowserContext, "new_page", fixture_page):
        result = await collect_page("https://fin.land.naver.com/articles/123456")
        assert result["outcome"] == "observed", result
        assert result["fields"]["asking_price"] == 750000000
        assert result["fields"]["area_sqm"] == 84.5
        assert result["fields"]["status"] == "unknown"
        assert result["fetched_at"] >= result["requested_at"]
        html = "<html><body>페이지를 찾을 수 없습니다</body></html>"
        missing = await collect_page("https://fin.land.naver.com/articles/123456")
        assert missing["outcome"] == "unavailable" and not missing["fields"]
    # 실제 사이트에서 관찰한 내부 API 429 → 문서 200 오류 화면 이동을 그대로 재현한다.
    for status in (401, 403, 429):
        async def blocked_page(context):
            page = await original(context)
            async def respond(route):
                url = route.request.url
                if "/front-api/" in url:
                    await route.fulfill(status=status, headers={"Retry-After":"1800"}, content_type="application/json", body='{"detailCode":"TOO_MANY_REQUESTS"}')
                elif "/404" in url:
                    await route.fulfill(status=200, content_type="text/html", body="페이지를 찾을 수 없습니다")
                else:
                    await route.fulfill(status=200, content_type="text/html", body="""<html><body>로딩중<script>
                    fetch('/front-api/v1/article/key?articleNumber=123456').then(()=>location.href='/404');
                    </script></body></html>""")
            await page.route("**/*", respond)
            return page
        with patch("backend.services.listing_collection_gate.reserve", return_value=0), \
             patch("backend.services.listing_collection_gate.postpone", side_effect=lambda seconds: seconds) as postpone, \
             patch.object(BrowserContext, "new_page", blocked_page):
            blocked = await collect_page("https://fin.land.naver.com/articles/123456")
        assert blocked["outcome"] == "blocked", blocked
        assert blocked["upstream_status"] == status and blocked["restriction_source"] == "article_api"
        assert blocked["fields"] == {} and blocked["retry_after_seconds"] == 1800
        postpone.assert_called_once_with(1800)
    print("PASS 실제 Chromium + 가상 원문: 가격·전용면적·시점 추출, 원문 없음, 내부 API 401/403/429 뒤 오류 화면 분류")


if __name__ == "__main__":
    asyncio.run(main())
