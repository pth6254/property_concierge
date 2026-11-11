package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import jakarta.servlet.http.Cookie
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.integration.PlatformIntegrationSupport
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import java.time.Instant

class NotificationIT : PlatformIntegrationSupport() {
    private fun condition(kind: String, subject: String, fingerprint: String, caseId: Long, propertyId: Long? = null,
        listingId: Long? = null, link: String = "/cases/$caseId") = mapOf("kind" to kind, "subject_key" to subject,
        "fingerprint" to fingerprint, "title" to "$kind 제목", "body" to "본문", "link" to link,
        "case_id" to caseId, "property_id" to propertyId, "listing_id" to listingId)
    private fun answer(conditions: List<Map<String, Any?>>, tradeSubjects: List<String> = emptyList()): JsonNode =
        json.valueToTree(mapOf("conditions" to conditions, "trade_subjects" to tradeSubjects))
    private fun inbox(cookie: Cookie, ownerId: Long, fresh: Boolean = true): JsonNode {
        // 동기화 최소 간격을 비워 매 호출이 새로 계산하게 한다. 간격 자체는 아래 별도 검사에서 확인한다.
        if (fresh) redis.delete("notifications:synced:$ownerId")
        return body(request("GET", "/api/notifications", cookie = cookie))
    }

    @Test fun `알림은 조건별로 한 번 저장하고 해결·대체·읽음과 소유자 경계를 지킨다`() {
        val (ownerId, owner) = register()
        val caseId = case(owner)
        val propertyId = candidate(owner, caseId)
        val requests = mutableListOf<JsonNode>()
        var reply = answer(listOf(
            condition("analysis_expired", "candidate:$propertyId:rights", "t|expired", caseId, propertyId),
            condition("trade_update", "candidate:$propertyId:trades", "100", caseId, propertyId),
            condition("trade_update", "candidate:$propertyId:bad", "1", caseId, propertyId, link = "//evil.example")),
            listOf("candidate:$propertyId:trades"))
        notificationConditions = { requests.add(it); reply }

        val first = inbox(owner, ownerId)
        assertEquals(2, first.path("items").size(), "형식이 다른 링크는 저장하지 않음")
        assertEquals(2, first.path("unread_count").asInt())
        // 보관하지 않은 본인 케이스의 저장 스냅샷을 넘긴다.
        assertEquals(caseId, requests.last().path("snapshots")[0].path("case").path("id").asLong())
        // 같은 조건을 다시 계산해도 중복 저장하지 않는다.
        assertEquals(2, inbox(owner, ownerId).path("items").size())
        assertEquals(2L, count("user_notifications"))

        val tradeId = first.path("items").first { it.path("kind").asText() == "trade_update" }.path("id").asLong()
        request("POST", "/api/notifications/$tradeId/read", cookie = owner, expected = 204)
        assertEquals(1, body(request("GET", "/api/notifications/summary", cookie = owner)).path("unread_count").asInt())

        val (otherId, other) = register()
        request("POST", "/api/notifications/$tradeId/read", cookie = other, expected = 404)
        assertEquals(0, inbox(other, otherId).path("items").size())
        request("GET", "/api/notifications", expected = 401)

        // 분석을 다시 해 만료 조건이 사라지고, 같은 후보에 더 새 거래가 들어온 경우.
        reply = answer(listOf(condition("trade_update", "candidate:$propertyId:trades", "150", caseId, propertyId)),
            listOf("candidate:$propertyId:trades"))
        val second = inbox(owner, ownerId).path("items")
        assertEquals(listOf("trade_update"), second.map { it.path("kind").asText() })
        assertTrue(second[0].path("read_at").isNull, "새 거래 묶음은 새 알림으로 읽지 않음 상태")

        // 새 거래가 없을 뿐이면 남기고, 후보가 대상에서 빠지면 해결한다.
        reply = answer(emptyList(), listOf("candidate:$propertyId:trades"))
        assertEquals(1, inbox(owner, ownerId).path("items").size())
        reply = answer(emptyList(), emptyList())
        assertEquals(0, inbox(owner, ownerId).path("items").size())

        // 같은 조건이 다시 성립하면 기존 기록을 다시 연다(읽음 기록 유지).
        reply = answer(listOf(condition("trade_update", "candidate:$propertyId:trades", "100", caseId, propertyId)),
            listOf("candidate:$propertyId:trades"))
        val reopened = inbox(owner, ownerId).path("items")
        assertEquals(1, reopened.size()); assertFalse(reopened[0].path("read_at").isNull)

        // 계산에 실패하면 확인하지 못한 조건을 해결로 처리하지 않는다.
        notificationConditions = { throw ApiFailure(503, "분석 서비스에 연결하지 못했습니다") }
        assertEquals(1, inbox(owner, ownerId).path("items").size())

        // 후보를 지우면 그 후보의 알림도 지운다.
        notificationConditions = { reply }
        request("DELETE", "/api/cases/$caseId/properties/$propertyId", cookie = owner, expected = 204)
        assertEquals(0L, jdbc.queryForObject("SELECT count(*) FROM user_notifications WHERE property_id=?", Long::class.java, propertyId))
    }

    @Test fun `재확인이 필요한 거래 가능 매물만 넘기고 모두 읽음과 동기화 간격을 지킨다`() {
        val (ownerId, owner) = register()
        import(owner, listOf(row(id = "old", time = Instant.now().minusSeconds(8 * 86400L)), row(id = "fresh", unit = "502"),
            row(id = "gone", status = "withdrawn", unit = "503", time = Instant.now().minusSeconds(9 * 86400L))))
        val listingId = jdbc.queryForObject("SELECT id FROM imported_listings WHERE external_id='old'", Long::class.java)!!
        var calls = 0
        notificationConditions = { request ->
            calls += 1
            val listings = request.path("listings")
            assertEquals(listOf(listingId), listings.map { it.path("id").asLong() }, "7일 지난 거래 가능 매물만")
            assertTrue(listings[0].path("needs_confirmation").asBoolean())
            answer(listOf(mapOf("kind" to "listing_reconfirm", "subject_key" to "listing:$listingId", "fingerprint" to "c|age",
                "title" to "재확인", "body" to "본문", "link" to "/listings?listing_id=$listingId#saved-listings", "listing_id" to listingId)))
        }
        assertEquals(1, inbox(owner, ownerId).path("unread_count").asInt())
        // 메뉴 개수 조회는 최소 간격 안에서 다시 계산하지 않는다.
        request("GET", "/api/notifications/summary", cookie = owner)
        request("GET", "/api/notifications/summary", cookie = owner)
        assertEquals(1, calls)
        assertEquals(1, body(request("POST", "/api/notifications/read-all", cookie = owner)).path("updated").asInt())
        assertEquals(0, body(request("GET", "/api/notifications/summary", cookie = owner)).path("unread_count").asInt())
    }
}
