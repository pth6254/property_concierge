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
        // 타임라인은 같은 이력에서 만들며 저장하지 않은 값이나 수집 시도를 가격 변경으로 만들지 않는다.
        val timeline = body(request("GET", "/api/listings/${saved.path("id").asLong()}/timeline", cookie=cookie))
        assertEquals(2, timeline.path("period").path("saved_versions").asInt())
        val metric = timeline.path("metrics").single()
        assertEquals(1, metric.path("change_count").asInt()); assertEquals(700_000_000L, metric.path("current").asLong())
        assertEquals("withdrawn", timeline.path("status_changes").single().path("to").asText())
        assertEquals(0, timeline.path("collection").path("attempts").asInt())
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
    @Test fun `시장 겹쳐 보기는 저장 실거래와 본인 후보의 저장 AVM만 읽고 조회 실패에도 호가 이력을 유지한다`() {
        val (_, cookie) = register(); import(cookie, listOf(row()))
        val id = body(request("GET", "/api/listings", cookie=cookie)).path("items").single().path("id").asLong()
        val first = body(request("GET", "/api/listings/$id/market-overlay", cookie=cookie))
        assertTrue(first.path("applicable").asBoolean()); assertEquals("1168010100", first.path("trades").path("echo").path("legal_region_code").asText())
        assertEquals("확인 후보", first.path("trades").path("echo").path("name").asText()); assertEquals(84.9, first.path("trades").path("echo").path("area_sqm").asDouble())
        assertEquals(0, first.path("avm").size())
        // 같은 사용자의 후보에 저장된 AVM. 시장가격 비교 기준을 통과한 값만 가격을 보여준다.
        val case = case(cookie); val property = candidate(cookie, case)
        jdbc.update("UPDATE case_properties SET source_listing_id=? WHERE id=?", id, property)
        jdbc.update("""INSERT INTO candidate_analyses(case_id,property_id,analysis_type,status,summary,analyzed_at,created,updated)
            VALUES (?,?,'appraisal','completed',?::json,'2026-10-01 10:00:00','2026-10-01 10:00:00','2026-10-01 10:00:00')""", case, property,
            """{"estimated_value":780000000,"result_kind":"market_reference","valuation":{"comparison_eligible":true,"result_kind":"market_reference"}}""")
        val withAvm = body(request("GET", "/api/listings/$id/market-overlay", cookie=cookie)).path("avm").single()
        assertTrue(withAvm.path("shown").asBoolean()); assertEquals(780_000_000L, withAvm.path("estimated_value_won").asLong())
        val before = count("listing_revisions")
        tradesFailure = true
        val degraded = body(request("GET", "/api/listings/$id/market-overlay", cookie=cookie))
        assertFalse(degraded.path("trades").path("available").asBoolean()); assertEquals(1, degraded.path("avm").size())
        assertEquals(before, count("listing_revisions"))  // 조회는 저장 상태를 바꾸지 않는다
        val (_, other) = register()
        request("GET", "/api/listings/$id/market-overlay", cookie=other, expected=404)
    }
    @Test fun `재확인은 확인 시각·상태·가격만 새 이력으로 저장하고 이전 시각·잘못된 금액·타인 매물은 거부한다`() {
        val (_, cookie) = register(); import(cookie, listOf(row(time=Instant.now().minusSeconds(9*86400))))
        val id = body(request("GET", "/api/listings", cookie=cookie)).path("items").single().path("id").asLong()
        assertTrue(body(request("GET", "/api/listings/$id", cookie=cookie)).path("needs_confirmation").asBoolean())
        val checked = Instant.now().minusSeconds(5)
        val saved = body(request("POST", "/api/listings/$id/confirm", mapOf("confirmed_at" to checked.toString(), "status" to "active", "asking_price" to 790_000_000), cookie))
        assertFalse(saved.path("needs_confirmation").asBoolean()); assertEquals(790_000_000L, saved.path("asking_price").asLong())
        // 물건 정보와 별칭은 그대로 둔다
        assertEquals("101동", saved.path("building_dong").asText()); assertEquals("임장", saved.path("alias").asText()); assertEquals(84.9, saved.path("area_sqm").asDouble())
        assertEquals(2, body(request("GET", "/api/listings/$id/history", cookie=cookie)).path("items").size())
        // 같은 시각 재저장, 매매에 보증금, 0원, 미래 시각, 잘못된 상태는 저장하지 않는다
        request("POST", "/api/listings/$id/confirm", mapOf("confirmed_at" to checked.toString(), "status" to "active", "asking_price" to 780_000_000), cookie, 409)
        val later = Instant.now().toString()
        request("POST", "/api/listings/$id/confirm", mapOf("confirmed_at" to later, "status" to "active", "asking_price" to 1, "deposit" to 1), cookie, 422)
        request("POST", "/api/listings/$id/confirm", mapOf("confirmed_at" to later, "status" to "active", "asking_price" to 0), cookie, 422)
        request("POST", "/api/listings/$id/confirm", mapOf("confirmed_at" to Instant.now().plusSeconds(3600).toString(), "status" to "active", "asking_price" to 1), cookie, 422)
        request("POST", "/api/listings/$id/confirm", mapOf("confirmed_at" to later, "status" to "sold", "asking_price" to 1), cookie, 422)
        request("POST", "/api/listings/$id/confirm", mapOf("confirmed_at" to "2026-10-10T10:00:00", "status" to "active", "asking_price" to 1), cookie, 422)
        assertEquals(2, body(request("GET", "/api/listings/$id/history", cookie=cookie)).path("items").size())
        val (_, other) = register()
        request("POST", "/api/listings/$id/confirm", mapOf("confirmed_at" to later, "status" to "active", "asking_price" to 1), other, 404)
    }
    @Test fun `타인의 매물 이력과 후보 저장은 모두 404이다`() {
        val (_, cookie) = register(); import(cookie, listOf(row()))
        val id = body(request("GET", "/api/listings", cookie=cookie)).path("items").single().path("id").asLong()
        val (_, other) = register(); val case = case(other)
        assertEquals(0, body(request("GET", "/api/listings", cookie=other)).path("total").asInt())
        request("GET", "/api/listings/$id", cookie=other, expected=404)
        request("GET", "/api/listings/$id/history", cookie=other, expected=404)
        request("GET", "/api/listings/$id/timeline", cookie=other, expected=404)
        request("POST", "/api/listings/$id/candidate", mapOf("case_id" to case), other, 404)
    }
}
