package kr.propertyconcierge.core.listings

import kr.propertyconcierge.core.integration.PlatformIntegrationSupport
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import java.time.Instant

class ListingPersistenceIT : PlatformIntegrationSupport() {
    @Test fun `저장 중복 갱신 오래된 입력과 변경 이력을 보존한다`() {
        val (_, cookie) = register(); val first = row(time=Instant.now().minusSeconds(60))
        assertEquals(1, import(cookie, listOf(first)).path("created").asInt())
        assertEquals(1, import(cookie, listOf(first)).path("unchanged").asInt())
        assertEquals(1, import(cookie, listOf(row(price=700_000_000, status="withdrawn"))).path("updated").asInt())
        assertEquals(1, import(cookie, listOf(first)).path("skipped_older").asInt())
        val saved = body(request("GET", "/api/listings", cookie=cookie)).path("items").single()
        assertEquals(700_000_000L, saved.path("asking_price").asLong()); assertEquals("withdrawn", saved.path("status").asText())
        assertEquals(2, body(request("GET", "/api/listings/${saved.path("id").asLong()}/history", cookie=cookie)).path("items").size())
    }
    @Test fun `배치 중간의 상충 갱신은 새 행과 변경 이력까지 롤백한다`() {
        val (_, cookie) = register(); val first = row()
        import(cookie, listOf(first)); val conflict = first.deepCopy<com.fasterxml.jackson.databind.node.ObjectNode>()
        (conflict.path("payload") as com.fasterxml.jackson.databind.node.ObjectNode).put("asking_price", 900_000_000)
        import(cookie, listOf(row(id="new-before-conflict"), conflict), expected=409)
        assertEquals(1L, count("imported_listings")); assertEquals(1L, count("listing_revisions"))
        val saved = body(request("GET", "/api/listings", cookie=cookie)).path("items").single()
        assertEquals(800_000_000L, saved.path("asking_price").asLong())
    }
    @Test fun `주소가 같아도 광고와 개별 호를 합치지 않는다`() {
        val (_, cookie) = register()
        import(cookie, listOf(row(id="ad-501", unit="501"), row(id="ad-502", unit="502")))
        val items = body(request("GET", "/api/listings", cookie=cookie)).path("items")
        assertEquals(setOf("501", "502"), items.map { it.path("unit_number").asText() }.toSet())
        assertEquals(2, items.size())
    }
    @Test fun `지역 가격 페이지와 확인 시점 필터는 실제 저장된 자료에 적용된다`() {
        val (_, cookie) = register()
        import(cookie, listOf(row(id="fresh", price=800_000_000), row(id="old", price=600_000_000, time=Instant.now().minusSeconds(9*86400)),
            row(id="withdrawn", price=500_000_000, status="withdrawn")))
        assertEquals(1, body(request("GET", "/api/listings?region_code=1168000000&fresh_only=true&budget_max=800000000", cookie=cookie)).path("total").asInt())
        assertEquals(2, body(request("GET", "/api/listings?budget_max=700000000", cookie=cookie)).path("total").asInt())
        assertEquals(1, body(request("GET", "/api/listings?page_size=1&page=2", cookie=cookie)).path("items").size())
        request("GET", "/api/listings?region_code=bad", cookie=cookie, expected=422)
        request("GET", "/api/listings?page=0", cookie=cookie, expected=422)
    }
    @Test fun `타인의 매물 이력과 후보 저장은 모두 404이다`() {
        val (_, cookie) = register(); import(cookie, listOf(row()))
        val id = body(request("GET", "/api/listings", cookie=cookie)).path("items").single().path("id").asLong()
        val (_, other) = register(); val case = case(other)
        assertEquals(0, body(request("GET", "/api/listings", cookie=other)).path("total").asInt())
        request("GET", "/api/listings/$id", cookie=other, expected=404)
        request("GET", "/api/listings/$id/history", cookie=other, expected=404)
        request("POST", "/api/listings/$id/candidate", mapOf("case_id" to case), other, 404)
    }
}
