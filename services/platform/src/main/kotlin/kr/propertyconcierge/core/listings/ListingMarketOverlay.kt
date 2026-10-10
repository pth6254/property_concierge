package kr.propertyconcierge.core.listings

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate

/** 후보에 연결된 저장 분석 한 건. 분석을 새로 실행하거나 바꾸지 않고 저장된 값만 보여준다. */
data class OverlayAnalysis(val propertyId: Long, val caseId: Long, val status: String, val analyzedAt: String?, val summary: JsonNode)

/**
 * 호가 이력 위에 겹쳐 볼 동일 단지 실거래와 저장된 AVM 결과를 정리한다.
 * 가격 판단을 만들지 않는다. 전용면적 기준이 확인된 아파트 매매만 대상이며 AVM은 비교 가능 기준을 통과한 값만 표시한다.
 */
class ListingMarketOverlay(private val json: ObjectMapper) {
    private val recentMonths = 6
    private val minimumTrades = 3

    private fun median(values: List<Long>): Long {
        val sorted = values.sorted(); val mid = sorted.size / 2
        return if (sorted.size % 2 == 1) sorted[mid] else (sorted[mid - 1] + sorted[mid] + 1) / 2
    }

    fun build(listing: JsonNode, trades: JsonNode?, analyses: List<OverlayAnalysis>, today: LocalDate = LocalDate.now()): ObjectNode {
        val out = json.createObjectNode().put("listing_id", listing.path("id").asLong())
        val reason = when {
            listing.path("transaction_type").asText() != "purchase" -> "매매 매물만 실거래와 비교합니다"
            listing.path("property_type").asText() != "apartment" -> "아파트 실거래만 연결합니다"
            listing.path("area_basis").asText() != "exclusive" -> "전용면적 기준이 확인되지 않아 실거래와 연결하지 않았습니다. 면적 기준을 확인해 저장하면 표시됩니다"
            listing.path("legal_region_code").isNull || listing.path("legal_region_code").asText("").length != 10 -> "법정동이 확인되지 않아 실거래와 연결하지 않았습니다"
            else -> ""
        }
        out.put("applicable", reason.isEmpty()).put("reason", reason)
        val asking = listing.path("asking_price").takeIf { it.isIntegralNumber && it.canConvertToLong() }?.asLong()
        val area = listing.path("area_sqm").asDouble(0.0)
        out.putObject("asking").also {
            if (asking == null) it.putNull("price_won") else it.put("price_won", asking)
            if (asking == null || area <= 0) it.putNull("per_sqm_won") else it.put("per_sqm_won", Math.round(asking / area))
            it.put("confirmed_at", listing.path("confirmed_at").asText(""))
        }
        if (reason.isNotEmpty() || trades == null) {
            out.putNull("trades")
        } else out.set<JsonNode>("trades", trades)
        out.set<JsonNode>("summary", summary(asking, area, trades, today))
        val avm = out.putArray("avm")
        analyses.forEach { analysis ->
            val value = analysis.summary
            val estimate = value.path("estimated_value").takeIf { it.isIntegralNumber && it.canConvertToLong() && it.asLong() > 0 }?.asLong()
            val eligible = value.path("valuation").path("comparison_eligible").asBoolean(false) &&
                value.path("result_kind").asText(value.path("valuation").path("result_kind").asText()) == "market_reference"
            val shown = reason.isEmpty() && estimate != null && eligible
            avm.addObject().put("property_id", analysis.propertyId).put("case_id", analysis.caseId).put("status", analysis.status)
                .put("analyzed_at", analysis.analyzedAt ?: "").put("shown", shown)
                .put("note", if (shown) "" else "시장가격 비교 기준을 통과하지 못한 분석이라 가격은 표시하지 않습니다").also {
                    if (shown) it.put("estimated_value_won", estimate) else it.putNull("estimated_value_won")
                }
        }
        out.putArray("limitations").also {
            it.add("실거래는 신고 지연이 있어 최근 거래가 일부 빠질 수 있으며 저장된 자료의 마지막 거래월까지만 보입니다.")
            it.add("시점수정과 층·향·동 보정을 하지 않았습니다. 호가·실거래·AVM은 서로 다른 자료이며 이 비교는 적정가격 판단이 아닙니다.")
            it.add("AVM 표시는 저장된 분석이며 기준일이 지났거나 원본이 바뀌면 오래된 값입니다.")
        }
        return out
    }

    private fun summary(asking: Long?, area: Double, trades: JsonNode?, today: LocalDate): ObjectNode {
        val node = json.createObjectNode().put("recent_window_months", recentMonths)
        val all = trades?.path("trades")?.toList().orEmpty()
        val cutoff = today.minusMonths(recentMonths.toLong())
        val recent = all.filter { runCatching { LocalDate.parse(it.path("deal_date").asText()) >= cutoff }.getOrDefault(false) }
        node.put("recent_count", recent.size)
        val status = when {
            trades == null || all.isEmpty() -> "no_trades"
            recent.size < minimumTrades -> "insufficient"
            asking == null || area <= 0 -> "no_asking"
            else -> "ok"
        }
        node.put("status", status)
        if (recent.isEmpty()) node.putNull("recent_median_per_sqm_won")
        else node.put("recent_median_per_sqm_won", median(recent.map { it.path("price_per_sqm_won").asLong() }))
        if (status == "ok" && asking != null) {
            val unit = BigDecimal(asking).divide(BigDecimal.valueOf(area), 4, RoundingMode.HALF_EVEN)
            val base = BigDecimal(node.path("recent_median_per_sqm_won").asLong())
            node.put("asking_vs_recent_median_pct", unit.subtract(base).multiply(BigDecimal(100)).divide(base, 1, RoundingMode.HALF_EVEN).toDouble())
        } else node.putNull("asking_vs_recent_median_pct")
        return node
    }
}
