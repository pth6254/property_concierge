package kr.propertyconcierge.core.listings

import kr.propertyconcierge.core.CoreConfiguration
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.time.LocalDate

class ListingMarketOverlayTest {
    private val json = CoreConfiguration().objectMapper()
    private val overlay = ListingMarketOverlay(json)
    private val today = LocalDate.of(2026, 10, 1)
    private fun listing(basis: String = "exclusive", type: String = "purchase", property: String = "apartment", price: Long = 3_000_000_000L, region: String = "1165010700") =
        json.readTree("""{"id":9,"transaction_type":"$type","property_type":"$property","area_basis":"$basis","legal_region_code":"$region",
            "asking_price":$price,"area_sqm":84.0,"confirmed_at":"2026-09-30T00:00:00Z"}""")
    private fun trades(vararg rows: Pair<String, Long>) = json.readTree("""{"available":true,"trades":[${
        rows.joinToString(",") { """{"deal_date":"${it.first}","price_won":${it.second * 84},"price_per_sqm_won":${it.second},"area_sqm":84.0,"floor":"5"}""" }}]}""")
    private fun analysis(summary: String, status: String = "completed") =
        OverlayAnalysis(3, 2, status, "2026-09-20 10:00:00", json.readTree(summary))

    @Test fun `최근 6개월 거래가 3건 이상일 때만 호가 대비 차이를 계산한다`() {
        val enough = overlay.build(listing(), trades("2026-09-10" to 34_000_000L, "2026-08-10" to 36_000_000L, "2026-07-10" to 35_000_000L, "2025-01-10" to 20_000_000L), emptyList(), today)
        assertTrue(enough.path("applicable").asBoolean())
        assertEquals(3, enough.path("summary").path("recent_count").asInt()); assertEquals("ok", enough.path("summary").path("status").asText())
        assertEquals(35_000_000L, enough.path("summary").path("recent_median_per_sqm_won").asLong())
        // 호가 30억 / 84㎡ = 35,714,286원/㎡ → 중앙값 대비 +2.0%
        assertEquals(2.0, enough.path("summary").path("asking_vs_recent_median_pct").asDouble())
        val thin = overlay.build(listing(), trades("2026-09-10" to 34_000_000L, "2026-08-10" to 36_000_000L), emptyList(), today)
        assertEquals("insufficient", thin.path("summary").path("status").asText()); assertTrue(thin.path("summary").path("asking_vs_recent_median_pct").isNull)
        assertEquals("no_trades", overlay.build(listing(), json.readTree("""{"available":false,"trades":[]}"""), emptyList(), today).path("summary").path("status").asText())
    }

    @Test fun `전용면적 기준 미확인과 매매 아파트가 아닌 매물은 실거래와 연결하지 않는다`() {
        for (bad in listOf(listing(basis = "unknown"), listing(basis = "supply"), listing(type = "lease"), listing(property = "officetel"), listing(region = "null"))) {
            val result = overlay.build(bad, trades("2026-09-10" to 34_000_000L), emptyList(), today)
            assertFalse(result.path("applicable").asBoolean(), bad.toString()); assertTrue(result.path("trades").isNull)
            assertTrue(result.path("reason").asText().isNotBlank())
        }
    }

    @Test fun `AVM은 시장가격 비교 기준을 통과한 저장 분석만 가격을 보여주고 나머지는 값을 숨긴다`() {
        val ok = analysis("""{"estimated_value":2900000000,"result_kind":"market_reference","valuation":{"comparison_eligible":true,"result_kind":"market_reference"}}""")
        val withheld = analysis("""{"estimated_value":2900000000,"result_kind":"withheld","valuation":{"comparison_eligible":false,"result_kind":"withheld"}}""")
        val legacy = analysis("""{"estimated_value":2900000000}""", status = "stale")
        val result = overlay.build(listing(), trades("2026-09-10" to 34_000_000L), listOf(ok, withheld, legacy), today)
        val avm = result.path("avm")
        assertTrue(avm[0].path("shown").asBoolean()); assertEquals(2_900_000_000L, avm[0].path("estimated_value_won").asLong())
        for (index in 1..2) { assertFalse(avm[index].path("shown").asBoolean()); assertTrue(avm[index].path("estimated_value_won").isNull) }
        assertEquals("stale", avm[2].path("status").asText())
        assertEquals(3, result.path("limitations").size())
    }
}
