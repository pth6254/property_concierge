package kr.propertyconcierge.core.listings

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.databind.node.ObjectNode
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime

/**
 * 사용자가 저장한 확인값(변경 이력)과 원문 수집 시도를 한 화면용 요약으로 만든다.
 * 서비스가 처음 관측한 시점 이전은 알 수 없으므로 기간은 항상 "서비스 관측기간"이다.
 * 수집 실패·페이지 미노출은 가격 변경이나 거래 상태로 해석하지 않는다.
 */
class ListingTimeline(private val json: ObjectMapper) {
    private val metrics = mapOf(
        "purchase" to listOf("asking_price" to "희망 매매가"),
        "lease" to listOf("deposit" to "전세 보증금"),
        "rent" to listOf("deposit" to "보증금", "monthly_rent" to "월세"),
    )

    private fun instant(node: JsonNode, fallback: Double): Instant =
        node.path("confirmed_at").asText("").let { text ->
            runCatching { OffsetDateTime.parse(text).toInstant() }.getOrNull()
        } ?: Instant.ofEpochMilli((fallback * 1000).toLong())

    private fun amount(node: JsonNode, key: String): Long? =
        node.get(key)?.takeIf { it.isIntegralNumber && it.canConvertToLong() }?.asLong()

    /** revisions: (저장 시각 초, payload) 쌍. observations: (수집 시각 초, outcome, payload) 3개 값. */
    fun build(listingId: Long, revisions: List<Pair<Double, JsonNode>>, observations: List<Triple<Double, String, JsonNode>>,
        needsConfirmation: Boolean): ObjectNode {
        val points = revisions.map { (imported, payload) -> Triple(instant(payload, imported), imported, payload) }.sortedBy { it.first }
        val out = json.createObjectNode().put("listing_id", listingId).put("basis", "service_observed")
        if (points.isEmpty()) {
            out.putArray("points"); out.putArray("metrics"); out.putArray("status_changes")
            out.putNull("period")
        } else {
            val type = points.last().third.path("transaction_type").asText("")
            out.put("transaction_type", type)
            out.put("needs_confirmation", needsConfirmation)
            val pointArray = out.putArray("points")
            points.forEach { (confirmed, imported, payload) ->
                pointArray.addObject().put("confirmed_at", confirmed.toString()).put("imported_at", Instant.ofEpochMilli((imported * 1000).toLong()).toString())
                    .put("status", payload.path("status").asText("unknown")).also { node ->
                        for (key in listOf("asking_price", "deposit", "monthly_rent")) amount(payload, key)?.let { node.put(key, it) } ?: node.putNull(key)
                    }
            }
            val metricArray = out.putArray("metrics")
            for ((key, label) in metrics[type].orEmpty()) {
                val values = points.mapNotNull { amount(it.third, key) }
                if (values.isEmpty()) continue
                val initial = values.first(); val current = values.last()
                val node = metricArray.addObject().put("key", key).put("label", label).put("initial", initial).put("current", current)
                    .put("change_count", values.zipWithNext().count { (a, b) -> a != b })
                    .put("lowest", values.min()).put("highest", values.max())
                if (initial > 0) node.put("cumulative_change_pct",
                    BigDecimal(current - initial).multiply(BigDecimal(100)).divide(BigDecimal(initial), 1, RoundingMode.HALF_EVEN).toDouble())
                else node.putNull("cumulative_change_pct")
            }
            val changes = out.putArray("status_changes")
            points.zipWithNext().forEach { (before, after) ->
                val a = before.third.path("status").asText("unknown"); val b = after.third.path("status").asText("unknown")
                if (a != b) changes.addObject().put("at", after.first.toString()).put("from", a).put("to", b)
            }
            out.putObject("period").put("first_confirmed_at", points.first().first.toString())
                .put("last_confirmed_at", points.last().first.toString())
                .put("days", Duration.between(points.first().first, points.last().first).toDays())
                .put("saved_versions", points.size)
        }
        val ordered = observations.sortedBy { it.first }
        val collection = out.putObject("collection")
        collection.put("attempts", ordered.size)
        collection.put("observed", ordered.count { it.second == "observed" })
        collection.put("unreadable", ordered.count { it.second != "observed" })
        ordered.lastOrNull()?.let { collection.put("last_attempt_at", Instant.ofEpochMilli((it.first * 1000).toLong()).toString()).put("last_outcome", it.second) }
            ?: collection.putNull("last_attempt_at")
        val latestPoint = points.lastOrNull()?.third
        val recent = collection.putArray("recent")
        ordered.takeLast(10).reversed().forEach { (fetched, outcome, payload) ->
            val node = recent.addObject().put("fetched_at", Instant.ofEpochMilli((fetched * 1000).toLong()).toString()).put("outcome", outcome)
            if (outcome == "observed") {
                val fields = payload.path("fields")
                val differs = mutableListOf<String>()
                for (key in listOf("asking_price", "deposit", "monthly_rent")) {
                    val seen = amount(fields, key)
                    seen?.let { node.put("observed_$key", it) }
                    // 원문 표시값은 사용자가 확인·저장하기 전까지 저장값을 바꾸지 않는다. 다르면 알리기만 한다.
                    if (seen != null && latestPoint != null && amount(latestPoint, key) != seen) differs.add(key)
                }
                node.put("differs_from_saved", differs.isNotEmpty())
                node.putArray("differing_fields").also { array -> differs.forEach(array::add) }
            }
        }
        out.putArray("limitations").also {
            it.add("서비스가 처음 저장·관측하기 전의 가격 변화는 알 수 없습니다. 표시 기간은 서비스 관측기간입니다.")
            it.add("원문을 읽지 못한 시도(차단·미노출·오류)는 거래 완료나 가격 변경을 뜻하지 않습니다.")
            it.add("가격 인하는 협상 가능성이나 매도인 사정을 확정하는 근거가 아닙니다.")
        }
        return out
    }
}
