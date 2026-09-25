"""외부 요청 제한을 Redis에서 원자적으로 공유하고 무관한 오류는 제외한다."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from backend.services import listing_collection_gate as gate
from backend.services.naver_listing_collector import restriction_response, retry_seconds
from db.redis_client import get_redis


@pytest.fixture(autouse=True)
def isolated_gate(monkeypatch):
    monkeypatch.setattr(gate, "KEY", "test:listing-collection:gate")
    get_redis().delete(gate.KEY)
    yield
    get_redis().delete(gate.KEY)


def test_only_one_concurrent_browser_can_start():
    with ThreadPoolExecutor(max_workers=8) as pool:
        waits = list(pool.map(lambda _: gate.reserve(), range(8)))
    assert waits.count(0) == 1
    assert all(0 < v <= 60 for v in waits if v)
    assert gate.remaining() > 0


def test_block_extends_but_does_not_shorten_shared_wait():
    assert gate.reserve() == 0
    assert gate.postpone(1800) == 1800
    assert gate.postpone(900) >= 1799
    assert gate.reserve() >= 1799
    get_redis().expire(gate.KEY, 0)
    assert gate.reserve() == 0


@pytest.mark.parametrize("status", [401, 403, 429])
def test_only_current_article_restrictions_count(status):
    base = "https://fin.land.naver.com"
    assert restriction_response(base + "/front-api/v1/article/key?articleNumber=123", status, navigation=False, article="123")
    assert restriction_response(base + "/front-api/v1/data-service/transport?itemType=article&itemId=123", status, navigation=False, article="123")
    assert restriction_response(base + "/map?layer=test", status, navigation=True, article="123")
    for url in [base + "/front-api/v1/auth/userInfo", base + "/front-api/v1/article/key?articleNumber=124",
                base + "/front-api/v1/data-service/transport?itemType=complex&itemId=123",
                "https://ads.example.com/front-api/v1/article/key?articleNumber=123"]:
        assert not restriction_response(url, status, navigation=False, article="123")
    assert not restriction_response(base + "/front-api/v1/article/key?articleNumber=123", 500, navigation=False, article="123")


def test_retry_after_seconds_and_http_date(monkeypatch):
    assert retry_seconds("120") == 900
    assert retry_seconds("1800") == 1800
    assert retry_seconds("invalid") == 900
    assert retry_seconds(None) == 900
    monkeypatch.setattr("backend.services.naver_listing_collector.time.time", lambda: 0)
    assert retry_seconds("Thu, 01 Jan 1970 01:00:00 GMT") == 3600


def test_cooldown_returns_without_opening_browser():
    import asyncio
    from unittest.mock import patch
    from backend.services.naver_listing_collector import collect_page
    gate.postpone(900)
    with patch("playwright.async_api.async_playwright", side_effect=AssertionError("브라우저가 열리면 안 됨")):
        result = asyncio.run(collect_page("https://fin.land.naver.com/articles/123"))
    assert result["outcome"] == "blocked"
    assert result["reason_code"] == "collection_cooldown"
    assert result["request_sent"] is False and result["fields"] == {}


def test_redis_failure_never_opens_browser(monkeypatch):
    import asyncio
    from unittest.mock import patch
    from backend.services.naver_listing_collector import collect_page
    def broken():
        raise ConnectionError("격리 Redis 장애")
    monkeypatch.setattr(gate, "reserve", broken)
    with patch("playwright.async_api.async_playwright", side_effect=AssertionError("브라우저가 열리면 안 됨")):
        result = asyncio.run(collect_page("https://fin.land.naver.com/articles/123"))
    assert result["outcome"] == "failed" and result["request_sent"] is False
