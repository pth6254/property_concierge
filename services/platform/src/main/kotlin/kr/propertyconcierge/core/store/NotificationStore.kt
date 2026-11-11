package kr.propertyconcierge.core.store

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import kr.propertyconcierge.core.ApiFailure
import kr.propertyconcierge.core.bridge.PythonClient
import kr.propertyconcierge.core.listings.ListingService
import org.slf4j.LoggerFactory
import org.springframework.dao.DataAccessException
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Service
import org.springframework.transaction.support.TransactionTemplate
import java.time.Duration
import java.time.Instant
import java.time.temporal.ChronoUnit

data class NotificationCondition(val kind: String, val subjectKey: String, val fingerprint: String, val title: String,
    val body: String, val link: String, val caseId: Long?, val propertyId: Long?, val listingId: Long?)
data class OpenNotification(val id: Long, val kind: String, val subjectKey: String, val fingerprint: String)

/**
 * 변화 알림함(실거래 갱신·분석 만료·매물 7일 재확인·원본 변경).
 *
 * 조건 계산은 Python(analysis/notification-conditions)이 기존 화면과 같은 기준으로 하고, 여기서는 저장·읽음·해결만 한다.
 * - 같은 조건(kind·subject_key·fingerprint)은 한 번만 만든다. 조건이 바뀌면 새 알림, 더 이상 성립하지 않으면 해결(resolved_at) 처리한다.
 * - 동기화는 사용자가 알림을 볼 때 최소 간격을 두고 실행한다. 별도 일괄 작업이나 외부 발송(메일·푸시)은 하지 않는다.
 * - 원격 분석은 트랜잭션 밖에서 끝내고, 실패하면 기존 알림을 그대로 둔다(조건을 확인하지 못한 것을 해결로 처리하지 않는다).
 */
@Service
class NotificationStore(private val jdbc: JdbcTemplate, private val json: ObjectMapper, private val cases: CaseStore,
    private val listings: ListingService, private val python: PythonClient, private val redis: StringRedisTemplate,
    private val tx: TransactionTemplate) {
    private val log = LoggerFactory.getLogger(javaClass)
    // 컨테이너는 UTC라 시간대 없는 문자열은 화면에서 9시간 어긋나 보인다. 알림 시각은 UTC ISO(...Z)로 저장하고 화면이 현지 시각으로 바꾼다.
    // 같은 형식이라 문자열 비교로도 순서가 맞다(90일 정리).
    private fun now(daysAgo: Long = 0) = Instant.now().minus(Duration.ofDays(daysAgo)).truncatedTo(ChronoUnit.SECONDS).toString()

    fun sync(owner: Long, minIntervalSeconds: Long) {
        val key = "notifications:synced:$owner"
        val current = System.currentTimeMillis() / 1000.0
        val last = redis.opsForValue().get(key)?.toDoubleOrNull()
        if (last != null && current - last < minIntervalSeconds) return
        // 동시에 두 번 실행돼도 같은 조건은 고유 키로 한 번만 저장되므로 잠금 없이 시각만 기록한다.
        redis.opsForValue().set(key, current.toString(), Duration.ofHours(1))
        val caseIds = jdbc.queryForList("SELECT id FROM purchase_cases WHERE user_id=? AND status<>'archived' ORDER BY id LIMIT 100", Long::class.java, owner)
        val snapshots = caseIds.mapNotNull { cases.aggregate(owner, it) }
        val stale = listings.needingConfirmation(owner, 2000).map { item -> mapOf("id" to item.path("id").asLong(),
            "name" to item.path("name").asText(""), "alias" to item.path("alias").asText(""), "status" to item.path("status").asText(""),
            "confirmed_at" to item.get("confirmed_at")?.takeUnless(JsonNode::isNull)?.asText(),
            "needs_confirmation" to item.path("needs_confirmation").asBoolean(false),
            "last_collection_at" to item.get("last_collection_at")?.takeUnless(JsonNode::isNull)?.asDouble()) }
        val result = try {
            python.analyze("analysis/notification-conditions", mapOf("snapshots" to snapshots, "listings" to stale, "now" to current))
        } catch (error: ApiFailure) {
            redis.delete(key)
            log.warn("변화 알림 조건을 계산하지 못했습니다: status={}", error.status)
            return
        }
        // 넘긴 자료(본인 케이스·후보·매물)에 없는 ID를 가리키는 조건은 저장하지 않는다. 계산 결과만 믿고 타인 자료에 알림을 걸지 않기 위해서다.
        val propertyIds = snapshots.flatMap { snapshot -> (snapshot["properties"] as List<*>).map { entry ->
            ((entry as Map<*, *>)["property"] as JsonNode).path("id").asLong() } }.toSet()
        val listingIds = stale.map { it["id"] as Long }.toSet()
        val conditions = result.path("conditions").mapNotNull(::condition).filter { item ->
            (item.caseId == null || item.caseId in caseIds) && (item.propertyId == null || item.propertyId in propertyIds) &&
                (item.listingId == null || item.listingId in listingIds)
        }
        val tradeSubjects = result.path("trade_subjects").map(JsonNode::asText).toSet()
        try {
            tx.executeWithoutResult { persist(owner, conditions, tradeSubjects) }
        } catch (error: DataAccessException) {
            // 계산과 저장 사이에 후보·매물이 삭제되면 외래 키가 거부한다. 다음 동기화에서 다시 계산한다.
            redis.delete(key)
            log.warn("변화 알림 저장을 건너뜁니다: {}", error.javaClass.simpleName)
        }
    }

    private fun condition(node: JsonNode): NotificationCondition? {
        fun id(name: String) = node.get(name)?.takeIf { it.isIntegralNumber && it.asLong() > 0 }?.asLong()
        val value = NotificationCondition(node.path("kind").asText(), node.path("subject_key").asText(), node.path("fingerprint").asText(),
            node.path("title").asText(), node.path("body").asText(), node.path("link").asText(), id("case_id"), id("property_id"), id("listing_id"))
        return value.takeIf { valid(it) } ?: run { log.warn("형식이 다른 변화 알림 조건을 버립니다: kind={}", value.kind); null }
    }

    private fun persist(owner: Long, conditions: List<NotificationCondition>, tradeSubjects: Set<String>) {
        val time = now()
        for (item in conditions) {
            // 같은 조건이 다시 성립하면(예: 제외했던 후보를 되돌림) 읽음 기록은 두고 다시 연다.
            jdbc.update("""INSERT INTO user_notifications(user_id,kind,subject_key,fingerprint,title,body,link,case_id,property_id,listing_id,created)
                VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (user_id,kind,subject_key,fingerprint)
                DO UPDATE SET title=excluded.title,body=excluded.body,link=excluded.link,resolved_at=NULL""",
                owner, item.kind, item.subjectKey, item.fingerprint, item.title, item.body, item.link, item.caseId, item.propertyId, item.listingId, time)
        }
        val open = jdbc.query("SELECT id,kind,subject_key,fingerprint FROM user_notifications WHERE user_id=? AND resolved_at IS NULL", { row, _ ->
            OpenNotification(row.getLong("id"), row.getString("kind"), row.getString("subject_key"), row.getString("fingerprint")) }, owner)
        val resolved = resolutions(open, conditions, tradeSubjects)
        resolved.chunked(500).forEach { ids ->
            jdbc.update("UPDATE user_notifications SET resolved_at=? WHERE user_id=? AND id IN (${ids.joinToString(",") { "?" }})",
                time, owner, *ids.toTypedArray())
        }
        // 해결된 알림은 90일 뒤 지운다. 열린 알림은 기간과 무관하게 남긴다.
        jdbc.update("DELETE FROM user_notifications WHERE user_id=? AND resolved_at IS NOT NULL AND resolved_at<?", owner, now(90))
    }

    fun list(owner: Long): Map<String, Any?> {
        val items = jdbc.queryForList("""SELECT id,kind,title,body,link,case_id,property_id,listing_id,created,read_at
            FROM user_notifications WHERE user_id=? AND resolved_at IS NULL
            ORDER BY (read_at IS NULL) DESC, created DESC, id DESC LIMIT 100""", owner)
        return mapOf("items" to items, "unread_count" to unread(owner))
    }

    fun unread(owner: Long): Long = jdbc.queryForObject(
        "SELECT count(*) FROM user_notifications WHERE user_id=? AND resolved_at IS NULL AND read_at IS NULL", Long::class.java, owner) ?: 0

    fun read(owner: Long, id: Long) {
        // 다른 사용자의 알림 ID는 존재 여부를 드러내지 않도록 404로 처리한다(AGENTS 2-3).
        if (jdbc.queryForObject("SELECT count(*) FROM user_notifications WHERE id=? AND user_id=?", Long::class.java, id, owner) == 0L)
            throw ApiFailure(404, "알림을 찾을 수 없습니다")
        jdbc.update("UPDATE user_notifications SET read_at=? WHERE id=? AND user_id=? AND read_at IS NULL", now(), id, owner)
    }

    fun readAll(owner: Long): Int =
        jdbc.update("UPDATE user_notifications SET read_at=? WHERE user_id=? AND resolved_at IS NULL AND read_at IS NULL", now(), owner)

    companion object {
        val KINDS = setOf("analysis_expired", "source_changed", "listing_reconfirm", "trade_update")
        private val link = Regex("^/[a-z][A-Za-z0-9/_\\-?=&#.%]*$")

        fun valid(item: NotificationCondition) = item.kind in KINDS && item.subjectKey.length in 1..80 &&
            item.fingerprint.length in 1..120 && item.title.length in 1..200 && item.body.length in 1..2000 &&
            item.link.length <= 300 && link.matches(item.link) && !item.link.startsWith("//")

        /**
         * 열린 알림 중 해결할 ID.
         * - 분석 만료·원본 변경·매물 재확인: 이번 계산에 같은 조건이 없으면 해결한다(다시 분석·반영·재확인한 경우).
         * - 실거래 갱신: 새 거래가 없다고 사라지지 않는다. 같은 후보에 더 새로운 거래 알림이 생겼거나(대체),
         *   후보가 더 이상 대상이 아닐 때(제외·삭제·면적 기준 변경)만 해결한다.
         */
        fun resolutions(open: List<OpenNotification>, conditions: List<NotificationCondition>, tradeSubjects: Set<String>): List<Long> {
            val current = conditions.map { Triple(it.kind, it.subjectKey, it.fingerprint) }.toSet()
            val latestTrade = conditions.filter { it.kind == "trade_update" }.associate { it.subjectKey to it.fingerprint }
            return open.filter { item ->
                if (item.kind == "trade_update") item.subjectKey !in tradeSubjects ||
                    (latestTrade[item.subjectKey]?.let { it != item.fingerprint } ?: false)
                else Triple(item.kind, item.subjectKey, item.fingerprint) !in current
            }.map { it.id }
        }
    }
}
