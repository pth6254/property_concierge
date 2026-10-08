package kr.propertyconcierge.core.listings

import com.fasterxml.jackson.databind.JsonNode
import kr.propertyconcierge.core.CoreConfiguration
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ListingTimelineTest {
    private val json = CoreConfiguration().objectMapper()
    private val timeline = ListingTimeline(json)
    private fun payload(price: Long, confirmed: String, status: String = "active", type: String = "purchase", extra: String = "") =
        json.readTree("""{"transaction_type":"$type","status":"$status","confirmed_at":"$confirmed",${if (type == "purchase") """"asking_price":$price""" else """"deposit":$price"""}$extra}""")
    private fun seconds(iso: String) = java.time.Instant.parse(iso).epochSecond.toDouble()

    @Test fun `가격 변경 횟수와 누적 변화율은 저장한 확인값 기준이며 순서가 뒤섞여도 시간순이다`() {
        val revisions = listOf(
            seconds("2026-09-20T00:00:00Z") to payload(900_000_000, "2026-09-20T00:00:00Z", status = "withdrawn"),
            seconds("2026-09-01T00:00:00Z") to payload(1_000_000_000, "2026-09-01T00:00:00Z"),
            seconds("2026-09-10T00:00:00Z") to payload(950_000_000, "2026-09-10T00:00:00Z"),
            seconds("2026-09-12T00:00:00Z") to payload(950_000_000, "2026-09-12T00:00:00Z", status = "withdrawn"),
        )
        val result = timeline.build(7, revisions, emptyList(), false)
        val metric = result.path("metrics").first()
        assertEquals("asking_price", metric.path("key").asText())
        assertEquals(1_000_000_000L, metric.path("initial").asLong()); assertEquals(900_000_000L, metric.path("current").asLong())
        assertEquals(2, metric.path("change_count").asInt()); assertEquals(-10.0, metric.path("cumulative_change_pct").asDouble())
        assertEquals(900_000_000L, metric.path("lowest").asLong()); assertEquals(1_000_000_000L, metric.path("highest").asLong())
        assertEquals("2026-09-01T00:00:00Z", result.path("period").path("first_confirmed_at").asText())
        assertEquals(19, result.path("period").path("days").asInt()); assertEquals(4, result.path("period").path("saved_versions").asInt())
        assertEquals("service_observed", result.path("basis").asText())
        // active → withdrawn 은 사용자가 저장한 상태 변경일 때만 보인다.
        val change = result.path("status_changes").single()
        assertEquals("active", change.path("from").asText()); assertEquals("withdrawn", change.path("to").asText())
    }

    @Test fun `수집 실패는 가격 변경이나 거래 상태로 바뀌지 않고 원문 표시값 차이는 알림만 한다`() {
        val revisions = listOf(seconds("2026-09-01T00:00:00Z") to payload(1_000_000_000, "2026-09-01T00:00:00Z"))
        val observations = listOf(
            Triple(seconds("2026-09-05T00:00:00Z"), "blocked", json.readTree("""{"fields":{}}""")),
            Triple(seconds("2026-09-06T00:00:00Z"), "observed", json.readTree("""{"fields":{"asking_price":950000000}}""")),
            Triple(seconds("2026-09-07T00:00:00Z"), "unavailable", json.readTree("""{"fields":{}}""")),
        )
        val result = timeline.build(7, revisions, observations, true)
        assertEquals(0, result.path("metrics").first().path("change_count").asInt())
        assertEquals(1_000_000_000L, result.path("metrics").first().path("current").asLong())
        assertTrue(result.path("status_changes").isEmpty)
        val collection = result.path("collection")
        assertEquals(3, collection.path("attempts").asInt()); assertEquals(1, collection.path("observed").asInt()); assertEquals(2, collection.path("unreadable").asInt())
        assertEquals("unavailable", collection.path("last_outcome").asText())
        val observed: JsonNode = collection.path("recent").first { it.path("outcome").asText() == "observed" }
        assertTrue(observed.path("differs_from_saved").asBoolean()); assertEquals("asking_price", observed.path("differing_fields").single().asText())
        assertFalse(collection.path("recent").first { it.path("outcome").asText() == "blocked" }.has("differs_from_saved"))
        assertTrue(result.path("needs_confirmation").asBoolean())
    }

    @Test fun `월세는 보증금과 월세를 따로 추적하고 이력이 없으면 빈 요약을 낸다`() {
        val revisions = listOf(
            seconds("2026-09-01T00:00:00Z") to payload(50_000_000, "2026-09-01T00:00:00Z", type = "rent", extra = ""","monthly_rent":1500000"""),
            seconds("2026-09-08T00:00:00Z") to payload(50_000_000, "2026-09-08T00:00:00Z", type = "rent", extra = ""","monthly_rent":1400000"""),
        )
        val metrics = timeline.build(1, revisions, emptyList(), false).path("metrics")
        assertEquals(listOf("deposit", "monthly_rent"), metrics.map { it.path("key").asText() })
        assertEquals(0, metrics[0].path("change_count").asInt()); assertEquals(1, metrics[1].path("change_count").asInt())
        val empty = timeline.build(1, emptyList(), emptyList(), false)
        assertTrue(empty.path("points").isEmpty); assertTrue(empty.path("period").isNull)
        assertEquals(0, empty.path("collection").path("attempts").asInt())
    }
}
